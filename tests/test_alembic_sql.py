from subprocess import run


def test_alembic_upgrade_sql_renders_successfully() -> None:
    result = run(
        ["uv", "run", "alembic", "upgrade", "head", "--sql"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "CREATE EXTENSION IF NOT EXISTS vector" in result.stdout
    assert "CREATE TABLE knowledge_bases" in result.stdout


def test_alembic_downgrade_sql_renders_successfully() -> None:
    result = run(
        ["uv", "run", "alembic", "downgrade", "20260503_0001:base", "--sql"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "DROP TABLE pipeline_run_items" in result.stdout
    assert "DROP TABLE knowledge_bases" in result.stdout
