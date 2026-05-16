from __future__ import annotations

import re
from typing import Any

from pydantic import Field, field_validator, model_validator

from ragrig.plugins.manifest import PluginConfigModel

SUPPORTED_DATABASE_ENGINES = ("postgresql", "mysql")

_QUERY_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_MUTATING_SQL_PATTERN = re.compile(
    r"\b("
    r"alter|call|copy|create|delete|drop|execute|grant|insert|merge|replace|"
    r"revoke|truncate|update|vacuum"
    r")\b",
    re.IGNORECASE,
)


class DatabaseQueryConfig(PluginConfigModel):
    name: str
    sql: str
    params: dict[str, Any] = Field(default_factory=dict)
    document_id_columns: list[str] = Field(default_factory=list)
    title_column: str | None = None
    text_columns: list[str] = Field(default_factory=list)
    metadata_columns: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not _QUERY_NAME_PATTERN.match(cleaned):
            raise ValueError(
                "query name must start with a letter and use letters, numbers, _, -, or ."
            )
        return cleaned

    @field_validator("sql")
    @classmethod
    def validate_sql(cls, value: str) -> str:
        sql = value.strip()
        if not sql:
            raise ValueError("sql must not be empty")
        sql_without_trailing_semicolon = sql[:-1].strip() if sql.endswith(";") else sql
        if ";" in sql_without_trailing_semicolon:
            raise ValueError("sql must contain a single read-only statement")
        lowered = sql_without_trailing_semicolon.lstrip("(\ufeff \t\r\n").lower()
        if not (lowered.startswith("select") or lowered.startswith("with")):
            raise ValueError("sql must be a read-only SELECT or WITH query")
        if _MUTATING_SQL_PATTERN.search(sql_without_trailing_semicolon):
            raise ValueError("sql must not contain mutating database keywords")
        return sql_without_trailing_semicolon

    @field_validator("document_id_columns", "text_columns", "metadata_columns")
    @classmethod
    def validate_column_list(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("column lists must not contain duplicates")
        return cleaned

    @field_validator("title_column")
    @classmethod
    def validate_optional_column(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class DatabaseSourceConfig(PluginConfigModel):
    engine: str = Field(pattern=r"^(postgresql|mysql)$")
    dsn: str
    source_name: str = "database-source"
    queries: list[DatabaseQueryConfig] = Field(min_length=1)
    max_rows_per_query: int = Field(default=1000, gt=0, le=10000)
    connect_timeout_seconds: int = Field(default=10, gt=0, le=120)
    query_timeout_seconds: int = Field(default=30, gt=0, le=600)
    known_document_uris: list[str] = Field(default_factory=list)

    @field_validator("dsn")
    @classmethod
    def validate_dsn_reference(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned.startswith("env:"):
            raise ValueError("dsn must use an env:SOURCE_DATABASE_DSN reference")
        if not cleaned.removeprefix("env:"):
            raise ValueError("dsn env reference must include a variable name")
        return cleaned

    @field_validator("source_name")
    @classmethod
    def validate_source_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not _QUERY_NAME_PATTERN.match(cleaned):
            raise ValueError(
                "source_name must start with a letter and use letters, numbers, _, -, or ."
            )
        return cleaned

    @field_validator("known_document_uris")
    @classmethod
    def validate_known_document_uris(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if any(not item.startswith("database://") for item in cleaned):
            raise ValueError("known_document_uris must use database:// URIs")
        return cleaned

    @model_validator(mode="after")
    def validate_unique_query_names(self) -> "DatabaseSourceConfig":
        names = [query.name for query in self.queries]
        if len(set(names)) != len(names):
            raise ValueError("query names must be unique")
        return self
