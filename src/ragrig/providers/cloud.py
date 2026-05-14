from __future__ import annotations

import os
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


ANTHROPIC_METADATA = build_cloud_model_metadata(
    name="model.anthropic",
    description="Contract-only Anthropic Claude provider stub for messages and model listing.",
    capabilities={ProviderCapability.CHAT, ProviderCapability.GENERATE, ProviderCapability.BATCH},
    required_secrets=["ANTHROPIC_API_KEY"],
    config_schema={
        "api_base_url": {"type": "string", "default": "https://api.anthropic.com/v1"},
        "model_name": {"type": "string", "default": "claude-sonnet-4-5"},
    },
    sdk_protocol="anthropic-messages-api",
    dependency_group="cloud-llm",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "managed_api"],
    default_context_window=200000,
)


GOOGLE_GEMINI_METADATA = build_cloud_model_metadata(
    name="model.google_gemini",
    description="Google Gemini API provider for Local Pilot answer smoke.",
    capabilities={
        ProviderCapability.CHAT,
        ProviderCapability.GENERATE,
        ProviderCapability.EMBEDDING,
        ProviderCapability.BATCH,
    },
    required_secrets=["GEMINI_API_KEY"],
    config_schema={
        "api_base_url": {
            "type": "string",
            "default": "https://generativelanguage.googleapis.com/v1beta",
        },
        "model_name": {"type": "string", "default": "gemini-2.5-flash"},
        "embedding_model_name": {"type": "string", "default": "text-embedding-004"},
    },
    sdk_protocol="google-genai-sdk",
    dependency_group="cloud-google",
    failure_modes=["optional_dependency_missing", "missing_required_secret", "request_failed"],
    audit_fields=["provider", "api_base_url", "model", "embedding_model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "managed_api"],
    default_dimensions=768,
    max_dimensions=3072,
    default_context_window=1048576,
)


MISTRAL_METADATA = build_cloud_model_metadata(
    name="model.mistral",
    description="Contract-only Mistral AI provider stub.",
    capabilities={
        ProviderCapability.CHAT,
        ProviderCapability.GENERATE,
        ProviderCapability.EMBEDDING,
        ProviderCapability.BATCH,
    },
    required_secrets=["MISTRAL_API_KEY"],
    config_schema={
        "api_base_url": {"type": "string", "default": "https://api.mistral.ai/v1"},
        "model_name": {"type": "string", "default": "mistral-large-latest"},
        "embedding_model_name": {"type": "string", "default": "mistral-embed"},
    },
    sdk_protocol="openai-compatible-cloud",
    dependency_group="cloud-llm",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "model", "embedding_model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "managed_api"],
    default_dimensions=1024,
    max_dimensions=4096,
    default_context_window=128000,
)


TOGETHER_METADATA = build_cloud_model_metadata(
    name="model.together",
    description="Contract-only Together AI OpenAI-compatible provider stub.",
    capabilities={
        ProviderCapability.CHAT,
        ProviderCapability.GENERATE,
        ProviderCapability.EMBEDDING,
        ProviderCapability.BATCH,
    },
    required_secrets=["TOGETHER_API_KEY"],
    config_schema={
        "api_base_url": {"type": "string", "default": "https://api.together.xyz/v1"},
        "model_name": {"type": "string", "default": "meta-llama/Llama-3.3-70B-Instruct-Turbo"},
        "embedding_model_name": {
            "type": "string",
            "default": "togethercomputer/m2-bert-80M-8k-retrieval",
        },
    },
    sdk_protocol="openai-compatible-cloud",
    dependency_group="cloud-llm",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "model", "embedding_model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "open_model_hosting"],
    default_dimensions=768,
    max_dimensions=4096,
    default_context_window=128000,
)


FIREWORKS_METADATA = build_cloud_model_metadata(
    name="model.fireworks",
    description="Contract-only Fireworks AI OpenAI-compatible provider stub.",
    capabilities={
        ProviderCapability.CHAT,
        ProviderCapability.GENERATE,
        ProviderCapability.EMBEDDING,
        ProviderCapability.BATCH,
    },
    required_secrets=["FIREWORKS_API_KEY"],
    config_schema={
        "api_base_url": {"type": "string", "default": "https://api.fireworks.ai/inference/v1"},
        "model_name": {"type": "string", "default": "accounts/fireworks/models/llama-v3p1-70b"},
    },
    sdk_protocol="openai-compatible-cloud",
    dependency_group="cloud-llm",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "open_model_hosting"],
    default_context_window=128000,
)


GROQ_METADATA = build_cloud_model_metadata(
    name="model.groq",
    description="Contract-only Groq OpenAI-compatible provider stub.",
    capabilities={ProviderCapability.CHAT, ProviderCapability.GENERATE},
    required_secrets=["GROQ_API_KEY"],
    config_schema={
        "api_base_url": {"type": "string", "default": "https://api.groq.com/openai/v1"},
        "model_name": {"type": "string", "default": "llama-3.3-70b-versatile"},
    },
    sdk_protocol="openai-compatible-cloud",
    dependency_group="cloud-llm",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "low_latency"],
    default_context_window=128000,
)


DEEPSEEK_METADATA = build_cloud_model_metadata(
    name="model.deepseek",
    description="Contract-only DeepSeek OpenAI-compatible provider stub.",
    capabilities={ProviderCapability.CHAT, ProviderCapability.GENERATE},
    required_secrets=["DEEPSEEK_API_KEY"],
    config_schema={
        "api_base_url": {"type": "string", "default": "https://api.deepseek.com/v1"},
        "model_name": {"type": "string", "default": "deepseek-chat"},
    },
    sdk_protocol="openai-compatible-cloud",
    dependency_group="cloud-llm",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "managed_api"],
    default_context_window=128000,
)


MOONSHOT_METADATA = build_cloud_model_metadata(
    name="model.moonshot",
    description="Contract-only Moonshot Kimi OpenAI-compatible provider stub.",
    capabilities={ProviderCapability.CHAT, ProviderCapability.GENERATE},
    required_secrets=["MOONSHOT_API_KEY"],
    config_schema={
        "api_base_url": {"type": "string", "default": "https://api.moonshot.ai/v1"},
        "model_name": {"type": "string", "default": "kimi-k2.5"},
    },
    sdk_protocol="openai-compatible-cloud",
    dependency_group="cloud-llm",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "managed_api"],
    default_context_window=256000,
)


MINIMAX_METADATA = build_cloud_model_metadata(
    name="model.minimax",
    description="Contract-only MiniMax OpenAI-compatible provider stub.",
    capabilities={ProviderCapability.CHAT, ProviderCapability.GENERATE},
    required_secrets=["MINIMAX_API_KEY"],
    config_schema={
        "api_base_url": {"type": "string", "default": "https://api.minimax.io/v1"},
        "model_name": {"type": "string", "default": "MiniMax-M2.7"},
    },
    sdk_protocol="openai-compatible-cloud",
    dependency_group="cloud-llm",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "managed_api"],
    default_context_window=200000,
)


DASHSCOPE_METADATA = build_cloud_model_metadata(
    name="model.dashscope",
    description="Contract-only Alibaba Cloud DashScope OpenAI-compatible provider stub.",
    capabilities={
        ProviderCapability.CHAT,
        ProviderCapability.GENERATE,
        ProviderCapability.EMBEDDING,
        ProviderCapability.BATCH,
    },
    required_secrets=["DASHSCOPE_API_KEY"],
    config_schema={
        "api_base_url": {
            "type": "string",
            "default": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        },
        "model_name": {"type": "string", "default": "qwen-plus"},
        "embedding_model_name": {"type": "string", "default": "text-embedding-v4"},
    },
    sdk_protocol="openai-compatible-cloud",
    dependency_group="cloud-llm",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "model", "embedding_model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "managed_api"],
    default_dimensions=1024,
    max_dimensions=4096,
    default_context_window=128000,
)


SILICONFLOW_METADATA = build_cloud_model_metadata(
    name="model.siliconflow",
    description="Contract-only SiliconFlow OpenAI-compatible provider stub.",
    capabilities={
        ProviderCapability.CHAT,
        ProviderCapability.GENERATE,
        ProviderCapability.EMBEDDING,
        ProviderCapability.RERANK,
    },
    required_secrets=["SILICONFLOW_API_KEY"],
    config_schema={
        "api_base_url": {"type": "string", "default": "https://api.siliconflow.cn/v1"},
        "model_name": {"type": "string", "default": "Qwen/Qwen3-235B-A22B-Instruct-2507"},
        "embedding_model_name": {"type": "string", "default": "BAAI/bge-m3"},
        "reranker_model_name": {"type": "string", "default": "BAAI/bge-reranker-v2-m3"},
    },
    sdk_protocol="openai-compatible-cloud",
    dependency_group="cloud-llm",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "model", "embedding_model", "reranker_model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "open_model_hosting"],
    default_dimensions=1024,
    max_dimensions=4096,
    default_context_window=128000,
)


ZHIPU_METADATA = build_cloud_model_metadata(
    name="model.zhipu",
    description="Contract-only Zhipu / Z.ai GLM OpenAI-compatible provider stub.",
    capabilities={ProviderCapability.CHAT, ProviderCapability.GENERATE},
    required_secrets=["ZHIPU_API_KEY"],
    config_schema={
        "api_base_url": {"type": "string", "default": "https://open.bigmodel.cn/api/paas/v4"},
        "model_name": {"type": "string", "default": "glm-4.5"},
    },
    sdk_protocol="openai-compatible-cloud",
    dependency_group="cloud-llm",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "managed_api"],
    default_context_window=128000,
)


BAIDU_QIANFAN_METADATA = build_cloud_model_metadata(
    name="model.baidu_qianfan",
    description="Contract-only Baidu Qianfan OpenAI-compatible provider stub.",
    capabilities={ProviderCapability.CHAT, ProviderCapability.GENERATE, ProviderCapability.BATCH},
    required_secrets=["QIANFAN_API_KEY"],
    config_schema={
        "api_base_url": {"type": "string", "default": "https://qianfan.baidubce.com/v2"},
        "model_name": {"type": "string", "default": "ernie-4.5-turbo"},
    },
    sdk_protocol="openai-compatible-cloud",
    dependency_group="cloud-llm",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "managed_api"],
    default_context_window=128000,
)


VOLCENGINE_ARK_METADATA = build_cloud_model_metadata(
    name="model.volcengine_ark",
    description="Contract-only Volcengine Ark OpenAI-compatible provider stub.",
    capabilities={ProviderCapability.CHAT, ProviderCapability.GENERATE, ProviderCapability.BATCH},
    required_secrets=["ARK_API_KEY"],
    config_schema={
        "api_base_url": {"type": "string", "default": "https://ark.cn-beijing.volces.com/api/v3"},
        "model_name": {"type": "string", "default": "doubao-seed-1-6"},
    },
    sdk_protocol="openai-compatible-cloud",
    dependency_group="cloud-llm",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "managed_api"],
    default_context_window=128000,
)


XAI_METADATA = build_cloud_model_metadata(
    name="model.xai",
    description="Contract-only xAI OpenAI-compatible provider stub.",
    capabilities={ProviderCapability.CHAT, ProviderCapability.GENERATE},
    required_secrets=["XAI_API_KEY"],
    config_schema={
        "api_base_url": {"type": "string", "default": "https://api.x.ai/v1"},
        "model_name": {"type": "string", "default": "grok-4"},
    },
    sdk_protocol="openai-compatible-cloud",
    dependency_group="cloud-llm",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "managed_api"],
    default_context_window=128000,
)


PERPLEXITY_METADATA = build_cloud_model_metadata(
    name="model.perplexity",
    description="Contract-only Perplexity OpenAI-compatible provider stub.",
    capabilities={ProviderCapability.CHAT, ProviderCapability.GENERATE},
    required_secrets=["PERPLEXITY_API_KEY"],
    config_schema={
        "api_base_url": {"type": "string", "default": "https://api.perplexity.ai/v1"},
        "model_name": {"type": "string", "default": "sonar-pro"},
    },
    sdk_protocol="openai-compatible-cloud",
    dependency_group="cloud-llm",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "web_grounded"],
    default_context_window=128000,
)


NVIDIA_NIM_METADATA = build_cloud_model_metadata(
    name="model.nvidia_nim",
    description="Contract-only NVIDIA NIM OpenAI-compatible provider stub.",
    capabilities={
        ProviderCapability.CHAT,
        ProviderCapability.GENERATE,
        ProviderCapability.EMBEDDING,
        ProviderCapability.BATCH,
    },
    required_secrets=["NVIDIA_API_KEY"],
    config_schema={
        "api_base_url": {"type": "string", "default": "https://integrate.api.nvidia.com/v1"},
        "model_name": {"type": "string", "default": "meta/llama-3.1-70b-instruct"},
    },
    sdk_protocol="openai-compatible-cloud",
    dependency_group="cloud-llm",
    failure_modes=["optional_dependency_missing", "provider_stub_only", "missing_required_secret"],
    audit_fields=["provider", "api_base_url", "model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["cloud_second", "nim"],
    default_context_window=128000,
)


OPENAI_COMPATIBLE_METADATA = build_cloud_model_metadata(
    name="model.openai_compatible",
    description="Generic OpenAI-compatible provider contract for custom endpoints.",
    capabilities={
        ProviderCapability.CHAT,
        ProviderCapability.GENERATE,
        ProviderCapability.EMBEDDING,
        ProviderCapability.RERANK,
    },
    required_secrets=[],
    config_schema={
        "api_base_url": {"type": "string", "default": "http://localhost:8000/v1"},
        "api_key": {"type": "string", "default": "env:OPENAI_COMPATIBLE_API_KEY"},
        "model_name": {"type": "string", "default": "local-model"},
    },
    sdk_protocol="openai-compatible",
    dependency_group="cloud-llm",
    failure_modes=["connection_failed", "provider_stub_only"],
    audit_fields=["provider", "api_base_url", "model"],
    metric_fields=["requests_total", "tokens_in", "tokens_out"],
    intended_uses=["custom_gateway", "self_hosted"],
)


class GeminiProvider(BaseProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_name: str = "gemini-2.5-flash",
        client: Any | None = None,
    ) -> None:
        self.metadata = GOOGLE_GEMINI_METADATA
        self._api_key = api_key or os.getenv("GEMINI_API_KEY")
        self._model_name = model_name
        self._client = client

    def _resolve_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ProviderError(
                "GEMINI_API_KEY is required for Gemini",
                code="missing_required_secret",
                retryable=False,
                details={"provider": "model.google_gemini", "secret": "GEMINI_API_KEY"},
            )
        try:
            from google import genai
        except Exception as exc:
            raise _optional_dependency_error(
                provider="model.google_gemini",
                dependencies=["google-genai"],
            ) from exc
        self._client = genai.Client(api_key=self._api_key)
        return self._client

    def health_check(self) -> ProviderHealth:
        try:
            self._resolve_client()
        except ProviderError as exc:
            return ProviderHealth(status="unavailable", detail=str(exc), metrics=exc.details)
        return ProviderHealth(
            status="healthy",
            detail="Gemini client is configured",
            metrics={"provider": "model.google_gemini", "model": self._model_name},
        )

    def chat(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        prompt = "\n\n".join(
            f"{message.get('role', 'user')}: {message.get('content', '')}"
            for message in messages
        )
        text = self.generate(prompt)
        return {"choices": [{"message": {"content": text}}]}

    def generate(self, prompt: str) -> str:
        response = self._resolve_client().models.generate_content(
            model=self._model_name,
            contents=prompt,
        )
        return str(getattr(response, "text", "") or "")


CLOUD_MODEL_METADATA = {
    VERTEX_AI_METADATA.name: (VERTEX_AI_METADATA, ["google-cloud-aiplatform"]),
    BEDROCK_METADATA.name: (BEDROCK_METADATA, ["boto3"]),
    AZURE_OPENAI_METADATA.name: (AZURE_OPENAI_METADATA, ["openai"]),
    ANTHROPIC_METADATA.name: (ANTHROPIC_METADATA, []),
    GOOGLE_GEMINI_METADATA.name: (GOOGLE_GEMINI_METADATA, ["google-genai"]),
    MISTRAL_METADATA.name: (MISTRAL_METADATA, []),
    OPENROUTER_METADATA.name: (OPENROUTER_METADATA, ["openai"]),
    OPENAI_METADATA.name: (OPENAI_METADATA, ["openai"]),
    COHERE_METADATA.name: (COHERE_METADATA, ["cohere"]),
    VOYAGE_METADATA.name: (VOYAGE_METADATA, ["voyageai"]),
    JINA_METADATA.name: (JINA_METADATA, []),
    TOGETHER_METADATA.name: (TOGETHER_METADATA, []),
    FIREWORKS_METADATA.name: (FIREWORKS_METADATA, []),
    GROQ_METADATA.name: (GROQ_METADATA, []),
    DEEPSEEK_METADATA.name: (DEEPSEEK_METADATA, []),
    MOONSHOT_METADATA.name: (MOONSHOT_METADATA, []),
    MINIMAX_METADATA.name: (MINIMAX_METADATA, []),
    DASHSCOPE_METADATA.name: (DASHSCOPE_METADATA, []),
    SILICONFLOW_METADATA.name: (SILICONFLOW_METADATA, []),
    ZHIPU_METADATA.name: (ZHIPU_METADATA, []),
    BAIDU_QIANFAN_METADATA.name: (BAIDU_QIANFAN_METADATA, []),
    VOLCENGINE_ARK_METADATA.name: (VOLCENGINE_ARK_METADATA, []),
    XAI_METADATA.name: (XAI_METADATA, []),
    PERPLEXITY_METADATA.name: (PERPLEXITY_METADATA, []),
    NVIDIA_NIM_METADATA.name: (NVIDIA_NIM_METADATA, []),
    OPENAI_COMPATIBLE_METADATA.name: (OPENAI_COMPATIBLE_METADATA, []),
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
    "ANTHROPIC_METADATA",
    "AZURE_OPENAI_METADATA",
    "BAIDU_QIANFAN_METADATA",
    "BEDROCK_METADATA",
    "CLOUD_MODEL_METADATA",
    "COHERE_METADATA",
    "DASHSCOPE_METADATA",
    "CloudStubProvider",
    "DEEPSEEK_METADATA",
    "FIREWORKS_METADATA",
    "GeminiProvider",
    "GOOGLE_GEMINI_METADATA",
    "GROQ_METADATA",
    "JINA_METADATA",
    "MINIMAX_METADATA",
    "MISTRAL_METADATA",
    "MOONSHOT_METADATA",
    "NVIDIA_NIM_METADATA",
    "OPENAI_METADATA",
    "OPENAI_COMPATIBLE_METADATA",
    "OPENROUTER_METADATA",
    "PERPLEXITY_METADATA",
    "SILICONFLOW_METADATA",
    "TOGETHER_METADATA",
    "VERTEX_AI_METADATA",
    "VOYAGE_METADATA",
    "VOLCENGINE_ARK_METADATA",
    "XAI_METADATA",
    "ZHIPU_METADATA",
    "create_cloud_stub_provider",
    "load_cloud_client",
]
