"""ARQ async task queue worker.

Run with: python -m ragrig.worker
Or: arq ragrig.worker.WorkerSettings

Activated when RAGRIG_TASK_BACKEND=arq.
Requires: pip install ragrig[task-queue]
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ragrig.tasks import TaskExecutor, TaskJob

logger = logging.getLogger(__name__)

_JOB_FUNCTION = "ragrig.worker.run_job"


async def run_job(ctx: dict, serialized_job: bytes) -> None:
    """ARQ job entry-point — deserializes and calls the pickled callable."""
    import pickle

    job: TaskJob = pickle.loads(serialized_job)  # noqa: S301
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, job)


class ArqTaskExecutor(TaskExecutor):
    """Pushes jobs to a Redis-backed ARQ queue."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._pool: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _get_pool(self) -> Any:
        try:
            import arq  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "arq and redis are required for the ARQ task backend. "
                "Install with: pip install 'ragrig[task-queue]'"
            ) from exc

        from arq import create_pool
        from arq.connections import RedisSettings

        if self._pool is None:
            arq_settings = RedisSettings.from_dsn(self._redis_url)
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
            self._pool = self._loop.run_until_complete(create_pool(arq_settings))
        return self._pool

    def submit(self, job: TaskJob) -> None:
        import pickle

        pool = self._get_pool()
        serialized = pickle.dumps(job)
        assert self._loop is not None
        self._loop.run_until_complete(pool.enqueue_job(_JOB_FUNCTION, serialized))

    def shutdown(self, wait: bool = True) -> None:
        if self._pool is not None and self._loop is not None:
            self._loop.run_until_complete(self._pool.aclose())
            self._pool = None


def _make_worker_settings_class(redis_url: str, max_jobs: int) -> type:
    """Build an ARQ WorkerSettings class.  Requires arq to be installed."""
    from arq.connections import RedisSettings

    _redis = RedisSettings.from_dsn(redis_url)
    _max_jobs = max_jobs

    class WorkerSettings:
        functions = [run_job]
        redis_settings = _redis
        max_jobs = _max_jobs
        job_timeout = 3600

    return WorkerSettings


def _get_worker_settings() -> type:
    from ragrig.config import get_settings

    s = get_settings()
    return _make_worker_settings_class(s.ragrig_redis_url, s.ragrig_task_queue_max_jobs)


class _LazyWorkerSettings:
    """Proxy that builds WorkerSettings on first attribute access (avoids import-time arq dep)."""

    _delegate: type | None = None

    def _load(self) -> type:
        if self._delegate is None:
            self._delegate = _get_worker_settings()
        return self._delegate

    def __getattr__(self, name: str) -> Any:
        return getattr(self._load(), name)

    def __class_getitem__(cls, item: Any) -> Any:
        return cls._load()


# Exposed for `arq ragrig.worker.WorkerSettings`
WorkerSettings: Any = _LazyWorkerSettings()


if __name__ == "__main__":
    from arq import run_worker

    run_worker(_get_worker_settings())
