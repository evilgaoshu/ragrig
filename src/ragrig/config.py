from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ragrig"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    db_host_port: int = 5432
    db_runtime_host: str = "localhost"
    database_url: str = Field(
        default="postgresql://ragrig:ragrig_dev@localhost:5432/ragrig",
        description="PostgreSQL connection string for RAGRig.",
    )
    vector_backend: str = Field(default="pgvector", description="Vector backend name.")
    qdrant_url: str = Field(
        default="http://localhost:6333",
        description="Qdrant base URL for the optional vector backend.",
    )
    qdrant_api_key: str | None = Field(default=None, description="Optional Qdrant API key.")
    ragrig_allow_fake_reranker: bool = Field(
        default=False,
        description=(
            "Allow the deterministic fake reranker fallback in production. "
            "Use only for demos or explicitly accepted degraded environments."
        ),
    )

    @property
    def runtime_database_url(self) -> str:
        if "://" not in self.database_url or not self.database_url.startswith("postgresql"):
            return self.database_url
        parts = urlsplit(self.database_url)
        username = parts.username or ""
        password = parts.password or ""
        auth = username
        if password:
            auth = f"{auth}:{password}"
        if auth:
            auth = f"{auth}@"
        return urlunsplit(
            (
                parts.scheme,
                f"{auth}{self.db_runtime_host}:{self.db_host_port}",
                parts.path,
                parts.query,
                parts.fragment,
            )
        )

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url.startswith("postgresql+psycopg://"):
            return self.database_url
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        return self.database_url

    @property
    def sqlalchemy_runtime_database_url(self) -> str:
        if self.runtime_database_url.startswith("postgresql+psycopg://"):
            return self.runtime_database_url
        if self.runtime_database_url.startswith("postgresql://"):
            return self.runtime_database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        return self.runtime_database_url

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
