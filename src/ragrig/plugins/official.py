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


class CloudModelConfig(PluginConfigModel):
    api_base_url: str
    model_name: str


class CloudEmbeddingModelConfig(PluginConfigModel):
    api_base_url: str
    model_name: str
    embedding_model_name: str


class CloudRerankModelConfig(PluginConfigModel):
    api_base_url: str
    embedding_model_name: str
    reranker_model_name: str


class VertexAiCloudModelConfig(PluginConfigModel):
    project: str
    location: str = "us-central1"
    model_name: str = "gemini-2.5-pro"
    embedding_model_name: str = "text-embedding-005"


class BedrockCloudModelConfig(PluginConfigModel):
    region: str = "us-east-1"
    model_name: str = "anthropic.claude-3-7-sonnet-20250219-v1:0"
    embedding_model_name: str = "amazon.titan-embed-text-v2:0"
    reranker_model_name: str = "cohere.rerank-v3-5:0"


class AzureOpenAiCloudModelConfig(PluginConfigModel):
    api_base_url: str = "https://example-resource.openai.azure.com/openai/deployments"
    deployment_name: str = "gpt-4.1"
    embedding_deployment_name: str = "text-embedding-3-large"
    api_version: str = "2025-01-01-preview"


class CloudGenerateEmbeddingRerankModelConfig(PluginConfigModel):
    api_base_url: str
    model_name: str
    embedding_model_name: str
    reranker_model_name: str


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
            plugin_id="model.vertex_ai",
            display_name="Google Vertex AI Cloud Provider",
            description=(
                "Contract-only cloud stub for Vertex AI chat, generate, and embedding workflows."
            ),
            plugin_type=PluginType.MODEL,
            family="vertex_ai",
            capabilities=(Capability.GENERATE_TEXT, Capability.EMBED_TEXT),
            docs_reference="docs/specs/ragrig-phase-1e-local-model-provider-plugin-spec.md",
            optional_dependencies=("google-cloud-aiplatform",),
            config_model=VertexAiCloudModelConfig,
            example_config={
                "project": "demo-project",
                "location": "us-central1",
                "model_name": "gemini-2.5-pro",
                "embedding_model_name": "text-embedding-005",
            },
            secret_requirements=(
                SecretRequirement(name="VERTEX_AI_PROJECT", description="Google Cloud project id"),
                SecretRequirement(name="VERTEX_AI_LOCATION", description="Vertex AI region"),
                SecretRequirement(
                    name="GOOGLE_APPLICATION_CREDENTIALS",
                    description="Path to service account credentials",
                ),
            ),
            unavailable_reason="Cloud provider remains a contract-only stub in PR-3.",
        ),
        _official_manifest(
            plugin_id="model.bedrock",
            display_name="Amazon Bedrock Cloud Provider",
            description=(
                "Contract-only cloud stub for Bedrock generation, embedding, and rerank workflows."
            ),
            plugin_type=PluginType.MODEL,
            family="bedrock",
            capabilities=(Capability.GENERATE_TEXT, Capability.EMBED_TEXT, Capability.RERANK),
            docs_reference="docs/specs/ragrig-phase-1e-local-model-provider-plugin-spec.md",
            optional_dependencies=("boto3",),
            config_model=BedrockCloudModelConfig,
            example_config={
                "region": "us-east-1",
                "model_name": "anthropic.claude-3-7-sonnet-20250219-v1:0",
                "embedding_model_name": "amazon.titan-embed-text-v2:0",
                "reranker_model_name": "cohere.rerank-v3-5:0",
            },
            secret_requirements=(
                SecretRequirement(name="AWS_ACCESS_KEY_ID", description="AWS access key id"),
                SecretRequirement(
                    name="AWS_SECRET_ACCESS_KEY", description="AWS secret access key"
                ),
                SecretRequirement(name="AWS_REGION", description="AWS region for Bedrock"),
            ),
            unavailable_reason="Cloud provider remains a contract-only stub in PR-3.",
        ),
        _official_manifest(
            plugin_id="model.azure_openai",
            display_name="Azure OpenAI Cloud Provider",
            description=(
                "Contract-only cloud stub for Azure OpenAI generation and embedding workflows."
            ),
            plugin_type=PluginType.MODEL,
            family="azure_openai",
            capabilities=(Capability.GENERATE_TEXT, Capability.EMBED_TEXT),
            docs_reference="docs/specs/ragrig-phase-1e-local-model-provider-plugin-spec.md",
            optional_dependencies=("openai",),
            config_model=AzureOpenAiCloudModelConfig,
            example_config={
                "api_base_url": "https://example-resource.openai.azure.com/openai/deployments",
                "deployment_name": "gpt-4.1",
                "embedding_deployment_name": "text-embedding-3-large",
                "api_version": "2025-01-01-preview",
            },
            secret_requirements=(
                SecretRequirement(name="AZURE_OPENAI_API_KEY", description="Azure OpenAI API key"),
                SecretRequirement(
                    name="AZURE_OPENAI_ENDPOINT", description="Azure OpenAI endpoint base URL"
                ),
            ),
            unavailable_reason="Cloud provider remains a contract-only stub in PR-3.",
        ),
        _official_manifest(
            plugin_id="model.openrouter",
            display_name="OpenRouter Cloud Provider",
            description=(
                "Contract-only cloud stub for OpenRouter text generation over an "
                "OpenAI-compatible API."
            ),
            plugin_type=PluginType.MODEL,
            family="openrouter",
            capabilities=(Capability.GENERATE_TEXT,),
            docs_reference="docs/specs/ragrig-phase-1e-local-model-provider-plugin-spec.md",
            optional_dependencies=("openai",),
            config_model=CloudModelConfig,
            example_config={
                "api_base_url": "https://openrouter.ai/api/v1",
                "model_name": "openai/gpt-4.1-mini",
            },
            secret_requirements=(
                SecretRequirement(name="OPENROUTER_API_KEY", description="OpenRouter API key"),
            ),
            unavailable_reason="Cloud provider remains a contract-only stub in PR-3.",
        ),
        _official_manifest(
            plugin_id="model.openai",
            display_name="OpenAI Cloud Provider",
            description="Contract-only cloud stub for OpenAI generation and embedding workflows.",
            plugin_type=PluginType.MODEL,
            family="openai",
            capabilities=(Capability.GENERATE_TEXT, Capability.EMBED_TEXT),
            docs_reference="docs/specs/ragrig-phase-1e-local-model-provider-plugin-spec.md",
            optional_dependencies=("openai",),
            config_model=CloudEmbeddingModelConfig,
            example_config={
                "api_base_url": "https://api.openai.com/v1",
                "model_name": "gpt-4.1-mini",
                "embedding_model_name": "text-embedding-3-large",
            },
            secret_requirements=(
                SecretRequirement(name="OPENAI_API_KEY", description="OpenAI API key"),
            ),
            unavailable_reason="Cloud provider remains a contract-only stub in PR-3.",
        ),
        _official_manifest(
            plugin_id="model.cohere",
            display_name="Cohere Cloud Provider",
            description=(
                "Contract-only cloud stub for Cohere generation, embedding, and rerank workflows."
            ),
            plugin_type=PluginType.MODEL,
            family="cohere",
            capabilities=(Capability.GENERATE_TEXT, Capability.EMBED_TEXT, Capability.RERANK),
            docs_reference="docs/specs/ragrig-phase-1e-local-model-provider-plugin-spec.md",
            optional_dependencies=("cohere",),
            config_model=CloudGenerateEmbeddingRerankModelConfig,
            example_config={
                "api_base_url": "https://api.cohere.com/v2",
                "model_name": "command-r-plus",
                "embedding_model_name": "embed-v4.0",
                "reranker_model_name": "rerank-v3.5",
            },
            secret_requirements=(
                SecretRequirement(name="COHERE_API_KEY", description="Cohere API key"),
            ),
            unavailable_reason="Cloud provider remains a contract-only stub in PR-3.",
        ),
        _official_manifest(
            plugin_id="model.voyage",
            display_name="Voyage AI Cloud Provider",
            description="Contract-only cloud stub for Voyage embedding and rerank workflows.",
            plugin_type=PluginType.MODEL,
            family="voyage",
            capabilities=(Capability.EMBED_TEXT, Capability.RERANK),
            docs_reference="docs/specs/ragrig-phase-1e-local-model-provider-plugin-spec.md",
            optional_dependencies=("voyageai",),
            config_model=CloudRerankModelConfig,
            example_config={
                "api_base_url": "https://api.voyageai.com/v1",
                "embedding_model_name": "voyage-3-large",
                "reranker_model_name": "rerank-2.5",
            },
            secret_requirements=(
                SecretRequirement(name="VOYAGE_API_KEY", description="Voyage AI API key"),
            ),
            unavailable_reason="Cloud provider remains a contract-only stub in PR-3.",
        ),
        _official_manifest(
            plugin_id="model.jina",
            display_name="Jina AI Cloud Provider",
            description="Contract-only cloud stub for Jina embedding and rerank workflows.",
            plugin_type=PluginType.MODEL,
            family="jina",
            capabilities=(Capability.EMBED_TEXT, Capability.RERANK),
            docs_reference="docs/specs/ragrig-phase-1e-local-model-provider-plugin-spec.md",
            config_model=CloudRerankModelConfig,
            example_config={
                "api_base_url": "https://api.jina.ai/v1",
                "embedding_model_name": "jina-embeddings-v4",
                "reranker_model_name": "jina-reranker-m0",
            },
            secret_requirements=(
                SecretRequirement(name="JINA_API_KEY", description="Jina AI API key"),
            ),
            unavailable_reason="Cloud provider remains a contract-only stub in PR-3.",
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
