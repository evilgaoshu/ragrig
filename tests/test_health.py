from collections.abc import Callable

import httpx
import pytest

from ragrig.main import create_app

pytestmark = pytest.mark.smoke

@pytest.fixture
def make_client() -> Callable[[Callable[[], None]], httpx.AsyncClient]:
    def _make_client(check_database: Callable[[], None]) -> httpx.AsyncClient:
        app = create_app(check_database=check_database)
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
        "version": "0.1.0",
    }
