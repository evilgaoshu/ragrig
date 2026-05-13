import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ragrig.db.models import Base
from ragrig.main import create_app
from ragrig.web_console import get_ops_diagnostics

pytestmark = [pytest.mark.smoke, pytest.mark.slow]


def _create_sqlite_session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    def _factory() -> Session:
        return Session(engine, expire_on_commit=False)

    return _factory


def test_ops_diagnostics_console_route_returns_json(tmp_path) -> None:
    import httpx

    session_factory = _create_sqlite_session_factory()
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async def _test():
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get("/ops/diagnostics")
        assert response.status_code == 200
        data = response.json()
        assert "overall_status" in data
        assert "summaries" in data
        for key in [
            "ops-deploy-summary",
            "ops-backup-summary",
            "ops-restore-summary",
            "ops-upgrade-summary",
        ]:
            assert key in data["summaries"]

    import anyio

    anyio.run(_test)


def test_ops_diagnostics_returns_degraded_without_artifacts() -> None:
    result = get_ops_diagnostics()
    assert result["overall_status"] in ("success", "degraded")
    assert "summaries" in result

    for key in [
        "ops-deploy-summary",
        "ops-backup-summary",
        "ops-restore-summary",
        "ops-upgrade-summary",
    ]:
        s = result["summaries"].get(key, {})
        if not s.get("available"):
            assert s.get("status") == "failure"
            assert "artifact not found or corrupt" in (s.get("reason") or "")


def test_ops_diagnostics_with_stub_artifacts(tmp_path, monkeypatch) -> None:
    from ragrig import web_console as wc

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True)

    for name in [
        "ops-deploy-summary",
        "ops-backup-summary",
        "ops-restore-summary",
        "ops-upgrade-summary",
    ]:
        artifact = {
            "artifact": name,
            "version": "1.0.0",
            "generated_at": "2026-05-13T00:00:00Z",
            "snapshot_id": "test",
            "schema_revision": "abc123",
            "operation_status": "success",
            "verification_checks": [],
            "report_path": str(artifacts_dir / f"{name}.json"),
        }
        (artifacts_dir / f"{name}.json").write_text(json.dumps(artifact), encoding="utf-8")

    monkeypatch.setattr(wc, "_OPS_ARTIFACTS_DIR", artifacts_dir)

    result = get_ops_diagnostics()
    assert result["overall_status"] == "success"

    for key in [
        "ops-deploy-summary",
        "ops-backup-summary",
        "ops-restore-summary",
        "ops-upgrade-summary",
    ]:
        s = result["summaries"][key]
        assert s["available"] is True
        assert s["status"] == "success"
