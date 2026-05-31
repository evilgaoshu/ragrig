from collections.abc import Callable
from importlib import import_module

import psycopg

from ragrig.config import Settings
from ragrig.reranker import fake_reranker_policy


def create_database_check(settings: Settings) -> Callable[[], None]:
    def check_database() -> None:
        with psycopg.connect(settings.database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()

    return check_database


def build_reranker_health(settings: Settings) -> dict[str, object]:
    return fake_reranker_policy(settings)


def build_redis_health(settings: Settings) -> dict[str, object]:
    backend = settings.ragrig_task_backend
    if backend != "arq":
        return {
            "status": "skipped",
            "backend": backend,
            "detail": f"Redis health check skipped for task backend '{backend}'.",
        }

    try:
        redis = import_module("redis")
    except Exception:
        return {
            "status": "error",
            "backend": backend,
            "detail": "redis package is not installed; install ragrig[task-queue].",
        }

    client = None
    try:
        client = redis.Redis.from_url(  # type: ignore[attr-defined]
            settings.ragrig_redis_url,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
        client.ping()
    except Exception as exc:
        return {
            "status": "error",
            "backend": backend,
            "detail": _safe_health_detail(str(exc)),
        }
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()

    return {
        "status": "connected",
        "backend": backend,
    }


def _safe_health_detail(detail: str) -> str:
    redacted = detail
    for prefix in ("redis://", "rediss://"):
        if prefix in redacted and "@" in redacted:
            scheme, rest = redacted.split(prefix, 1)
            credentials, host = rest.split("@", 1)
            if ":" in credentials:
                redacted = f"{scheme}{prefix}[redacted]@{host}"
    return redacted[:240]
