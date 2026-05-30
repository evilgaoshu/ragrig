from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_uses_multistage_build_and_non_root_runtime() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    meaningful_lines = [
        line.strip()
        for line in dockerfile.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    from_lines = [line for line in meaningful_lines if line.startswith("FROM ")]

    assert from_lines[0] == "FROM node:22-alpine AS frontend"
    assert from_lines[-1] == "FROM python:3.11-slim"
    assert len(from_lines) >= 2
    assert "COPY --from=frontend /frontend/dist ./src/ragrig/static/dist" in meaningful_lines
    assert any("groupadd --gid 10001 ragrig" in line for line in meaningful_lines)
    assert any("useradd --uid 10001 --gid ragrig" in line for line in meaningful_lines)
    assert "USER ragrig" in meaningful_lines
    assert meaningful_lines.index("USER ragrig") < meaningful_lines.index(
        'ENTRYPOINT ["sh", "/app/scripts/docker-entrypoint.sh"]'
    )
