from __future__ import annotations

from pydantic import Field

from ragrig.plugins import guards
from ragrig.plugins.manifest import PluginConfigModel, PluginManifest, SecretRequirement
from ragrig.plugins.object_storage.config import ObjectStorageSinkConfig
from ragrig.plugins.sources.backblaze_b2.config import BackblazeB2SourceConfig
from ragrig.plugins.sources.cloudflare_r2.config import CloudflareR2SourceConfig
from ragrig.plugins.sources.database.config import DatabaseSourceConfig
from ragrig.plugins.sources.fileshare.config import FileshareSourceConfig
from ragrig.plugins.sources.google_workspace.config import GoogleWorkspaceSourceConfig
from ragrig.plugins.sources.s3.config import S3SourceConfig
from ragrig.plugins.types import Capability, PluginStatus, PluginTier, PluginType


class CloudflareR2SinkConfig(PluginConfigModel):
    account_id: str = Field(min_length=1)
    access_key_id: str
    secret_access_key: str
    bucket: str = Field(min_length=1)
    prefix: str = ""
    jurisdiction: str | None = None
    path_template: str = "{knowledge_base}/{run_id}/{artifact}.{format}"
    overwrite: bool = False
    dry_run: bool = False
    include_retrieval_artifact: bool = True
    include_markdown_summary: bool = True
    parquet_export: bool = False
    max_retries: int = Field(default=3, ge=0)
    connect_timeout_seconds: int = Field(default=10, gt=0)
    read_timeout_seconds: int = Field(default=30, gt=0)
    object_metadata: dict[str, str] = Field(default_factory=dict)


class BackblazeB2SinkConfig(PluginConfigModel):
    region: str = Field(min_length=1)
    key_id: str
    application_key: str
    bucket: str = Field(min_length=1)
    prefix: str = ""
    path_template: str = "{knowledge_base}/{run_id}/{artifact}.{format}"
    overwrite: bool = False
    dry_run: bool = False
    include_retrieval_artifact: bool = True
    include_markdown_summary: bool = True
    parquet_export: bool = False
    max_retries: int = Field(default=3, ge=0)
    connect_timeout_seconds: int = Field(default=10, gt=0)
    read_timeout_seconds: int = Field(default=30, gt=0)
    object_metadata: dict[str, str] = Field(default_factory=dict)


class Microsoft365SourceConfig(PluginConfigModel):
    tenant_id: str
    client_id: str
    client_secret: str
    site_url: str | None = None
    scope: str = "sharepoint"
    page_size: int = 100


class WikiSourceConfig(PluginConfigModel):
    base_url: str
    access_token: str


class AnalyticsSinkConfig(PluginConfigModel):
    db_path: str = ":memory:"
    table_prefix: str = ""
    include_embeddings: bool = False


class ConfluenceSourcePluginConfig(PluginConfigModel):
    base_url: str
    space_key: str | None = None
    email: str = ""
    api_token: str = ""
    page_size: int = 50


class NotionSourcePluginConfig(PluginConfigModel):
    api_token: str
    page_size: int = 50
    filter_kind: str | None = None
    notion_version: str = "2022-06-28"


class FeishuSourcePluginConfig(PluginConfigModel):
    space_id: str
    app_id: str
    app_secret: str
    base_url: str = "https://open.feishu.cn"
    page_size: int = 50


class AnthropicCloudModelConfig(PluginConfigModel):
    api_base_url: str = "https://api.anthropic.com/v1"
    model_name: str = "claude-sonnet-4-5"


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


class WebSourceConfig(PluginConfigModel):
    urls: list[str]
    max_depth: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, gt=0)
    timeout_seconds: float = Field(default=15.0, gt=0)
    verify_tls: bool = True
    user_agent: str = "RAGRig-WebSource/1.0"
    include_patterns: list[str] = []
    exclude_patterns: list[str] = []
    cookies: dict[str, str] = {}
    headers: dict[str, str] = {}
    bearer_token: str | None = None
    basic_auth_username: str | None = None
    basic_auth_password: str | None = None


class AgentAccessSinkFullConfig(PluginConfigModel):
    endpoint_url: str
    api_key: str
    hmac_secret: str | None = None
    batch_size: int = Field(default=100, gt=0)
    timeout_seconds: float = Field(default=30.0, gt=0)
    verify_tls: bool = True


class WebhookSinkConfig(PluginConfigModel):
    endpoint_url: str
    hmac_secret: str | None = None
    format: str = "ndjson"
    extra_headers: dict[str, str] = {}
    batch_size: int = Field(default=200, gt=0)
    timeout_seconds: float = Field(default=30.0, gt=0)
    verify_tls: bool = True


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
    degraded_missing_dependencies: tuple[str, ...] = (),
    config_model: type[PluginConfigModel] | None = None,
    example_config: dict[str, object] | None = None,
    secret_requirements: tuple[SecretRequirement, ...] = (),
    status: PluginStatus = PluginStatus.UNAVAILABLE,
    unavailable_reason: str | None,
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
        degraded_missing_dependencies=degraded_missing_dependencies,
        unavailable_reason=unavailable_reason,
    )


def official_stub_manifests() -> list[PluginManifest]:
    s3_ready = guards.is_dependency_available("boto3")
    pyarrow_ready = guards.is_dependency_available("pyarrow")
    qdrant_ready = guards.is_dependency_available("qdrant_client")
    google_workspace_ready = guards.is_dependency_available("googleapiclient")
    duckdb_ready = guards.is_dependency_available("duckdb")
    docling_ready = guards.is_dependency_available("docling")
    ebooklib_ready = guards.is_dependency_available("ebooklib")
    fileshare_protocol_dependencies = {
        "nfs_mounted": (),
        "sftp": ("paramiko",),
        "smb": ("smbprotocol",),
        "webdav": ("httpx",),
    }
    fileshare_protocol_statuses = {
        protocol: (
            PluginStatus.READY
            if not guards.list_missing_dependencies(dependencies)
            else PluginStatus.UNAVAILABLE
        )
        for protocol, dependencies in fileshare_protocol_dependencies.items()
    }
    fileshare_missing_dependencies = sorted(
        {
            dependency
            for dependencies in fileshare_protocol_dependencies.values()
            for dependency in guards.list_missing_dependencies(dependencies)
        }
    )
    fileshare_ready_count = sum(
        1 for status in fileshare_protocol_statuses.values() if status is PluginStatus.READY
    )
    fileshare_status = PluginStatus.UNAVAILABLE
    fileshare_reason = "Install fileshare protocol dependencies to enable the runtime connector."
    if fileshare_ready_count == len(fileshare_protocol_statuses):
        fileshare_status = PluginStatus.READY
        fileshare_reason = None
    elif fileshare_ready_count > 0:
        fileshare_status = PluginStatus.DEGRADED
        fileshare_reason = (
            "Mounted NFS/local-path mode is ready; install optional SDKs for SMB, WebDAV, and SFTP."
        )
    return [
        _official_manifest(
            plugin_id="vector.qdrant",
            display_name="Qdrant Vector Backend",
            description="Qdrant vector backend for similarity search and retrieval.",
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
            status=PluginStatus.READY if qdrant_ready else PluginStatus.UNAVAILABLE,
            unavailable_reason=(
                None
                if qdrant_ready
                else "Install qdrant-client to enable the Qdrant vector backend connector."
            ),
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
            description="Azure OpenAI provider for chat, generate, and embeddings.",
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
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.openrouter",
            display_name="OpenRouter Cloud Provider",
            description="OpenRouter provider for chat and generate over an OpenAI-compatible API.",
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
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.openai",
            display_name="OpenAI Cloud Provider",
            description="OpenAI provider for chat, generate, and embeddings.",
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
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.jina",
            display_name="Jina AI Cloud Provider",
            description="Jina AI provider for embeddings and rerank via httpx.",
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
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.anthropic",
            display_name="Anthropic Claude Cloud Provider",
            description="Anthropic Claude provider for chat and generation via the Messages API.",
            plugin_type=PluginType.MODEL,
            family="anthropic",
            capabilities=(Capability.GENERATE_TEXT,),
            config_model=AnthropicCloudModelConfig,
            example_config={
                "api_base_url": "https://api.anthropic.com/v1",
                "model_name": "claude-sonnet-4-5",
            },
            secret_requirements=(
                SecretRequirement(name="ANTHROPIC_API_KEY", description="Anthropic API key"),
            ),
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.mistral",
            display_name="Mistral AI Cloud Provider",
            description="Mistral AI provider for chat, generation, and embeddings via OpenAI API.",
            plugin_type=PluginType.MODEL,
            family="mistral",
            capabilities=(Capability.GENERATE_TEXT, Capability.EMBED_TEXT),
            config_model=CloudEmbeddingModelConfig,
            example_config={
                "api_base_url": "https://api.mistral.ai/v1",
                "model_name": "mistral-large-latest",
                "embedding_model_name": "mistral-embed",
            },
            secret_requirements=(
                SecretRequirement(name="MISTRAL_API_KEY", description="Mistral AI API key"),
            ),
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.together",
            display_name="Together AI Cloud Provider",
            description="Together AI provider for chat, generation, and embeddings via OpenAI API.",
            plugin_type=PluginType.MODEL,
            family="together",
            capabilities=(Capability.GENERATE_TEXT, Capability.EMBED_TEXT),
            config_model=CloudEmbeddingModelConfig,
            example_config={
                "api_base_url": "https://api.together.xyz/v1",
                "model_name": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
                "embedding_model_name": "togethercomputer/m2-bert-80M-8k-retrieval",
            },
            secret_requirements=(
                SecretRequirement(name="TOGETHER_API_KEY", description="Together AI API key"),
            ),
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.fireworks",
            display_name="Fireworks AI Cloud Provider",
            description="Fireworks AI provider for chat and generation via OpenAI-compatible API.",
            plugin_type=PluginType.MODEL,
            family="fireworks",
            capabilities=(Capability.GENERATE_TEXT,),
            config_model=CloudModelConfig,
            example_config={
                "api_base_url": "https://api.fireworks.ai/inference/v1",
                "model_name": "accounts/fireworks/models/llama-v3p1-70b",
            },
            secret_requirements=(
                SecretRequirement(name="FIREWORKS_API_KEY", description="Fireworks AI API key"),
            ),
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.groq",
            display_name="Groq Cloud Provider",
            description="Groq provider for ultra-fast chat and generation via OpenAI API.",
            plugin_type=PluginType.MODEL,
            family="groq",
            capabilities=(Capability.GENERATE_TEXT,),
            config_model=CloudModelConfig,
            example_config={
                "api_base_url": "https://api.groq.com/openai/v1",
                "model_name": "llama-3.3-70b-versatile",
            },
            secret_requirements=(
                SecretRequirement(name="GROQ_API_KEY", description="Groq API key"),
            ),
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.deepseek",
            display_name="DeepSeek Cloud Provider",
            description="DeepSeek provider for chat and generation via OpenAI-compatible API.",
            plugin_type=PluginType.MODEL,
            family="deepseek",
            capabilities=(Capability.GENERATE_TEXT,),
            config_model=CloudModelConfig,
            example_config={
                "api_base_url": "https://api.deepseek.com/v1",
                "model_name": "deepseek-chat",
            },
            secret_requirements=(
                SecretRequirement(name="DEEPSEEK_API_KEY", description="DeepSeek API key"),
            ),
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.moonshot",
            display_name="Moonshot Kimi Cloud Provider",
            description="Moonshot Kimi provider for chat and generation via OpenAI-compatible API.",
            plugin_type=PluginType.MODEL,
            family="moonshot",
            capabilities=(Capability.GENERATE_TEXT,),
            config_model=CloudModelConfig,
            example_config={
                "api_base_url": "https://api.moonshot.ai/v1",
                "model_name": "kimi-k2.5",
            },
            secret_requirements=(
                SecretRequirement(name="MOONSHOT_API_KEY", description="Moonshot API key"),
            ),
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.minimax",
            display_name="MiniMax Cloud Provider",
            description="MiniMax provider for chat and generation via OpenAI-compatible API.",
            plugin_type=PluginType.MODEL,
            family="minimax",
            capabilities=(Capability.GENERATE_TEXT,),
            config_model=CloudModelConfig,
            example_config={
                "api_base_url": "https://api.minimax.io/v1",
                "model_name": "MiniMax-M2.7",
            },
            secret_requirements=(
                SecretRequirement(name="MINIMAX_API_KEY", description="MiniMax API key"),
            ),
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.dashscope",
            display_name="Alibaba DashScope Cloud Provider",
            description="SiliconFlow provider for chat, generation, embeddings, and rerank.",
            plugin_type=PluginType.MODEL,
            family="dashscope",
            capabilities=(Capability.GENERATE_TEXT, Capability.EMBED_TEXT),
            config_model=CloudEmbeddingModelConfig,
            example_config={
                "api_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "model_name": "qwen-plus",
                "embedding_model_name": "text-embedding-v4",
            },
            secret_requirements=(
                SecretRequirement(name="DASHSCOPE_API_KEY", description="DashScope API key"),
            ),
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.siliconflow",
            display_name="SiliconFlow Cloud Provider",
            description="Zhipu / Z.ai GLM provider for chat and generation via OpenAI API.",
            plugin_type=PluginType.MODEL,
            family="siliconflow",
            capabilities=(Capability.GENERATE_TEXT, Capability.EMBED_TEXT, Capability.RERANK),
            config_model=CloudGenerateEmbeddingRerankModelConfig,
            example_config={
                "api_base_url": "https://api.siliconflow.cn/v1",
                "model_name": "Qwen/Qwen3-235B-A22B-Instruct-2507",
                "embedding_model_name": "BAAI/bge-m3",
                "reranker_model_name": "BAAI/bge-reranker-v2-m3",
            },
            secret_requirements=(
                SecretRequirement(name="SILICONFLOW_API_KEY", description="SiliconFlow API key"),
            ),
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.zhipu",
            display_name="Zhipu GLM Cloud Provider",
            description="Baidu Qianfan ERNIE provider for chat and generation via OpenAI API.",
            plugin_type=PluginType.MODEL,
            family="zhipu",
            capabilities=(Capability.GENERATE_TEXT,),
            config_model=CloudModelConfig,
            example_config={
                "api_base_url": "https://open.bigmodel.cn/api/paas/v4",
                "model_name": "glm-4.5",
            },
            secret_requirements=(
                SecretRequirement(name="ZHIPU_API_KEY", description="Zhipu API key"),
            ),
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.baidu_qianfan",
            display_name="Baidu Qianfan Cloud Provider",
            description="Volcengine Ark Doubao provider for chat and generation via OpenAI API.",
            plugin_type=PluginType.MODEL,
            family="baidu_qianfan",
            capabilities=(Capability.GENERATE_TEXT,),
            config_model=CloudModelConfig,
            example_config={
                "api_base_url": "https://qianfan.baidubce.com/v2",
                "model_name": "ernie-4.5-turbo",
            },
            secret_requirements=(
                SecretRequirement(name="QIANFAN_API_KEY", description="Baidu Qianfan API key"),
            ),
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.volcengine_ark",
            display_name="Volcengine Ark Cloud Provider",
            description="xAI Grok provider for chat and generation via OpenAI-compatible API.",
            plugin_type=PluginType.MODEL,
            family="volcengine_ark",
            capabilities=(Capability.GENERATE_TEXT,),
            config_model=CloudModelConfig,
            example_config={
                "api_base_url": "https://ark.cn-beijing.volces.com/api/v3",
                "model_name": "doubao-seed-1-6",
            },
            secret_requirements=(
                SecretRequirement(name="ARK_API_KEY", description="Volcengine Ark API key"),
            ),
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.xai",
            display_name="xAI Grok Cloud Provider",
            description="xAI Grok provider for chat and generation via OpenAI-compatible API.",
            plugin_type=PluginType.MODEL,
            family="xai",
            capabilities=(Capability.GENERATE_TEXT,),
            config_model=CloudModelConfig,
            example_config={
                "api_base_url": "https://api.x.ai/v1",
                "model_name": "grok-4",
            },
            secret_requirements=(SecretRequirement(name="XAI_API_KEY", description="xAI API key"),),
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.perplexity",
            display_name="Perplexity Cloud Provider",
            description="NVIDIA NIM provider for chat, generation, and embeddings via OpenAI API.",
            plugin_type=PluginType.MODEL,
            family="perplexity",
            capabilities=(Capability.GENERATE_TEXT,),
            config_model=CloudModelConfig,
            example_config={
                "api_base_url": "https://api.perplexity.ai/v1",
                "model_name": "sonar-pro",
            },
            secret_requirements=(
                SecretRequirement(name="PERPLEXITY_API_KEY", description="Perplexity API key"),
            ),
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="model.nvidia_nim",
            display_name="NVIDIA NIM Cloud Provider",
            description="Alibaba DashScope provider for chat, generation, and embeddings.",
            plugin_type=PluginType.MODEL,
            family="nvidia_nim",
            capabilities=(Capability.GENERATE_TEXT, Capability.EMBED_TEXT),
            config_model=CloudEmbeddingModelConfig,
            example_config={
                "api_base_url": "https://integrate.api.nvidia.com/v1",
                "model_name": "meta/llama-3.1-70b-instruct",
                "embedding_model_name": "nvidia/nv-embedqa-e5-v5",
            },
            secret_requirements=(
                SecretRequirement(name="NVIDIA_API_KEY", description="NVIDIA API key"),
            ),
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
            description=(
                "Exports governed assets and audit artifacts to S3-compatible object storage."
            ),
            plugin_type=PluginType.SINK,
            family="object_storage",
            capabilities=(Capability.WRITE,),
            docs_reference="docs/specs/ragrig-plugin-system-spec.md",
            optional_dependencies=("boto3", "pyarrow"),
            degraded_missing_dependencies=("boto3", "pyarrow"),
            config_model=ObjectStorageSinkConfig,
            example_config={
                "bucket": "exports",
                "prefix": "team-a",
                "endpoint_url": "http://localhost:9000",
                "region": "us-east-1",
                "use_path_style": True,
                "verify_tls": True,
                "access_key": "env:AWS_ACCESS_KEY_ID",
                "secret_key": "env:AWS_SECRET_ACCESS_KEY",
                "session_token": "env:AWS_SESSION_TOKEN",
                "path_template": "{knowledge_base}/{run_id}/{artifact}.{format}",
                "overwrite": False,
                "dry_run": False,
                "include_retrieval_artifact": True,
                "include_markdown_summary": True,
                "parquet_export": False,
                "max_retries": 3,
                "connect_timeout_seconds": 10,
                "read_timeout_seconds": 30,
                "object_metadata": {"environment": "dev"},
            },
            secret_requirements=(
                SecretRequirement(
                    name="AWS_ACCESS_KEY_ID", description="Object storage access key id"
                ),
                SecretRequirement(
                    name="AWS_SECRET_ACCESS_KEY", description="Object storage secret access key"
                ),
                SecretRequirement(
                    name="AWS_SESSION_TOKEN",
                    description="Optional session token for temporary credentials",
                    required=False,
                ),
            ),
            unavailable_reason=None,
            status=PluginStatus.READY if (s3_ready and pyarrow_ready) else PluginStatus.DEGRADED,
        ),
        _official_manifest(
            plugin_id="source.cloudflare_r2",
            display_name="Cloudflare R2 Source",
            description=(
                "Reads Cloudflare R2 object storage into the ingestion pipeline "
                "using S3-compatible API with SigV4 authentication."
            ),
            plugin_type=PluginType.SOURCE,
            family="cloudflare_r2",
            capabilities=(
                Capability.READ,
                Capability.INCREMENTAL_SYNC,
            ),
            docs_reference="docs/specs/ragrig-plugin-system-spec.md",
            optional_dependencies=("boto3",),
            config_model=CloudflareR2SourceConfig,
            example_config={
                "account_id": "your-account-id",
                "access_key_id": "env:CF_R2_ACCESS_KEY_ID",
                "secret_access_key": "env:CF_R2_SECRET_ACCESS_KEY",
                "bucket": "docs",
                "prefix": "team-a",
                "jurisdiction": None,
                "include_patterns": ["*.md", "*.txt"],
                "exclude_patterns": [],
                "max_object_size_mb": 50,
                "page_size": 1000,
                "max_retries": 3,
            },
            secret_requirements=(
                SecretRequirement(
                    name="CF_R2_ACCESS_KEY_ID", description="Cloudflare R2 access key id"
                ),
                SecretRequirement(
                    name="CF_R2_SECRET_ACCESS_KEY", description="Cloudflare R2 secret access key"
                ),
            ),
            unavailable_reason=(
                None if s3_ready else "Install boto3 to enable the Cloudflare R2 source connector."
            ),
            status=PluginStatus.READY if s3_ready else PluginStatus.UNAVAILABLE,
        ),
        _official_manifest(
            plugin_id="source.backblaze_b2",
            display_name="Backblaze B2 Source",
            description=(
                "Reads Backblaze B2 object storage into the ingestion pipeline "
                "using the S3-compatible API."
            ),
            plugin_type=PluginType.SOURCE,
            family="backblaze_b2",
            capabilities=(
                Capability.READ,
                Capability.INCREMENTAL_SYNC,
            ),
            docs_reference="docs/specs/ragrig-plugin-system-spec.md",
            optional_dependencies=("boto3",),
            config_model=BackblazeB2SourceConfig,
            example_config={
                "region": "us-west-004",
                "key_id": "env:B2_APPLICATION_KEY_ID",
                "application_key": "env:B2_APPLICATION_KEY",
                "bucket": "docs",
                "prefix": "team-a",
                "include_patterns": ["*.md", "*.txt"],
                "exclude_patterns": [],
                "max_object_size_mb": 50,
                "page_size": 1000,
                "max_retries": 3,
            },
            secret_requirements=(
                SecretRequirement(
                    name="B2_APPLICATION_KEY_ID", description="Backblaze B2 application key id"
                ),
                SecretRequirement(
                    name="B2_APPLICATION_KEY", description="Backblaze B2 application key"
                ),
            ),
            unavailable_reason=(
                None if s3_ready else "Install boto3 to enable the Backblaze B2 source connector."
            ),
            status=PluginStatus.READY if s3_ready else PluginStatus.UNAVAILABLE,
        ),
        _official_manifest(
            plugin_id="sink.cloudflare_r2",
            display_name="Cloudflare R2 Sink",
            description=(
                "Exports governed assets and audit artifacts to Cloudflare R2 object storage."
            ),
            plugin_type=PluginType.SINK,
            family="cloudflare_r2",
            capabilities=(Capability.WRITE,),
            docs_reference="docs/specs/ragrig-plugin-system-spec.md",
            optional_dependencies=("boto3", "pyarrow"),
            degraded_missing_dependencies=("boto3", "pyarrow"),
            config_model=CloudflareR2SinkConfig,
            example_config={
                "account_id": "your-account-id",
                "access_key_id": "env:CF_R2_ACCESS_KEY_ID",
                "secret_access_key": "env:CF_R2_SECRET_ACCESS_KEY",
                "bucket": "exports",
                "prefix": "team-a",
                "jurisdiction": None,
                "path_template": "{knowledge_base}/{run_id}/{artifact}.{format}",
                "overwrite": False,
                "dry_run": False,
                "include_retrieval_artifact": True,
                "include_markdown_summary": True,
                "parquet_export": False,
                "max_retries": 3,
                "connect_timeout_seconds": 10,
                "read_timeout_seconds": 30,
                "object_metadata": {},
            },
            secret_requirements=(
                SecretRequirement(
                    name="CF_R2_ACCESS_KEY_ID", description="Cloudflare R2 access key id"
                ),
                SecretRequirement(
                    name="CF_R2_SECRET_ACCESS_KEY", description="Cloudflare R2 secret access key"
                ),
            ),
            unavailable_reason=None,
            status=PluginStatus.READY if (s3_ready and pyarrow_ready) else PluginStatus.DEGRADED,
        ),
        _official_manifest(
            plugin_id="sink.backblaze_b2",
            display_name="Backblaze B2 Sink",
            description=(
                "Exports governed assets and audit artifacts to Backblaze B2 object storage."
            ),
            plugin_type=PluginType.SINK,
            family="backblaze_b2",
            capabilities=(Capability.WRITE,),
            docs_reference="docs/specs/ragrig-plugin-system-spec.md",
            optional_dependencies=("boto3", "pyarrow"),
            degraded_missing_dependencies=("boto3", "pyarrow"),
            config_model=BackblazeB2SinkConfig,
            example_config={
                "region": "us-west-004",
                "key_id": "env:B2_APPLICATION_KEY_ID",
                "application_key": "env:B2_APPLICATION_KEY",
                "bucket": "exports",
                "prefix": "team-a",
                "path_template": "{knowledge_base}/{run_id}/{artifact}.{format}",
                "overwrite": False,
                "dry_run": False,
                "include_retrieval_artifact": True,
                "include_markdown_summary": True,
                "parquet_export": False,
                "max_retries": 3,
                "connect_timeout_seconds": 10,
                "read_timeout_seconds": 30,
                "object_metadata": {},
            },
            secret_requirements=(
                SecretRequirement(
                    name="B2_APPLICATION_KEY_ID", description="Backblaze B2 application key id"
                ),
                SecretRequirement(
                    name="B2_APPLICATION_KEY", description="Backblaze B2 application key"
                ),
            ),
            unavailable_reason=None,
            status=PluginStatus.READY if (s3_ready and pyarrow_ready) else PluginStatus.DEGRADED,
        ),
        _official_manifest(
            plugin_id="source.fileshare",
            display_name="Fileshare Source",
            description="Enterprise fileshare source for SMB, mounted NFS, WebDAV, and SFTP.",
            plugin_type=PluginType.SOURCE,
            family="fileshare",
            capabilities=(
                Capability.READ,
                Capability.INCREMENTAL_SYNC,
                Capability.DELETE_DETECTION,
                Capability.PERMISSION_MAPPING,
            ),
            optional_dependencies=tuple(fileshare_missing_dependencies),
            config_model=FileshareSourceConfig,
            docs_reference="docs/specs/ragrig-fileshare-source-plugin-spec.md",
            example_config={
                "protocol": "smb",
                "host": "files.example.internal",
                "share": "knowledge",
                "root_path": "/docs",
                "username": "env:FILESHARE_USERNAME",
                "password": "env:FILESHARE_PASSWORD",
            },
            secret_requirements=(
                SecretRequirement(
                    name="FILESHARE_USERNAME", description="Fileshare username", required=False
                ),
                SecretRequirement(
                    name="FILESHARE_PASSWORD", description="Fileshare password", required=False
                ),
                SecretRequirement(
                    name="FILESHARE_PRIVATE_KEY",
                    description="Fileshare private key for SFTP auth",
                    required=False,
                ),
            ),
            status=fileshare_status,
            unavailable_reason=fileshare_reason,
        ),
        _official_manifest(
            plugin_id="source.google_workspace",
            display_name="Google Workspace Source",
            description=(
                "Pilot connector for Google Drive and Google Docs with dry-run"
                " discovery, incremental cursor, and secret masking."
            ),
            plugin_type=PluginType.SOURCE,
            family="google_workspace",
            capabilities=(
                Capability.READ,
                Capability.INCREMENTAL_SYNC,
            ),
            docs_reference="docs/specs/SPEC-google-workspace-source-connector.md",
            optional_dependencies=("googleapiclient",),
            degraded_missing_dependencies=("googleapiclient",),
            config_model=GoogleWorkspaceSourceConfig,
            example_config={
                "drive_id": "shared-drive-id",
                "include_shared_drives": False,
                "include_patterns": ["*.pdf", "*.txt", "*.docx"],
                "exclude_patterns": [],
                "page_size": 100,
                "max_retries": 3,
                "service_account_json": "env:GOOGLE_SERVICE_ACCOUNT_JSON",
            },
            secret_requirements=(
                SecretRequirement(
                    name="GOOGLE_SERVICE_ACCOUNT_JSON",
                    description="Google service account JSON key",
                    required=True,
                ),
            ),
            unavailable_reason=(
                None
                if google_workspace_ready
                else "Install google-api-python-client to enable live Google Workspace discovery."
            ),
            status=PluginStatus.READY if google_workspace_ready else PluginStatus.DEGRADED,
        ),
        _official_manifest(
            plugin_id="source.confluence",
            display_name="Confluence Cloud Source",
            description="Confluence Cloud connector — lists pages via REST API with basic auth.",
            plugin_type=PluginType.SOURCE,
            family="confluence",
            capabilities=(Capability.READ, Capability.INCREMENTAL_SYNC),
            config_model=ConfluenceSourcePluginConfig,
            example_config={
                "base_url": "https://your-org.atlassian.net/wiki",
                "space_key": "ENG",
                "email": "env:CONFLUENCE_EMAIL",
                "api_token": "env:CONFLUENCE_API_TOKEN",
                "page_size": 50,
            },
            secret_requirements=(
                SecretRequirement(name="CONFLUENCE_EMAIL", description="Atlassian account email"),
                SecretRequirement(name="CONFLUENCE_API_TOKEN", description="Confluence API token"),
            ),
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="source.notion",
            display_name="Notion Source",
            description="Confluence Cloud connector — lists pages via REST API with basic auth.",
            plugin_type=PluginType.SOURCE,
            family="notion",
            capabilities=(Capability.READ, Capability.INCREMENTAL_SYNC),
            config_model=NotionSourcePluginConfig,
            example_config={
                "api_token": "env:NOTION_API_TOKEN",
                "page_size": 50,
                "filter_kind": "page",
            },
            secret_requirements=(
                SecretRequirement(name="NOTION_API_TOKEN", description="Notion integration token"),
            ),
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="source.feishu",
            display_name="Feishu / Lark Source",
            description="Notion connector — enumerates pages and databases via the Notion API.",
            plugin_type=PluginType.SOURCE,
            family="feishu",
            capabilities=(Capability.READ, Capability.INCREMENTAL_SYNC),
            config_model=FeishuSourcePluginConfig,
            example_config={
                "space_id": "your-wiki-space-id",
                "app_id": "env:FEISHU_APP_ID",
                "app_secret": "env:FEISHU_APP_SECRET",
                "base_url": "https://open.feishu.cn",
                "page_size": 50,
            },
            secret_requirements=(
                SecretRequirement(name="FEISHU_APP_ID", description="Feishu app ID"),
                SecretRequirement(name="FEISHU_APP_SECRET", description="Feishu app secret"),
            ),
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="source.web",
            display_name="Web Source",
            description=(
                "Fetches web pages via HTTP with cookie, bearer, basic-auth, "
                "and custom-header support."
            ),
            plugin_type=PluginType.SOURCE,
            family="web",
            capabilities=(Capability.READ, Capability.INCREMENTAL_SYNC),
            config_model=WebSourceConfig,
            example_config={
                "urls": ["https://docs.example.com/"],
                "max_depth": 2,
                "bearer_token": "env:WEB_BEARER_TOKEN",
                "cookies": {"session": "env:WEB_SESSION_COOKIE"},
            },
            secret_requirements=(
                SecretRequirement(
                    name="WEB_BEARER_TOKEN",
                    description="Bearer token for authenticated web sources",
                    required=False,
                ),
                SecretRequirement(
                    name="WEB_SESSION_COOKIE",
                    description="Session cookie value for authenticated web sources",
                    required=False,
                ),
                SecretRequirement(
                    name="WEB_BASIC_AUTH_PASSWORD",
                    description="Basic auth password for authenticated web sources",
                    required=False,
                ),
            ),
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="source.microsoft_365",
            display_name="Microsoft 365 Source",
            description=(
                "SharePoint and OneDrive connector via Microsoft Graph API. "
                "Uses app-only client credentials — no external SDK required."
            ),
            plugin_type=PluginType.SOURCE,
            family="microsoft_365",
            capabilities=(
                Capability.READ,
                Capability.INCREMENTAL_SYNC,
                Capability.PERMISSION_MAPPING,
            ),
            config_model=Microsoft365SourceConfig,
            example_config={
                "tenant_id": "env:MICROSOFT_365_TENANT_ID",
                "client_id": "env:MICROSOFT_365_CLIENT_ID",
                "client_secret": "env:MICROSOFT_365_CLIENT_SECRET",
                "site_url": "https://myorg.sharepoint.com/sites/Engineering",
                "scope": "sharepoint",
                "page_size": 100,
            },
            secret_requirements=(
                SecretRequirement(
                    name="MICROSOFT_365_TENANT_ID",
                    description="Azure AD tenant ID",
                    required=True,
                ),
                SecretRequirement(
                    name="MICROSOFT_365_CLIENT_ID",
                    description="Azure AD app registration client ID",
                    required=True,
                ),
                SecretRequirement(
                    name="MICROSOFT_365_CLIENT_SECRET",
                    description="Azure AD app registration client secret",
                    required=True,
                ),
            ),
            status=PluginStatus.READY,
            unavailable_reason=None,
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
            description="PostgreSQL/MySQL read-only query ingestion.",
            plugin_type=PluginType.SOURCE,
            family="database",
            capabilities=(
                Capability.READ,
                Capability.INCREMENTAL_SYNC,
                Capability.DELETE_DETECTION,
            ),
            optional_dependencies=("pymysql",),
            degraded_missing_dependencies=("pymysql",),
            config_model=DatabaseSourceConfig,
            example_config={
                "engine": "postgresql",
                "dsn": "env:SOURCE_DATABASE_DSN",
                "source_name": "crm",
                "queries": [
                    {
                        "name": "accounts",
                        "sql": "select id, name, notes from accounts where active = :active",
                        "params": {"active": True},
                        "document_id_columns": ["id"],
                        "title_column": "name",
                        "text_columns": ["name", "notes"],
                        "metadata_columns": [],
                    }
                ],
            },
            secret_requirements=(
                SecretRequirement(
                    name="SOURCE_DATABASE_DSN", description="Database connection string"
                ),
            ),
            unavailable_reason=None,
            status=PluginStatus.READY,
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
            description=(
                "Layout-aware PDF/DOCX/PPTX/XLSX parser with table extraction via Docling."
            ),
            plugin_type=PluginType.PARSER,
            family="advanced_documents",
            capabilities=(Capability.READ, Capability.PARSE_TEXT),
            optional_dependencies=("docling",),
            status=PluginStatus.READY if docling_ready else PluginStatus.UNAVAILABLE,
            unavailable_reason=(
                None
                if docling_ready
                else "Install docling to enable layout-aware parsing: pip install docling"
            ),
        ),
        _official_manifest(
            plugin_id="parser.email",
            display_name="Email Parser",
            description="Parses EML and MSG email files — extracts headers and body text.",
            plugin_type=PluginType.PARSER,
            family="email",
            capabilities=(Capability.READ, Capability.PARSE_TEXT),
            status=PluginStatus.READY,
            unavailable_reason=None,
            example_config={},
        ),
        _official_manifest(
            plugin_id="parser.xml",
            display_name="XML Parser",
            description="Extracts text nodes from XML documents using the standard library.",
            plugin_type=PluginType.PARSER,
            family="xml",
            capabilities=(Capability.READ, Capability.PARSE_TEXT),
            status=PluginStatus.READY,
            unavailable_reason=None,
            example_config={},
        ),
        _official_manifest(
            plugin_id="parser.json",
            display_name="JSON Parser",
            description="Flattens JSON documents into key-path: value text for indexing.",
            plugin_type=PluginType.PARSER,
            family="json",
            capabilities=(Capability.READ, Capability.PARSE_TEXT),
            status=PluginStatus.READY,
            unavailable_reason=None,
            example_config={},
        ),
        _official_manifest(
            plugin_id="parser.epub",
            display_name="EPUB Parser",
            description="Parses EPUB e-books into plain text via ebooklib.",
            plugin_type=PluginType.PARSER,
            family="epub",
            capabilities=(Capability.READ, Capability.PARSE_TEXT),
            optional_dependencies=("ebooklib",),
            status=PluginStatus.READY if ebooklib_ready else PluginStatus.UNAVAILABLE,
            unavailable_reason=(
                None
                if ebooklib_ready
                else "Install ebooklib to enable EPUB parsing: pip install ebooklib"
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
            description="DuckDB analytics sink — exports chunks and embeddings to a local DB.",
            plugin_type=PluginType.SINK,
            family="analytics",
            capabilities=(Capability.WRITE,),
            config_model=AnalyticsSinkConfig,
            optional_dependencies=("duckdb",),
            example_config={"db_path": "/data/kb.duckdb", "table_prefix": ""},
            status=PluginStatus.READY if duckdb_ready else PluginStatus.UNAVAILABLE,
            unavailable_reason=(
                None
                if duckdb_ready
                else "Install duckdb to enable the analytics sink: pip install duckdb"
            ),
        ),
        _official_manifest(
            plugin_id="sink.agent_access",
            display_name="Agent Access Sink",
            description=(
                "Pushes chunks to an MCP-compatible HTTP endpoint with "
                "Bearer auth and optional HMAC signing."
            ),
            plugin_type=PluginType.SINK,
            family="agent_access",
            capabilities=(Capability.WRITE,),
            config_model=AgentAccessSinkFullConfig,
            example_config={
                "endpoint_url": "https://example.com/mcp/ingest",
                "api_key": "env:AGENT_ACCESS_API_KEY",
                "hmac_secret": "env:AGENT_ACCESS_HMAC_SECRET",
                "batch_size": 100,
            },
            secret_requirements=(
                SecretRequirement(name="AGENT_ACCESS_API_KEY", description="Agent access API key"),
                SecretRequirement(
                    name="AGENT_ACCESS_HMAC_SECRET",
                    description="HMAC-SHA256 signing secret",
                    required=False,
                ),
            ),
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
        _official_manifest(
            plugin_id="sink.webhook",
            display_name="Webhook Sink",
            description=(
                "Pushes chunks to any HTTP endpoint as NDJSON or JSON "
                "with optional HMAC-SHA256 signature."
            ),
            plugin_type=PluginType.SINK,
            family="webhook",
            capabilities=(Capability.WRITE,),
            config_model=WebhookSinkConfig,
            example_config={
                "endpoint_url": "https://example.com/webhooks/ragrig",
                "hmac_secret": "env:WEBHOOK_HMAC_SECRET",
                "format": "ndjson",
                "batch_size": 200,
            },
            secret_requirements=(
                SecretRequirement(
                    name="WEBHOOK_HMAC_SECRET",
                    description="HMAC-SHA256 signing secret for webhook verification",
                    required=False,
                ),
            ),
            status=PluginStatus.READY,
            unavailable_reason=None,
        ),
    ]
