from urllib.parse import urlsplit, urlunsplit

from pydantic import Field

from ragrig.settings.base import RagrigBaseSettings

DEFAULT_DATABASE_URL = "postgresql://ragrig:ragrig_dev@localhost:5432/ragrig"


class DatabaseSettings(RagrigBaseSettings):
    db_host_port: int = 5432
    db_runtime_host: str = "localhost"
    database_url: str = Field(
        default=DEFAULT_DATABASE_URL,
        description="PostgreSQL connection string for RAGRig.",
    )
    ragrig_db_pool_size: int = Field(
        default=10,
        description="SQLAlchemy PostgreSQL connection pool size.",
    )
    ragrig_db_max_overflow: int = Field(
        default=20,
        description="Maximum overflow connections above the PostgreSQL pool size.",
    )
    ragrig_db_pool_recycle: int = Field(
        default=1800,
        description="Seconds before PostgreSQL pooled connections are recycled.",
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


class VectorSettings(RagrigBaseSettings):
    vector_backend: str = Field(default="pgvector", description="Vector backend name.")
    qdrant_url: str = Field(
        default="http://localhost:6333",
        description="Qdrant base URL for the optional vector backend.",
    )
    qdrant_api_key: str | None = Field(default=None, description="Optional Qdrant API key.")
