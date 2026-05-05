from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ragrig.embeddings import EmbeddingResult
from ragrig.providers import (
    BaseProvider,
    ProviderCapability,
    ProviderError,
    ProviderHealth,
    ProviderKind,
    ProviderMetadata,
    ProviderRetryPolicy,
)


def _optional_dependency_error(*, provider: str, dependencies: list[str]) -> ProviderError:
    return ProviderError(
        f"Provider '{provider}' requires optional cloud dependencies: {', '.join(dependencies)}",
        code="optional_dependency_missing",
        retryable=False,
        details={"provider": provider, "dependencies": dependencies},
    )


def _stub_runtime_error(*, provider: str) -> ProviderError:
    return ProviderError(
        f"Provider '{provider}' is a contract-only cloud stub in this phase",
        code="provider_stub_only",
        retryable=False,
        details={"provider": provider, "status": "stub_only"},
    )


def load_cloud_client(*, provider: str, dependencies: list[str]) -> Any:
    raise _optional_dependency_error(provider=provider, dependencies=dependencies)


def build_cloud_model_metadata(
    *,
    name: str,
    description: str,
    capabilities: set[ProviderCapability],
    required_secrets: list[str],
    config_schema: dict[str, Any],
    sdk_protocol: str,
    dependency_group: str,
    failure_modes: list[str],
    audit_fields: list[str],
    metric_fields: list[str],
    intended_uses: list[str],
    default_dimensions: int | None = None,
    max_dimensions: int | None = None,
    default_context_window: int | None = None,
    max_context_window: int | None = None,
) -> ProviderMetadata:
    return ProviderMetadata(
        name=name,
        kind=ProviderKind.CLOUD,
        description=description,
        capabilities=capabilities,
        default_dimensions=default_dimensions,
        max_dimensions=max_dimensions,
        default_context_window=default_context_window,
        max_context_window=max_context_window,
        required_secrets=required_secrets,
        config_schema=config_schema,
        sdk_protocol=sdk_protocol,
        healthcheck=(
            "Contract-only stub. Validate configured secrets and optional SDK availability without "
            f"performing live requests. Install via the optional '{dependency_group}' extra."
        ),
        failure_modes=failure_modes,
        retry_policy=ProviderRetryPolicy(max_attempts=1, backoff_seconds=0.0),
        audit_fields=audit_fields,
        metric_fields=metric_fields,
        intended_uses=intended_uses,
    )


VERTEX_AI_METADATA = build_cloud_model_metadata(
    name="model.vertex_ai",
    description=(
        "Contract-only Google Vertex AI cloud provider stub for chat, generate, and embeddings."
    ),
    capabilities={
        ProviderCapability.CHAT,
        ProviderCapability.GENERATE,
        ProviderCapability.EMBEDDING,
        ProviderCapability.BATCH,
    },
    required_secrets=["VERTEX_AI_PROJECT", "VERTEX_AI_LOCATION", "GOOGLE_APPLICATION_CREDENTIALS"],
    config_schema={
        "project": {"type": "string", "description": "Google Cloud project id."},
        "location": {"type": "string", "default": "us-central1"},
        "model_name": {"type": "string", "default": "gemini-2.5-pro"},
        "embedding_model_name": {"type": "string", "default": "text-embedding-005"},
    },
    sdk_protocol="optional-google-cloud-aiplatform-sdk",
    dependency_group="cloud-google",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "project", "location", "model", "embedding_model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "managed_enterprise"],
    default_dimensions=768,
    max_dimensions=3072,
    default_context_window=1048576,
)


BEDROCK_METADATA = build_cloud_model_metadata(
    name="model.bedrock",
    description=(
        "Contract-only Amazon Bedrock cloud provider stub for chat, generate, "
        "embeddings, and rerank."
    ),
    capabilities={
        ProviderCapability.CHAT,
        ProviderCapability.GENERATE,
        ProviderCapability.EMBEDDING,
        ProviderCapability.RERANK,
        ProviderCapability.BATCH,
    },
    required_secrets=["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION"],
    config_schema={
        "region": {"type": "string", "default": "us-east-1"},
        "model_name": {"type": "string", "default": "anthropic.claude-3-7-sonnet-20250219-v1:0"},
        "embedding_model_name": {"type": "string", "default": "amazon.titan-embed-text-v2:0"},
        "reranker_model_name": {"type": "string", "default": "cohere.rerank-v3-5:0"},
    },
    sdk_protocol="optional-boto3-bedrock-runtime",
    dependency_group="cloud-aws",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "region", "model", "embedding_model", "reranker_model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "managed_enterprise"],
    default_dimensions=1024,
    max_dimensions=4096,
    default_context_window=200000,
)


AZURE_OPENAI_METADATA = build_cloud_model_metadata(
    name="model.azure_openai",
    description=(
        "Contract-only Azure OpenAI cloud provider stub for chat, generate, and embeddings."
    ),
    capabilities={
        ProviderCapability.CHAT,
        ProviderCapability.GENERATE,
        ProviderCapability.EMBEDDING,
        ProviderCapability.BATCH,
    },
    required_secrets=["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"],
    config_schema={
        "api_base_url": {
            "type": "string",
            "default": "https://example-resource.openai.azure.com/openai/deployments",
        },
        "deployment_name": {"type": "string", "default": "gpt-4.1"},
        "embedding_deployment_name": {"type": "string", "default": "text-embedding-3-large"},
        "api_version": {"type": "string", "default": "2025-01-01-preview"},
    },
    sdk_protocol="optional-openai-sdk-azure-mode",
    dependency_group="cloud-openai",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "deployment", "embedding_deployment"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "enterprise_managed"],
    default_dimensions=3072,
    max_dimensions=3072,
    default_context_window=128000,
)


OPENROUTER_METADATA = build_cloud_model_metadata(
    name="model.openrouter",
    description=(
        "Contract-only OpenRouter cloud provider stub for chat and generate over an "
        "OpenAI-compatible API."
    ),
    capabilities={ProviderCapability.CHAT, ProviderCapability.GENERATE, ProviderCapability.BATCH},
    required_secrets=["OPENROUTER_API_KEY"],
    config_schema={
        "api_base_url": {"type": "string", "default": "https://openrouter.ai/api/v1"},
        "model_name": {"type": "string", "default": "openai/gpt-4.1-mini"},
    },
    sdk_protocol="optional-openai-compatible-cloud",
    dependency_group="cloud-openai",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "multi_provider_router"],
    default_context_window=128000,
)


OPENAI_METADATA = build_cloud_model_metadata(
    name="model.openai",
    description="Contract-only OpenAI cloud provider stub for chat, generate, and embeddings.",
    capabilities={
        ProviderCapability.CHAT,
        ProviderCapability.GENERATE,
        ProviderCapability.EMBEDDING,
        ProviderCapability.BATCH,
    },
    required_secrets=["OPENAI_API_KEY"],
    config_schema={
        "api_base_url": {"type": "string", "default": "https://api.openai.com/v1"},
        "model_name": {"type": "string", "default": "gpt-4.1-mini"},
        "embedding_model_name": {"type": "string", "default": "text-embedding-3-large"},
    },
    sdk_protocol="optional-openai-sdk",
    dependency_group="cloud-openai",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "model", "embedding_model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "managed_api"],
    default_dimensions=3072,
    max_dimensions=3072,
    default_context_window=128000,
)


COHERE_METADATA = build_cloud_model_metadata(
    name="model.cohere",
    description=(
        "Contract-only Cohere cloud provider stub for chat, generate, embeddings, and rerank."
    ),
    capabilities={
        ProviderCapability.CHAT,
        ProviderCapability.GENERATE,
        ProviderCapability.EMBEDDING,
        ProviderCapability.RERANK,
        ProviderCapability.BATCH,
    },
    required_secrets=["COHERE_API_KEY"],
    config_schema={
        "api_base_url": {"type": "string", "default": "https://api.cohere.com/v2"},
        "model_name": {"type": "string", "default": "command-r-plus"},
        "embedding_model_name": {"type": "string", "default": "embed-v4.0"},
        "reranker_model_name": {"type": "string", "default": "rerank-v3.5"},
    },
    sdk_protocol="optional-cohere-sdk",
    dependency_group="cloud-cohere",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "model", "embedding_model", "reranker_model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "managed_api"],
    default_dimensions=1024,
    max_dimensions=4096,
    default_context_window=128000,
)


VOYAGE_METADATA = build_cloud_model_metadata(
    name="model.voyage",
    description="Contract-only Voyage AI cloud provider stub for embeddings and rerank.",
    capabilities={
        ProviderCapability.EMBEDDING,
        ProviderCapability.RERANK,
        ProviderCapability.BATCH,
    },
    required_secrets=["VOYAGE_API_KEY"],
    config_schema={
        "api_base_url": {"type": "string", "default": "https://api.voyageai.com/v1"},
        "embedding_model_name": {"type": "string", "default": "voyage-3-large"},
        "reranker_model_name": {"type": "string", "default": "rerank-2.5"},
    },
    sdk_protocol="optional-voyageai-sdk",
    dependency_group="cloud-voyage",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "embedding_model", "reranker_model"],
    metric_fields=["requests_total", "document_count"],
    intended_uses=["cloud_second", "managed_retrieval"],
    default_dimensions=1024,
    max_dimensions=4096,
)


JINA_METADATA = build_cloud_model_metadata(
    name="model.jina",
    description="Contract-only Jina AI cloud provider stub for embeddings and rerank.",
    capabilities={
        ProviderCapability.EMBEDDING,
        ProviderCapability.RERANK,
        ProviderCapability.BATCH,
    },
    required_secrets=["JINA_API_KEY"],
    config_schema={
        "api_base_url": {"type": "string", "default": "https://api.jina.ai/v1"},
        "embedding_model_name": {"type": "string", "default": "jina-embeddings-v4"},
        "reranker_model_name": {"type": "string", "default": "jina-reranker-m0"},
    },
    sdk_protocol="optional-jina-http-api",
    dependency_group="cloud-jina",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "embedding_model", "reranker_model"],
    metric_fields=["requests_total", "document_count"],
    intended_uses=["cloud_second", "managed_retrieval"],
    default_dimensions=1024,
    max_dimensions=4096,
)


CLOUD_MODEL_METADATA = {
    VERTEX_AI_METADATA.name: (VERTEX_AI_METADATA, ["google-cloud-aiplatform"]),
    BEDROCK_METADATA.name: (BEDROCK_METADATA, ["boto3"]),
    AZURE_OPENAI_METADATA.name: (AZURE_OPENAI_METADATA, ["openai"]),
    OPENROUTER_METADATA.name: (OPENROUTER_METADATA, ["openai"]),
    OPENAI_METADATA.name: (OPENAI_METADATA, ["openai"]),
    COHERE_METADATA.name: (COHERE_METADATA, ["cohere"]),
    VOYAGE_METADATA.name: (VOYAGE_METADATA, ["voyageai"]),
    JINA_METADATA.name: (JINA_METADATA, []),
}


@dataclass
class CloudStubProvider(BaseProvider):
    provider_name: str
    metadata: ProviderMetadata
    optional_dependencies: list[str]
    config: dict[str, Any] = field(default_factory=dict)
    client: Any | None = None

    def __post_init__(self) -> None:
        # PR-3 cloud providers are contract-only stubs and must remain instantiable
        # without optional SDKs so registry discovery and health reporting stay offline.
        self._client = self.client

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            status="stub",
            detail=(
                f"{self.provider_name} is a contract-only cloud stub. "
                "Install optional dependencies and "
                "add a production adapter in a later phase."
            ),
            metrics={
                "provider": self.provider_name,
                "kind": self.metadata.kind.value,
                "required_secrets": len(self.metadata.required_secrets),
            },
        )

    def generate(self, prompt: str) -> str:
        del prompt
        raise _stub_runtime_error(provider=self.provider_name)

    def chat(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        del messages
        raise _stub_runtime_error(provider=self.provider_name)

    def embed_text(self, text: str) -> EmbeddingResult:
        del text
        raise _stub_runtime_error(provider=self.provider_name)

    def rerank(self, query: str, documents: list[str]) -> list[dict[str, Any]]:
        del query, documents
        raise _stub_runtime_error(provider=self.provider_name)


def create_cloud_stub_provider(provider_name: str, **config: Any) -> CloudStubProvider:
    metadata, dependencies = CLOUD_MODEL_METADATA[provider_name]
    return CloudStubProvider(
        provider_name=provider_name,
        metadata=metadata,
        optional_dependencies=dependencies,
        config={key: value for key, value in config.items() if key != "client"},
        client=config.get("client"),
    )


__all__ = [
    "AZURE_OPENAI_METADATA",
    "BEDROCK_METADATA",
    "CLOUD_MODEL_METADATA",
    "COHERE_METADATA",
    "CloudStubProvider",
    "JINA_METADATA",
    "OPENAI_METADATA",
    "OPENROUTER_METADATA",
    "VERTEX_AI_METADATA",
    "VOYAGE_METADATA",
    "create_cloud_stub_provider",
    "load_cloud_client",
]
