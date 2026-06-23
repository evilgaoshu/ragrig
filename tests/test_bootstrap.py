from __future__ import annotations

from pathlib import Path

import pytest

from scripts.bootstrap import bootstrap_env, render_result

pytestmark = pytest.mark.unit


def test_bootstrap_env_writes_env_with_generated_password(tmp_path: Path) -> None:
    template = tmp_path / ".env.example"
    template.write_text(
        "RAGRIG_POSTGRES_PASSWORD=replace-with-a-strong-postgres-password\n"
        "RAGRIG_AUTH_ENABLED=false\n",
        encoding="utf-8",
    )

    result = bootstrap_env(
        project_root=tmp_path,
        template_path=template,
        password="local-secret-fixture",
    )

    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert result.status == "created"
    assert "RAGRIG_POSTGRES_PASSWORD=local-secret-fixture" in env_text
    assert "RAGRIG_AUTH_ENABLED=false" in env_text
    assert "local-secret-fixture" not in render_result(result)
    assert "docker compose up" in render_result(result)


def test_bootstrap_env_does_not_overwrite_existing_env_without_force(tmp_path: Path) -> None:
    template = tmp_path / ".env.example"
    template.write_text("RAGRIG_POSTGRES_PASSWORD=placeholder\n", encoding="utf-8")
    env_path = tmp_path / ".env"
    env_path.write_text("RAGRIG_POSTGRES_PASSWORD=keep-me\n", encoding="utf-8")

    result = bootstrap_env(
        project_root=tmp_path,
        template_path=template,
        password="new-secret",
    )

    assert result.status == "exists"
    assert env_path.read_text(encoding="utf-8") == "RAGRIG_POSTGRES_PASSWORD=keep-me\n"


def test_bootstrap_env_force_regenerates_existing_env(tmp_path: Path) -> None:
    template = tmp_path / ".env.example"
    template.write_text("RAGRIG_POSTGRES_PASSWORD=placeholder\n", encoding="utf-8")
    env_path = tmp_path / ".env"
    env_path.write_text("RAGRIG_POSTGRES_PASSWORD=old\n", encoding="utf-8")

    result = bootstrap_env(
        project_root=tmp_path,
        template_path=template,
        password="new-secret",
        force=True,
    )

    assert result.status == "regenerated"
    assert env_path.read_text(encoding="utf-8") == "RAGRIG_POSTGRES_PASSWORD=new-secret\n"


def test_bootstrap_env_requires_template(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="template not found"):
        bootstrap_env(project_root=tmp_path)


def test_makefile_exposes_init_and_plain_python_doctor() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "PYTHON ?= python3" in makefile
    assert "init:" in makefile
    assert "$(PYTHON) -m scripts.bootstrap" in makefile
    assert "$(PYTHON) -m scripts.doctor" in makefile
