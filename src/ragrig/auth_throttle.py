from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

from fastapi import HTTPException, status

from ragrig.observability import log_event

if TYPE_CHECKING:
    from ragrig.config import Settings

logger = logging.getLogger(__name__)


@dataclass
class _LoginAttemptWindow:
    failures: deque[float] = field(default_factory=deque)
    locked_until: float = 0.0


class AuthLoginAttemptLimiter:
    """In-memory login failure limiter keyed by IP + normalized email hash."""

    def __init__(
        self,
        settings: "Settings",
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._enabled = settings.ragrig_auth_login_rate_limit_enabled
        self._max_failures = max(1, settings.ragrig_auth_login_max_failures)
        self._window_seconds = max(1, settings.ragrig_auth_login_window_seconds)
        self._lockout_seconds = max(1, settings.ragrig_auth_login_lockout_seconds)
        self._clock = clock
        self._windows: dict[str, _LoginAttemptWindow] = {}
        self._lock = threading.Lock()

    def check_allowed(self, *, email: str, ip: str | None) -> None:
        if not self._enabled:
            return
        now = self._clock()
        key = self._key(email=email, ip=ip)
        with self._lock:
            window = self._windows.get(key)
            if window is None:
                return
            self._prune(window, now)
            if window.locked_until > now:
                retry_after = max(1, int(window.locked_until - now) + 1)
                self._raise_locked(email=email, ip=ip, retry_after=retry_after)

    def record_failure(self, *, email: str, ip: str | None) -> None:
        if not self._enabled:
            return
        now = self._clock()
        retry_after = 0
        locked = False
        key = self._key(email=email, ip=ip)
        with self._lock:
            window = self._windows.setdefault(key, _LoginAttemptWindow())
            self._prune(window, now)
            if window.locked_until > now:
                retry_after = max(1, int(window.locked_until - now) + 1)
            else:
                window.failures.append(now)
                if len(window.failures) >= self._max_failures:
                    window.locked_until = now + self._lockout_seconds
                    retry_after = self._lockout_seconds
                    locked = True

        if locked:
            log_event(
                logger,
                logging.WARNING,
                "auth.login.locked",
                reason="too_many_failures",
                email_sha256=self._hash_email(email),
                ip_sha256=self._hash_optional(ip),
                max_failures=self._max_failures,
                window_seconds=self._window_seconds,
                retry_after_seconds=retry_after,
            )
        if retry_after:
            self._raise_locked(email=email, ip=ip, retry_after=retry_after)

    def record_success(self, *, email: str, ip: str | None) -> None:
        if not self._enabled:
            return
        key = self._key(email=email, ip=ip)
        with self._lock:
            self._windows.pop(key, None)

    def _prune(self, window: _LoginAttemptWindow, now: float) -> None:
        cutoff = now - self._window_seconds
        while window.failures and window.failures[0] <= cutoff:
            window.failures.popleft()
        if window.locked_until <= now and not window.failures:
            window.locked_until = 0.0

    def _raise_locked(self, *, email: str, ip: str | None, retry_after: int) -> None:
        log_event(
            logger,
            logging.WARNING,
            "auth.login.rate_limited",
            email_sha256=self._hash_email(email),
            ip_sha256=self._hash_optional(ip),
            retry_after_seconds=retry_after,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many login attempts",
            headers={"Retry-After": str(retry_after)},
        )

    @staticmethod
    def _key(*, email: str, ip: str | None) -> str:
        normalized_email = email.strip().lower()
        ip_part = ip or "unknown"
        return hashlib.sha256(f"{ip_part}:{normalized_email}".encode("utf-8")).hexdigest()

    @staticmethod
    def _hash_email(email: str) -> str:
        return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()

    @staticmethod
    def _hash_optional(value: str | None) -> str | None:
        if not value:
            return None
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
