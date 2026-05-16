from pathlib import Path

import pytest

from ragrig.config import Settings, get_settings

pytestmark = pytest.mark.unit


def test_settings_exposes_sqlalchemy_database_url_for_psycopg() -> None:
    settings = Settings(
        database_url="postgresql://ragrig:ragrig_dev@db:5432/ragrig",
    )

    assert (
        settings.sqlalchemy_database_url == "postgresql+psycopg://ragrig:ragrig_dev@db:5432/ragrig"
    )


def test_settings_preserve_psycopg_and_non_postgres_urls() -> None:
    postgres_settings = Settings(
        database_url="postgresql+psycopg://ragrig:ragrig_dev@db:5432/ragrig",
    )
    sqlite_settings = Settings(database_url="sqlite+pysqlite:///:memory:")

    assert postgres_settings.sqlalchemy_database_url == postgres_settings.database_url
    assert (
        postgres_settings.sqlalchemy_runtime_database_url == postgres_settings.runtime_database_url
    )
    assert sqlite_settings.sqlalchemy_database_url == sqlite_settings.database_url
    assert sqlite_settings.sqlalchemy_runtime_database_url == sqlite_settings.database_url


def test_runtime_database_url_supports_urls_without_password() -> None:
    settings = Settings(
        database_url="postgresql://ragrig@db:5432/ragrig",
        db_host_port=15433,
    )

    assert settings.runtime_database_url == "postgresql://ragrig@localhost:15433/ragrig"


def test_runtime_database_url_preserves_non_url_strings() -> None:
    settings = Settings(database_url="not-a-url")

    assert settings.runtime_database_url == "not-a-url"


def test_get_settings_is_cached(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("APP_NAME", "cached-ragrig")

    first = get_settings()
    second = get_settings()

    assert first is second
    assert second.app_name == "cached-ragrig"
    get_settings.cache_clear()


def test_settings_include_vector_backend_defaults() -> None:
    settings = Settings()

    assert settings.vector_backend == "pgvector"
    assert settings.qdrant_url == "http://localhost:6333"
    assert settings.qdrant_api_key is None


def test_settings_parses_fake_reranker_guard_env(monkeypatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("RAGRIG_ALLOW_FAKE_RERANKER", "true")

    settings = get_settings()

    assert settings.ragrig_allow_fake_reranker is True
    get_settings.cache_clear()


def test_env_example_documents_fake_reranker_guard() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")

    assert "RAGRIG_ALLOW_FAKE_RERANKER=false" in env_example
    assert "Production disables fake reranker fallback by default" in env_example
