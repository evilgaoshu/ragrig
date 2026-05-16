from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, ResourceClosedError, SQLAlchemyError

from ragrig.plugins.sources.database.config import DatabaseQueryConfig
from ragrig.plugins.sources.database.errors import DatabaseConfigError, DatabaseQueryError


@dataclass(frozen=True)
class DatabaseQueryResult:
    query_name: str
    rows: list[Mapping[str, Any]]
    truncated: bool = False

    @property
    def row_count(self) -> int:
        return len(self.rows)


class DatabaseClientProtocol(Protocol):
    def fetch_query(
        self,
        query: DatabaseQueryConfig,
        *,
        max_rows: int,
    ) -> DatabaseQueryResult: ...

    def close(self) -> None: ...


class SQLAlchemyDatabaseClient:
    def __init__(
        self,
        *,
        dsn: str,
        engine: str,
        connect_timeout_seconds: int,
        query_timeout_seconds: int,
    ) -> None:
        self.engine_name = engine
        self.query_timeout_seconds = query_timeout_seconds
        try:
            self._engine = create_engine(
                dsn,
                future=True,
                pool_pre_ping=True,
                connect_args=_connect_args(
                    engine=engine,
                    connect_timeout_seconds=connect_timeout_seconds,
                    query_timeout_seconds=query_timeout_seconds,
                ),
            )
        except ModuleNotFoundError as exc:
            raise DatabaseConfigError(
                f"database driver is not installed for engine {engine!r}: {exc.name}"
            ) from exc

    def fetch_query(
        self,
        query: DatabaseQueryConfig,
        *,
        max_rows: int,
    ) -> DatabaseQueryResult:
        try:
            with self._engine.connect() as connection:
                result = connection.execute(text(query.sql), query.params)
                try:
                    rows = [dict(row) for row in result.mappings().fetchmany(max_rows + 1)]
                except ResourceClosedError as exc:
                    raise DatabaseConfigError(
                        f"query {query.name!r} did not return a row set"
                    ) from exc
                finally:
                    result.close()
        except DatabaseConfigError:
            raise
        except (DBAPIError, SQLAlchemyError, ModuleNotFoundError) as exc:
            raise DatabaseQueryError(f"query {query.name!r} failed: {exc}") from exc

        truncated = len(rows) > max_rows
        return DatabaseQueryResult(
            query_name=query.name,
            rows=rows[:max_rows],
            truncated=truncated,
        )

    def close(self) -> None:
        self._engine.dispose()


class FakeDatabaseClient:
    def __init__(self, results: Mapping[str, list[Mapping[str, Any]]]) -> None:
        self.results = {name: [dict(row) for row in rows] for name, rows in results.items()}
        self.queries: list[str] = []

    def fetch_query(
        self,
        query: DatabaseQueryConfig,
        *,
        max_rows: int,
    ) -> DatabaseQueryResult:
        self.queries.append(query.name)
        rows = self.results.get(query.name, [])
        truncated = len(rows) > max_rows
        return DatabaseQueryResult(
            query_name=query.name,
            rows=rows[:max_rows],
            truncated=truncated,
        )

    def close(self) -> None:
        return None


def build_sqlalchemy_database_client(
    *,
    dsn: str,
    engine: str,
    connect_timeout_seconds: int,
    query_timeout_seconds: int,
) -> SQLAlchemyDatabaseClient:
    return SQLAlchemyDatabaseClient(
        dsn=dsn,
        engine=engine,
        connect_timeout_seconds=connect_timeout_seconds,
        query_timeout_seconds=query_timeout_seconds,
    )


def _connect_args(
    *,
    engine: str,
    connect_timeout_seconds: int,
    query_timeout_seconds: int,
) -> dict[str, object]:
    if engine == "postgresql":
        return {"connect_timeout": connect_timeout_seconds}
    if engine == "mysql":
        return {
            "connect_timeout": connect_timeout_seconds,
            "read_timeout": query_timeout_seconds,
            "write_timeout": query_timeout_seconds,
        }
    raise DatabaseConfigError(f"unsupported database engine: {engine}")
