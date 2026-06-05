"""In-process sliding-window rate limiter for RAGRig.

Applies per-workspace (or per-IP when auth is off) request limits to
the search/answer and ingestion routes. Uses a thread-safe in-memory
sliding-window counter suitable for single-process deployments.

Multi-worker or replicated deployments need a gateway, Redis-backed limiter,
or another external shared limiter. The ARQ task queue only moves background
work out of the API process; it does not share API request limiter state.

When RAGRIG_RATE_LIMIT_ENABLED=false (default) every check is a no-op.

Config:
    RAGRIG_RATE_LIMIT_ENABLED          bool  default False
    RAGRIG_RATE_LIMIT_SEARCH_RPM       int   default 60   (search + answer)
    RAGRIG_RATE_LIMIT_INGEST_RPM       int   default 20   (upload + ingest)
    RAGRIG_RATE_LIMIT_BURST_FACTOR     float default 1.5  (burst headroom)
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import deque
from typing import TYPE_CHECKING

from fastapi import HTTPException, status

from ragrig.observability import log_event

if TYPE_CHECKING:
    from ragrig.config import Settings

logger = logging.getLogger(__name__)


class _SlidingWindow:
    """Thread-safe sliding-window counter (1-minute window)."""

    def __init__(self, rpm: int, burst_factor: float = 1.5) -> None:
        self._rpm = rpm
        self._limit = max(1, int(rpm * burst_factor))
        self._window = 60.0
        self._timestamps: deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self) -> tuple[bool, int]:
        """Return (allowed, retry_after_seconds)."""
        now = time.monotonic()
        cutoff = now - self._window
        with self._lock:
            while self._timestamps and self._timestamps[0] <= cutoff:
                self._timestamps.popleft()
            if len(self._timestamps) >= self._limit:
                oldest = self._timestamps[0]
                retry_after = max(1, int(oldest + self._window - now) + 1)
                return False, retry_after
            self._timestamps.append(now)
            return True, 0


class RateLimiter:
    """Holds per-key sliding windows and enforces limits."""

    def __init__(self, settings: "Settings") -> None:
        self._enabled = settings.ragrig_rate_limit_enabled
        self._search_rpm = settings.ragrig_rate_limit_search_rpm
        self._ingest_rpm = settings.ragrig_rate_limit_ingest_rpm
        self._burst = settings.ragrig_rate_limit_burst_factor
        self._search_windows: dict[str, _SlidingWindow] = {}
        self._ingest_windows: dict[str, _SlidingWindow] = {}
        self._lock = threading.Lock()

    def _get_window(self, store: dict[str, _SlidingWindow], key: str, rpm: int) -> _SlidingWindow:
        with self._lock:
            if key not in store:
                store[key] = _SlidingWindow(rpm, self._burst)
            return store[key]

    def _check(
        self,
        *,
        operation: str,
        key: str,
        store: dict[str, _SlidingWindow],
        rpm: int,
    ) -> None:
        if not self._enabled:
            return
        window = self._get_window(store, key, rpm)
        allowed, retry_after = window.allow()
        key_sha256 = hashlib.sha256(key.encode("utf-8")).hexdigest()
        if allowed:
            log_event(
                logger,
                logging.INFO,
                "rate_limit.allowed",
                operation=operation,
                key_sha256=key_sha256,
                rpm=rpm,
                limit=window._limit,
            )
            return
        log_event(
            logger,
            logging.WARNING,
            "rate_limit.exceeded",
            operation=operation,
            key_sha256=key_sha256,
            rpm=rpm,
            limit=window._limit,
            retry_after_seconds=retry_after,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"{operation} rate limit exceeded — retry in {retry_after}s",
            headers={"Retry-After": str(retry_after)},
        )

    def check_search(self, key: str) -> None:
        """Raise HTTP 429 if the search/answer rate is exceeded for *key*."""
        self._check(
            operation="search",
            key=key,
            store=self._search_windows,
            rpm=self._search_rpm,
        )

    def check_ingest(self, key: str) -> None:
        """Raise HTTP 429 if the ingest rate is exceeded for *key*."""
        self._check(
            operation="ingest",
            key=key,
            store=self._ingest_windows,
            rpm=self._ingest_rpm,
        )
