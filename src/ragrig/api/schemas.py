from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EvaluationRunRequest(BaseModel):
    golden_path: str
    knowledge_base: str = "fixture-local"
    top_k: int = Field(default=5, ge=1, le=50)
    provider: str | None = None
    model: str | None = None
    dimensions: int | None = Field(default=None, gt=0)
    baseline_path: str | None = None
    mode: str = Field(
        default="dense",
        pattern=(
            r"^(dense|hybrid|rerank|hybrid_rerank|graph|hybrid_graph|"
            r"graph_rerank|hybrid_graph_rerank)$"
        ),
    )
    lexical_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    vector_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    candidate_k: int = Field(default=20, ge=1, le=200)
    reranker_provider: str | None = None
    reranker_model: str | None = None
    graph_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    graph_depth: int = Field(default=1, ge=0, le=2)


class RetrievalSearchRequest(BaseModel):
    knowledge_base: str
    query: str
    top_k: int = Field(default=5, ge=1, le=50)
    role: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    provider: str | None = None
    model: str | None = None
    dimensions: int | None = Field(default=None, gt=0)
    principal_ids: list[str] | None = None
    enforce_acl: bool = True
    mode: str = Field(
        default="dense",
        pattern=(
            r"^(dense|hybrid|rerank|hybrid_rerank|graph|hybrid_graph|"
            r"graph_rerank|hybrid_graph_rerank)$"
        ),
    )
    lexical_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    vector_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    candidate_k: int = Field(default=20, ge=1, le=200)
    reranker_provider: str | None = None
    reranker_model: str | None = None
    graph_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    graph_depth: int = Field(default=1, ge=0, le=2)


class AnswerRequest(BaseModel):
    knowledge_base: str
    query: str
    top_k: int = Field(default=5, ge=1, le=50)
    role: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    role_model_config: dict[str, Any] | None = None
    provider: str = "deterministic-local"
    model: str | None = None
    config: dict[str, Any] | None = None
    answer_provider: str | None = None
    answer_model: str | None = None
    answer_config: dict[str, Any] | None = None
    dimensions: int | None = Field(default=None, gt=0)
    principal_ids: list[str] | None = None
    enforce_acl: bool = True
    stream: bool = False
    mode: str = Field(
        default="dense",
        pattern=(
            r"^(dense|hybrid|rerank|hybrid_rerank|graph|hybrid_graph|"
            r"graph_rerank|hybrid_graph_rerank)$"
        ),
    )
    lexical_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    vector_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    candidate_k: int = Field(default=20, ge=1, le=200)
    reranker_provider: str | None = None
    reranker_model: str | None = None
    reranker_config: dict[str, Any] | None = None
    judge_provider: str | None = None
    judge_model: str | None = None
    judge_config: dict[str, Any] | None = None
    judge_enabled: bool | None = None
    graph_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    graph_depth: int = Field(default=1, ge=0, le=2)


class PermissionPreviewRequest(BaseModel):
    principal_ids: list[str] | None = None


class AgentAccessExportRequest(BaseModel):
    endpoint_url: str
    api_key: str
    hmac_secret: str | None = None
    batch_size: int = 100
    timeout_seconds: float = 30.0
    verify_tls: bool = True
    dry_run: bool = False


class WebhookExportRequest(BaseModel):
    endpoint_url: str
    hmac_secret: str | None = None
    format: str = "ndjson"
    extra_headers: dict[str, str] | None = None
    batch_size: int = 200
    timeout_seconds: float = 30.0
    verify_tls: bool = True
    dry_run: bool = False


class ObjectStorageExportRequest(BaseModel):
    bucket: str
    endpoint_url: str | None = None
    access_key: str | None = None
    secret_key: str | None = None
    region: str | None = None
    use_path_style: bool = False
    verify_tls: bool = True
    path_template: str = "{knowledge_base}/{run_id}/{artifact}.{format}"
    overwrite: bool = True
    dry_run: bool = False
    include_retrieval_artifact: bool = True
    include_markdown_summary: bool = True
    parquet_export: bool = False


class CloudflareR2ExportRequest(BaseModel):
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    prefix: str = ""
    jurisdiction: str | None = None
    path_template: str = "{knowledge_base}/{run_id}/{artifact}.{format}"
    overwrite: bool = True
    dry_run: bool = False
    include_retrieval_artifact: bool = True
    include_markdown_summary: bool = True
    parquet_export: bool = False


class BackblazeB2ExportRequest(BaseModel):
    region: str
    key_id: str
    application_key: str
    bucket: str
    prefix: str = ""
    path_template: str = "{knowledge_base}/{run_id}/{artifact}.{format}"
    overwrite: bool = True
    dry_run: bool = False
    include_retrieval_artifact: bool = True
    include_markdown_summary: bool = True
    parquet_export: bool = False


class AzureBlobExportRequest(BaseModel):
    account_name: str
    account_key: str
    container: str
    prefix: str = ""
    path_template: str = "{knowledge_base}/{run_id}/{artifact}.{format}"
    overwrite: bool = True
    dry_run: bool = False
    include_retrieval_artifact: bool = True
    include_markdown_summary: bool = True
    parquet_export: bool = False


class GcsExportRequest(BaseModel):
    access_key: str
    secret_key: str
    bucket: str
    prefix: str = ""
    path_template: str = "{knowledge_base}/{run_id}/{artifact}.{format}"
    overwrite: bool = True
    dry_run: bool = False
    include_retrieval_artifact: bool = True
    include_markdown_summary: bool = True
    parquet_export: bool = False
