"""In-process sliding-window rate limiter for RAGRig.

Applies per-workspace (or per-IP when auth is off) request limits to
the search/answer and ingestion routes. Uses a thread-safe in-memory
token bucket — suitable for single-process deployments.

When RAGRIG_RATE_LIMIT_ENABLED=false (default) every check is a no-op.

Config:
    RAGRIG_RATE_LIMIT_ENABLED          bool  default False
    RAGRIG_RATE_LIMIT_SEARCH_RPM       int   default 60   (search + answer)
    RAGRIG_RATE_LIMIT_INGEST_RPM       int   default 20   (upload + ingest)
    RAGRIG_RATE_LIMIT_BURST_FACTOR     float default 1.5  (burst headroom)
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import TYPE_CHECKING

from fastapi import HTTPException, status

if TYPE_CHECKING:
    from ragrig.config import Settings


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

    def check_search(self, key: str) -> None:
        """Raise HTTP 429 if the search/answer rate is exceeded for *key*."""
        if not self._enabled:
            return
        window = self._get_window(self._search_windows, key, self._search_rpm)
        allowed, retry_after = window.allow()
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"search rate limit exceeded — retry in {retry_after}s",
                headers={"Retry-After": str(retry_after)},
            )

    def check_ingest(self, key: str) -> None:
        """Raise HTTP 429 if the ingest rate is exceeded for *key*."""
        if not self._enabled:
            return
        window = self._get_window(self._ingest_windows, key, self._ingest_rpm)
        allowed, retry_after = window.allow()
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"ingest rate limit exceeded — retry in {retry_after}s",
                headers={"Retry-After": str(retry_after)},
            )
