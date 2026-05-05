from __future__ import annotations

from pydantic import Field, field_validator

from ragrig.plugins.manifest import PluginConfigModel


class S3CompatibleStorageConfig(PluginConfigModel):
    bucket: str = Field(min_length=1)
    prefix: str = ""
    endpoint_url: str | None = None
    region: str | None = None
    use_path_style: bool = False
    verify_tls: bool = True
    access_key: str
    secret_key: str
    session_token: str | None = None
    max_retries: int = Field(default=3, ge=0)
    connect_timeout_seconds: int = Field(default=10, gt=0)
    read_timeout_seconds: int = Field(default=30, gt=0)

    @field_validator("bucket")
    @classmethod
    def validate_bucket(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("bucket must not be empty")
        if "/" in cleaned:
            raise ValueError("bucket must not contain '/' characters")
        return cleaned

    @field_validator("prefix")
    @classmethod
    def normalize_prefix(cls, value: str) -> str:
        return value.strip().strip("/")


class ObjectStorageSinkConfig(S3CompatibleStorageConfig):
    path_template: str = "{knowledge_base}/{run_id}/{artifact}.{format}"
    overwrite: bool = False
    dry_run: bool = False
    include_retrieval_artifact: bool = True
    include_markdown_summary: bool = True
    object_metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("path_template")
    @classmethod
    def validate_path_template(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("path_template must not be empty")
        if cleaned.startswith("/"):
            raise ValueError("path_template must be relative")
        required_tokens = {"{knowledge_base}", "{artifact}", "{format}"}
        if any(token not in cleaned for token in required_tokens):
            raise ValueError(
                "path_template must include {knowledge_base}, {artifact}, and {format}"
            )
        return cleaned

    @field_validator("object_metadata")
    @classmethod
    def validate_object_metadata(cls, value: dict[str, str]) -> dict[str, str]:
        return {
            str(key).strip(): str(item).strip() for key, item in value.items() if str(key).strip()
        }
