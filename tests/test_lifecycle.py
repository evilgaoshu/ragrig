from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from ragrig.config import Settings

pytestmark = pytest.mark.unit


def test_main_module_keeps_app_creation_lazy() -> None:
    from pathlib import Path

    source = Path("src/ragrig/main.py").read_text(encoding="utf-8")

    assert "app = create_app()" not in source
    assert "create_app(" in source


@pytest.mark.anyio
async def test_lifespan_disposes_default_engine_and_flushes_otel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ragrig.otel as otel
    from ragrig import main

    engine = create_engine("sqlite+pysqlite:///:memory:")
    calls: list[str] = []

    original_dispose = engine.dispose

    def dispose() -> None:
        calls.append("engine.dispose")
        original_dispose()

    class TaskExecutor:
        def shutdown(self, wait: bool = True) -> None:
            calls.append(f"task.shutdown:{wait}")

    def setup_otel(_app, _settings):
        def shutdown() -> None:
            calls.append("otel.shutdown")

        return shutdown

    monkeypatch.setattr(engine, "dispose", dispose)
    monkeypatch.setattr(main, "create_db_engine", lambda _settings: engine)
    monkeypatch.setattr(otel, "setup_otel", setup_otel)

    app = main.create_app(
        check_database=lambda: None,
        settings=Settings(database_url="sqlite+pysqlite:///:memory:"),
        task_executor=TaskExecutor(),
    )

    async with app.router.lifespan_context(app):
        pass

    assert calls == ["task.shutdown:True", "engine.dispose", "otel.shutdown"]
