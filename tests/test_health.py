import sys
import types
from collections.abc import Callable

import httpx
import pytest

from ragrig.config import Settings
from ragrig.main import create_app

pytestmark = pytest.mark.smoke


@pytest.fixture
def make_client() -> Callable[[Callable[[], None], Settings | None], httpx.AsyncClient]:
    def _make_client(
        check_database: Callable[[], None], settings: Settings | None = None
    ) -> httpx.AsyncClient:
        app = create_app(check_database=check_database, settings=settings)
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(transport=transport, base_url="http://testserver")

    return _make_client


@pytest.mark.anyio
async def test_health_reports_database_connection(
    make_client: Callable[[Callable[[], None]], httpx.AsyncClient],
) -> None:
    async with make_client(lambda: None) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "app": "ok",
        "db": "connected",
        "redis": {
            "status": "skipped",
            "backend": "threadpool",
            "detail": "Redis health check skipped for task backend 'threadpool'.",
        },
        "reranker": {
            "status": "development_fallback_allowed",
            "provider": "reranker.bge",
            "fake_reranker_allowed": True,
            "policy": "non_production_fallback",
            "detail": "Fake reranker fallback is allowed outside production.",
            "app_env": "development",
        },
        "version": "0.1.0",
    }


@pytest.mark.anyio
async def test_health_returns_503_when_database_check_fails(
    make_client: Callable[[Callable[[], None]], httpx.AsyncClient],
) -> None:
    def failing_check() -> None:
        raise RuntimeError("database unavailable")

    async with make_client(failing_check) as client:
        response = await client.get("/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unhealthy",
        "app": "ok",
        "db": "error",
        "detail": "database unavailable",
        "redis": {
            "status": "skipped",
            "backend": "threadpool",
            "detail": "Redis health check skipped for task backend 'threadpool'.",
        },
        "reranker": {
            "status": "development_fallback_allowed",
            "provider": "reranker.bge",
            "fake_reranker_allowed": True,
            "policy": "non_production_fallback",
            "detail": "Fake reranker fallback is allowed outside production.",
            "app_env": "development",
        },
        "version": "0.1.0",
    }


@pytest.mark.anyio
async def test_health_reports_redis_connected_for_arq_backend(
    make_client: Callable[[Callable[[], None], Settings | None], httpx.AsyncClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRedisClient:
        def ping(self) -> bool:
            return True

        def close(self) -> None:
            return None

    class FakeRedis:
        @staticmethod
        def from_url(_url: str, **_kwargs) -> FakeRedisClient:
            return FakeRedisClient()

    fake_redis = types.ModuleType("redis")
    fake_redis.Redis = FakeRedis
    monkeypatch.setitem(sys.modules, "redis", fake_redis)

    settings = Settings(ragrig_task_backend="arq")
    async with make_client(lambda: None, settings) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["redis"] == {"status": "connected", "backend": "arq"}


@pytest.mark.anyio
async def test_health_returns_503_when_arq_redis_check_fails(
    make_client: Callable[[Callable[[], None], Settings | None], httpx.AsyncClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRedisClient:
        def ping(self) -> None:
            raise RuntimeError("redis unavailable")

        def close(self) -> None:
            return None

    class FakeRedis:
        @staticmethod
        def from_url(_url: str, **_kwargs) -> FakeRedisClient:
            return FakeRedisClient()

    fake_redis = types.ModuleType("redis")
    fake_redis.Redis = FakeRedis
    monkeypatch.setitem(sys.modules, "redis", fake_redis)

    settings = Settings(ragrig_task_backend="arq")
    async with make_client(lambda: None, settings) as client:
        response = await client.get("/health")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "unhealthy"
    assert payload["detail"] == "redis unavailable"
    assert payload["redis"] == {
        "status": "error",
        "backend": "arq",
        "detail": "redis unavailable",
    }
