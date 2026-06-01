from __future__ import annotations

import pytest
from fastapi import HTTPException

from ragrig.auth_throttle import AuthLoginAttemptLimiter
from ragrig.config import Settings

pytestmark = pytest.mark.unit


def test_login_attempt_limiter_locks_after_configured_failures() -> None:
    now = 0.0

    def clock() -> float:
        return now

    limiter = AuthLoginAttemptLimiter(
        Settings(
            ragrig_auth_login_rate_limit_enabled=True,
            ragrig_auth_login_max_failures=2,
            ragrig_auth_login_window_seconds=60,
            ragrig_auth_login_lockout_seconds=30,
        ),
        clock=clock,
    )

    limiter.check_allowed(email="User@example.com", ip="203.0.113.9")
    limiter.record_failure(email="User@example.com", ip="203.0.113.9")

    with pytest.raises(HTTPException) as exc_info:
        limiter.record_failure(email=" user@example.com ", ip="203.0.113.9")

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers["Retry-After"] == "30"

    with pytest.raises(HTTPException):
        limiter.check_allowed(email="user@example.com", ip="203.0.113.9")


def test_login_attempt_limiter_success_clears_failures() -> None:
    limiter = AuthLoginAttemptLimiter(
        Settings(
            ragrig_auth_login_rate_limit_enabled=True,
            ragrig_auth_login_max_failures=2,
        ),
    )

    limiter.record_failure(email="user@example.com", ip="203.0.113.9")
    limiter.record_success(email="user@example.com", ip="203.0.113.9")

    limiter.record_failure(email="user@example.com", ip="203.0.113.9")
