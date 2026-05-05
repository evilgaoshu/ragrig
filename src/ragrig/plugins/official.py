from __future__ import annotations

from pydantic import Field

from ragrig.plugins import guards
from ragrig.plugins.manifest import PluginConfigModel, PluginManifest, SecretRequirement
from ragrig.plugins.sources.s3.config import S3SourceConfig
from ragrig.plugins.types import Capability, PluginStatus, PluginTier, PluginType


class FileshareSourceConfig(PluginConfigModel):
    root_path: str
    transport: str = Field(pattern=r"^(smb|nfs|webdav|sftp)$")


class GoogleWorkspaceSourceConfig(PluginConfigModel):
    drive_id: str
    service_account_json: str


class Microsoft365SourceConfig(PluginConfigModel):
    tenant_id: str
    client_id: str
    client_secret: str


class WikiSourceConfig(PluginConfigModel):
    base_url: str
    access_token: str


class DatabaseSourceConfig(PluginConfigModel):
    dsn: str


class ObjectStorageSinkConfig(PluginConfigModel):
    bucket: str
    access_key: str
    secret_key: str


class AnalyticsSinkConfig(PluginConfigModel):
    target: str


class AgentAccessSinkConfig(PluginConfigModel):
    endpoint_url: str
    api_key: str


class LocalRuntimeModelConfig(PluginConfigModel):
    endpoint_url: str


class BgeEmbeddingConfig(PluginConfigModel):
    model_name: str = "BAAI/bge-small-en-v1.5"


class BgeRerankerConfig(PluginConfigModel):
    model_name: str = "BAAI/bge-reranker-base"


class QdrantVectorConfig(PluginConfigModel):
    endpoint_url: str
    api_key: str | None = None


def _official_manifest(
    *,
    plugin_id: str,
    display_name: str,
    description: str,
    plugin_type: PluginType,
    family: str,
    capabilities: tuple[Capability, ...],
    docs_reference: str = "docs/specs/ragrig-plugin-system-spec.md",
    optional_dependencies: tuple[str, ...] = (),
    config_model: type[PluginConfigModel] | None = None,
    example_config: dict[str, str] | None = None,
    secret_requirements: tuple[SecretRequirement, ...] = (),
    status: PluginStatus = PluginStatus.UNAVAILABLE,
    unavailable_reason: str,
) -> PluginManifest:
    return PluginManifest(
        plugin_id=plugin_id,
        display_name=display_name,
        description=description,
        plugin_type=plugin_type,
        family=family,
        version="0.1.0",
        owner="ragrig-official",
        tier=PluginTier.OFFICIAL,
        status=status,
        capabilities=capabilities,
        docs_reference=docs_reference,
        config_model=config_model,
        example_config=example_config,
        secret_requirements=secret_requirements,
        optional_dependencies=optional_dependencies,
        unavailable_reason=unavailable_reason,
    )


def official_stub_manifests() -> list[PluginManifest]:
    s3_ready = guards.is_dependency_available("boto3")
    return [
        _official_manifest(
            plugin_id="vector.qdrant",
            display_name="Qdrant Vector Backend",
            description="Stub manifest for future Qdrant vector backend support.",
            plugin_type=PluginType.VECTOR,
            family="qdrant",
            capabilities=(
                Capability.READ,
                Capability.WRITE,
                Capability.VECTOR_READ,
                Capability.VECTOR_WRITE,
            ),
            optional_dependencies=("qdrant_client",),
            config_model=QdrantVectorConfig,
            example_config={
                "endpoint_url": "http://localhost:6333",
                "api_key": "env:QDRANT_API_KEY",
            },
            secret_requirements=(
                SecretRequirement(
                    name="QDRANT_API_KEY", description="Qdrant API key", required=False
                ),
            ),
            unavailable_reason="Runtime connector is not implemented in this contract-first phase.",
        ),
        _official_manifest(
            plugin_id="model.ollama",
            display_name="Ollama Local Model Provider",
            description="Optional local Ollama runtime adapter for chat, generate, and embeddings.",
            plugin_type=PluginType.MODEL,
            family="ollama",
            capabilities=(Capability.GENERATE_TEXT,),
            config_model=LocalRuntimeModelConfig,
            example_config={"endpoint_url": "http://localhost:11434"},
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.lm_studio",
            display_name="LM Studio Local Model Provider",
            description="Optional LM Studio OpenAI-compatible local model adapter.",
            plugin_type=PluginType.MODEL,
            family="lm_studio",
            capabilities=(Capability.GENERATE_TEXT,),
            config_model=LocalRuntimeModelConfig,
            example_config={"endpoint_url": "http://localhost:1234/v1"},
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.llama_cpp",
            display_name="llama.cpp Local Model Provider",
            description="OpenAI-compatible local adapter for llama.cpp server.",
            plugin_type=PluginType.MODEL,
            family="llama_cpp",
            capabilities=(Capability.GENERATE_TEXT,),
            config_model=LocalRuntimeModelConfig,
            example_config={"endpoint_url": "http://localhost:8080/v1"},
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.vllm",
            display_name="vLLM Local Model Provider",
            description="OpenAI-compatible local adapter for vLLM.",
            plugin_type=PluginType.MODEL,
            family="vllm",
            capabilities=(Capability.GENERATE_TEXT,),
            config_model=LocalRuntimeModelConfig,
            example_config={"endpoint_url": "http://localhost:8000/v1"},
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.xinference",
            display_name="Xinference Local Model Provider",
            description="OpenAI-compatible local adapter for Xinference.",
            plugin_type=PluginType.MODEL,
            family="xinference",
            capabilities=(Capability.GENERATE_TEXT,),
            config_model=LocalRuntimeModelConfig,
            example_config={"endpoint_url": "http://localhost:9997/v1"},
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.localai",
            display_name="LocalAI Model Provider",
            description="OpenAI-compatible local adapter for LocalAI.",
            plugin_type=PluginType.MODEL,
            family="localai",
            capabilities=(Capability.GENERATE_TEXT,),
            config_model=LocalRuntimeModelConfig,
            example_config={"endpoint_url": "http://localhost:8080/v1"},
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="embedding.bge",
            display_name="BGE Embedding",
            description="Optional local BGE embedding provider.",
            plugin_type=PluginType.EMBEDDING,
            family="bge",
            capabilities=(Capability.WRITE, Capability.EMBED_TEXT),
            optional_dependencies=("FlagEmbedding",),
            config_model=BgeEmbeddingConfig,
            example_config={"model_name": "BAAI/bge-small-en-v1.5"},
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="reranker.bge",
            display_name="BGE Reranker",
            description="Optional local BGE reranker provider.",
            plugin_type=PluginType.RERANKER,
            family="bge",
            capabilities=(Capability.RERANK,),
            optional_dependencies=("FlagEmbedding",),
            config_model=BgeRerankerConfig,
            example_config={"model_name": "BAAI/bge-reranker-base"},
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="source.s3",
            display_name="S3-Compatible Source",
            description="Reads S3-compatible object storage into the ingestion pipeline.",
            plugin_type=PluginType.SOURCE,
            family="s3",
            capabilities=(
                Capability.READ,
                Capability.INCREMENTAL_SYNC,
            ),
            docs_reference="docs/specs/ragrig-s3-source-plugin-spec.md",
            optional_dependencies=("boto3",),
            config_model=S3SourceConfig,
            example_config={
                "bucket": "docs",
                "prefix": "team-a",
                "endpoint_url": "http://localhost:9000",
                "region": "us-east-1",
                "use_path_style": True,
                "verify_tls": True,
                "access_key": "env:AWS_ACCESS_KEY_ID",
                "secret_key": "env:AWS_SECRET_ACCESS_KEY",
                "session_token": "env:AWS_SESSION_TOKEN",
                "include_patterns": ["*.md", "*.txt"],
                "exclude_patterns": [],
                "max_object_size_mb": 50,
                "page_size": 1000,
                "max_retries": 3,
                "connect_timeout_seconds": 10,
                "read_timeout_seconds": 30,
            },
            secret_requirements=(
                SecretRequirement(name="AWS_ACCESS_KEY_ID", description="S3 access key id"),
                SecretRequirement(name="AWS_SECRET_ACCESS_KEY", description="S3 secret access key"),
                SecretRequirement(
                    name="AWS_SESSION_TOKEN",
                    description="Optional session token for temporary credentials",
                    required=False,
                ),
            ),
            unavailable_reason="Install boto3 to enable the S3-compatible runtime connector.",
            status=PluginStatus.READY if s3_ready else PluginStatus.UNAVAILABLE,
        ),
        _official_manifest(
            plugin_id="sink.object_storage",
            display_name="Object Storage Sink",
            description="Stub manifest for writing outputs to object storage.",
            plugin_type=PluginType.SINK,
            family="object_storage",
            capabilities=(Capability.WRITE,),
            optional_dependencies=("boto3",),
            config_model=ObjectStorageSinkConfig,
            example_config={
                "bucket": "exports",
                "access_key": "env:AWS_ACCESS_KEY_ID",
                "secret_key": "env:AWS_SECRET_ACCESS_KEY",
            },
            secret_requirements=(
                SecretRequirement(
                    name="AWS_ACCESS_KEY_ID", description="Object storage access key id"
                ),
                SecretRequirement(
                    name="AWS_SECRET_ACCESS_KEY", description="Object storage secret access key"
                ),
            ),
            unavailable_reason="Remote sink execution is intentionally out of scope.",
        ),
        _official_manifest(
            plugin_id="source.fileshare",
            display_name="Fileshare Source",
            description="Stub manifest for SMB, NFS, WebDAV, and SFTP sources.",
            plugin_type=PluginType.SOURCE,
            family="fileshare",
            capabilities=(
                Capability.READ,
                Capability.INCREMENTAL_SYNC,
                Capability.PERMISSION_MAPPING,
            ),
            optional_dependencies=("smbprotocol",),
            config_model=FileshareSourceConfig,
            example_config={"root_path": "//server/share", "transport": "smb"},
            unavailable_reason=(
                "Enterprise fileshare connector logic is intentionally out of scope."
            ),
        ),
        _official_manifest(
            plugin_id="source.google_workspace",
            display_name="Google Workspace Source",
            description="Stub manifest for Drive, Docs, Sheets, and Slides sources.",
            plugin_type=PluginType.SOURCE,
            family="google_workspace",
            capabilities=(
                Capability.READ,
                Capability.INCREMENTAL_SYNC,
                Capability.PERMISSION_MAPPING,
            ),
            optional_dependencies=("googleapiclient",),
            config_model=GoogleWorkspaceSourceConfig,
            example_config={
                "drive_id": "shared-drive-id",
                "service_account_json": "env:GOOGLE_SERVICE_ACCOUNT_JSON",
            },
            secret_requirements=(
                SecretRequirement(
                    name="GOOGLE_SERVICE_ACCOUNT_JSON", description="Google service account JSON"
                ),
            ),
            unavailable_reason="Google Workspace connector logic is intentionally out of scope.",
        ),
        _official_manifest(
            plugin_id="source.microsoft_365",
            display_name="Microsoft 365 Source",
            description="Stub manifest for SharePoint and OneDrive sources.",
            plugin_type=PluginType.SOURCE,
            family="microsoft_365",
            capabilities=(
                Capability.READ,
                Capability.INCREMENTAL_SYNC,
                Capability.PERMISSION_MAPPING,
            ),
            optional_dependencies=("msgraph",),
            config_model=Microsoft365SourceConfig,
            example_config={
                "tenant_id": "tenant-id",
                "client_id": "client-id",
                "client_secret": "env:MICROSOFT_365_CLIENT_SECRET",
            },
            secret_requirements=(
                SecretRequirement(
                    name="MICROSOFT_365_CLIENT_SECRET", description="Microsoft 365 client secret"
                ),
            ),
            unavailable_reason="Microsoft 365 connector logic is intentionally out of scope.",
        ),
        _official_manifest(
            plugin_id="source.wiki",
            display_name="Wiki Source",
            description="Stub manifest for wiki ingestion.",
            plugin_type=PluginType.SOURCE,
            family="wiki",
            capabilities=(Capability.READ, Capability.INCREMENTAL_SYNC),
            config_model=WikiSourceConfig,
            example_config={
                "base_url": "https://wiki.example.com",
                "access_token": "env:WIKI_ACCESS_TOKEN",
            },
            secret_requirements=(
                SecretRequirement(name="WIKI_ACCESS_TOKEN", description="Wiki API token"),
            ),
            unavailable_reason="Wiki connector logic is intentionally out of scope.",
        ),
        _official_manifest(
            plugin_id="source.database",
            display_name="Database Source",
            description="Stub manifest for relational and document database ingestion.",
            plugin_type=PluginType.SOURCE,
            family="database",
            capabilities=(
                Capability.READ,
                Capability.INCREMENTAL_SYNC,
                Capability.DELETE_DETECTION,
            ),
            config_model=DatabaseSourceConfig,
            example_config={"dsn": "env:SOURCE_DATABASE_DSN"},
            secret_requirements=(
                SecretRequirement(
                    name="SOURCE_DATABASE_DSN", description="Database connection string"
                ),
            ),
            unavailable_reason="Database connector logic is intentionally out of scope.",
        ),
        _official_manifest(
            plugin_id="preview.office",
            display_name="Office Preview",
            description="Stub manifest for office preview integrations.",
            plugin_type=PluginType.PREVIEW,
            family="office",
            capabilities=(Capability.PREVIEW_READ,),
            unavailable_reason=(
                "Office preview integrations are not implemented in this contract-first phase."
            ),
        ),
        _official_manifest(
            plugin_id="source.collaboration",
            display_name="Collaboration Source",
            description="Stub manifest for collaboration-suite document sources.",
            plugin_type=PluginType.SOURCE,
            family="collaboration",
            capabilities=(
                Capability.READ,
                Capability.INCREMENTAL_SYNC,
                Capability.PERMISSION_MAPPING,
            ),
            unavailable_reason="Collaboration-suite connectors are intentionally out of scope.",
        ),
        _official_manifest(
            plugin_id="parser.advanced_documents",
            display_name="Advanced Document Parser",
            description="Stub manifest for PDF, DOCX, PPTX, XLSX, and layout-aware parsing.",
            plugin_type=PluginType.PARSER,
            family="advanced_documents",
            capabilities=(Capability.READ, Capability.PARSE_TEXT),
            optional_dependencies=("docling",),
            unavailable_reason=(
                "Advanced parsing SDKs stay optional and are not implemented in this phase."
            ),
        ),
        _official_manifest(
            plugin_id="ocr",
            display_name="OCR Plugin",
            description="Stub manifest for OCR support.",
            plugin_type=PluginType.OCR,
            family="ocr",
            capabilities=(Capability.READ, Capability.OCR_TEXT),
            optional_dependencies=("paddleocr",),
            unavailable_reason="OCR integrations are intentionally out of scope.",
        ),
        _official_manifest(
            plugin_id="sink.analytics",
            display_name="Analytics Sink",
            description="Stub manifest for analytics-oriented output sinks.",
            plugin_type=PluginType.SINK,
            family="analytics",
            capabilities=(Capability.WRITE,),
            config_model=AnalyticsSinkConfig,
            example_config={"target": "duckdb"},
            unavailable_reason="Analytics sink execution is intentionally out of scope.",
        ),
        _official_manifest(
            plugin_id="sink.agent_access",
            display_name="Agent Access Sink",
            description="Stub manifest for agent-oriented export adapters.",
            plugin_type=PluginType.SINK,
            family="agent_access",
            capabilities=(Capability.WRITE,),
            config_model=AgentAccessSinkConfig,
            example_config={
                "endpoint_url": "https://example.com/mcp",
                "api_key": "env:AGENT_ACCESS_API_KEY",
            },
            secret_requirements=(
                SecretRequirement(name="AGENT_ACCESS_API_KEY", description="Agent access API key"),
            ),
            unavailable_reason="Agent-access export adapters are intentionally out of scope.",
        ),
    ]
