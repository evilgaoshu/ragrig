from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable

from ragrig.embeddings import DeterministicEmbeddingProvider, EmbeddingResult


class ProviderCapability(StrEnum):
    CHAT = "chat"
    GENERATE = "generate"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    STREAMING = "streaming"
    BATCH = "batch"


class ProviderKind(StrEnum):
    LOCAL = "local"
    CLOUD = "cloud"


@dataclass(frozen=True)
class ProviderRetryPolicy:
    max_attempts: int
    backoff_seconds: float


@dataclass(frozen=True)
class ProviderHealth:
    status: str
    detail: str
    metrics: dict[str, Any] = field(default_factory=dict)


class ProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        retryable: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.details = details or {}


@dataclass(frozen=True)
class ProviderMetadata:
    name: str
    kind: ProviderKind
    description: str
    capabilities: set[ProviderCapability]
    default_dimensions: int | None
    max_dimensions: int | None
    default_context_window: int | None
    max_context_window: int | None
    required_secrets: list[str]
    config_schema: dict[str, Any]
    sdk_protocol: str
    healthcheck: str
    failure_modes: list[str]
    retry_policy: ProviderRetryPolicy
    audit_fields: list[str]
    metric_fields: list[str]
    intended_uses: list[str]


class BaseProvider:
    metadata: ProviderMetadata

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(status="unknown", detail="Health check not implemented")

    def embed_text(self, text: str) -> EmbeddingResult:
        del text
        self.raise_unsupported_capability(ProviderCapability.EMBEDDING)

    def generate(self, prompt: str) -> str:
        del prompt
        self.raise_unsupported_capability(ProviderCapability.GENERATE)

    def chat(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        del messages
        self.raise_unsupported_capability(ProviderCapability.CHAT)

    def rerank(self, query: str, documents: list[str]) -> list[dict[str, Any]]:
        del query, documents
        self.raise_unsupported_capability(ProviderCapability.RERANK)

    def raise_unsupported_capability(self, capability: ProviderCapability) -> None:
        raise ProviderError(
            f"Provider '{self.metadata.name}' does not support capability '{capability.value}'",
            code="unsupported_capability",
            retryable=False,
            details={"provider": self.metadata.name, "capability": capability.value},
        )


ProviderFactory = Callable[..., BaseProvider]


class ProviderRegistry:
    def __init__(self) -> None:
        self._metadata: dict[str, ProviderMetadata] = {}
        self._factories: dict[str, ProviderFactory] = {}

    def register(self, metadata: ProviderMetadata, factory: ProviderFactory) -> None:
        self._metadata[metadata.name] = metadata
        self._factories[metadata.name] = factory

    def get(self, name: str, **config: Any) -> BaseProvider:
        factory = self._factories.get(name)
        if factory is None:
            raise ProviderError(
                f"Provider '{name}' is not registered",
                code="provider_not_registered",
                retryable=False,
                details={"provider": name},
            )
        return factory(**config)

    def read(self, name: str) -> ProviderMetadata:
        metadata = self._metadata.get(name)
        if metadata is None:
            raise ProviderError(
                f"Provider '{name}' is not registered",
                code="provider_not_registered",
                retryable=False,
                details={"provider": name},
            )
        return metadata

    def list(self) -> list[ProviderMetadata]:
        return [self._metadata[name] for name in sorted(self._metadata)]

    def health_check_all(
        self, provider_configs: dict[str, dict[str, Any]] | None = None
    ) -> dict[str, ProviderHealth]:
        configs = provider_configs or {}
        return {
            name: self.get(name, **configs.get(name, {})).health_check()
            for name in sorted(self._metadata)
        }


@dataclass
class DeterministicLocalProvider(BaseProvider):
    dimensions: int = 8

    def __post_init__(self) -> None:
        self._provider = DeterministicEmbeddingProvider(dimensions=self.dimensions)
        self.metadata = DETERMINISTIC_LOCAL_METADATA

    def embed_text(self, text: str) -> EmbeddingResult:
        return self._provider.embed_text(text)

    def health_check(self) -> ProviderHealth:
        sample = self._provider.embed_text("registry-health")
        return ProviderHealth(
            status="healthy",
            detail="Deterministic local embedding provider is ready for CI/smoke use",
            metrics={"dimensions": sample.dimensions},
        )


DETERMINISTIC_LOCAL_METADATA = ProviderMetadata(
    name="deterministic-local",
    kind=ProviderKind.LOCAL,
    description="Deterministic local embedding provider for CI and smoke validation.",
    capabilities={ProviderCapability.EMBEDDING, ProviderCapability.BATCH},
    default_dimensions=8,
    max_dimensions=None,
    default_context_window=None,
    max_context_window=None,
    required_secrets=[],
    config_schema={
        "dimensions": {
            "type": "integer",
            "minimum": 1,
            "default": 8,
            "description": "Output dimensions for the deterministic hash embedding.",
        }
    },
    sdk_protocol="in-process",
    healthcheck="Instantiate the provider and embed a deterministic probe string.",
    failure_modes=["invalid_dimensions"],
    retry_policy=ProviderRetryPolicy(max_attempts=1, backoff_seconds=0.0),
    audit_fields=["provider", "model", "dimensions", "text_hash"],
    metric_fields=["dimensions", "requests_total"],
    intended_uses=["ci", "smoke"],
)


_provider_registry: ProviderRegistry | None = None


def create_provider_registry() -> ProviderRegistry:
    from ragrig.providers.bge import (
        BGE_EMBEDDING_METADATA,
        BGE_RERANKER_METADATA,
        create_bge_embedding_provider,
        create_bge_reranker_provider,
    )
    from ragrig.providers.cloud import (
        ANTHROPIC_METADATA,
        AZURE_OPENAI_METADATA,
        BAIDU_QIANFAN_METADATA,
        BEDROCK_METADATA,
        COHERE_METADATA,
        DASHSCOPE_METADATA,
        DEEPSEEK_METADATA,
        FIREWORKS_METADATA,
        GOOGLE_GEMINI_METADATA,
        GROQ_METADATA,
        JINA_METADATA,
        MINIMAX_METADATA,
        MISTRAL_METADATA,
        MOONSHOT_METADATA,
        NVIDIA_NIM_METADATA,
        OPENAI_COMPATIBLE_METADATA,
        OPENAI_METADATA,
        OPENROUTER_METADATA,
        PERPLEXITY_METADATA,
        SILICONFLOW_METADATA,
        TOGETHER_METADATA,
        VERTEX_AI_METADATA,
        VOLCENGINE_ARK_METADATA,
        VOYAGE_METADATA,
        XAI_METADATA,
        ZHIPU_METADATA,
        GeminiProvider,
        create_anthropic_provider,
        create_azure_openai_provider,
        create_cloud_stub_provider,
        create_cohere_provider,
        create_jina_provider,
        create_openai_compatible_cloud_provider,
        create_voyage_provider,
    )
    from ragrig.providers.local import (
        LLAMA_CPP_METADATA,
        LM_STUDIO_METADATA,
        LOCALAI_METADATA,
        OLLAMA_METADATA,
        VLLM_METADATA,
        XINFERENCE_METADATA,
        create_ollama_provider,
        create_openai_compatible_provider,
    )

    # Providers that share the generic OpenAI-compatible cloud implementation:
    # each entry is (metadata, api_key_env_var)
    _OAI_COMPAT_CLOUD: list[tuple[object, str]] = [
        (OPENAI_METADATA, "OPENAI_API_KEY"),
        (OPENROUTER_METADATA, "OPENROUTER_API_KEY"),
        (MISTRAL_METADATA, "MISTRAL_API_KEY"),
        (TOGETHER_METADATA, "TOGETHER_API_KEY"),
        (FIREWORKS_METADATA, "FIREWORKS_API_KEY"),
        (GROQ_METADATA, "GROQ_API_KEY"),
        (DEEPSEEK_METADATA, "DEEPSEEK_API_KEY"),
        (MOONSHOT_METADATA, "MOONSHOT_API_KEY"),
        (MINIMAX_METADATA, "MINIMAX_API_KEY"),
        (DASHSCOPE_METADATA, "DASHSCOPE_API_KEY"),
        (SILICONFLOW_METADATA, "SILICONFLOW_API_KEY"),
        (ZHIPU_METADATA, "ZHIPU_API_KEY"),
        (BAIDU_QIANFAN_METADATA, "QIANFAN_API_KEY"),
        (VOLCENGINE_ARK_METADATA, "ARK_API_KEY"),
        (XAI_METADATA, "XAI_API_KEY"),
        (PERPLEXITY_METADATA, "PERPLEXITY_API_KEY"),
        (NVIDIA_NIM_METADATA, "NVIDIA_API_KEY"),
        (OPENAI_COMPATIBLE_METADATA, "OPENAI_COMPATIBLE_API_KEY"),
    ]

    registry = ProviderRegistry()
    registry.register(
        DETERMINISTIC_LOCAL_METADATA,
        lambda **config: DeterministicLocalProvider(dimensions=int(config.get("dimensions", 8))),
    )
    registry.register(OLLAMA_METADATA, create_ollama_provider)
    registry.register(
        LM_STUDIO_METADATA,
        lambda **config: create_openai_compatible_provider("model.lm_studio", **config),
    )
    registry.register(
        LLAMA_CPP_METADATA,
        lambda **config: create_openai_compatible_provider("model.llama_cpp", **config),
    )
    registry.register(
        VLLM_METADATA,
        lambda **config: create_openai_compatible_provider("model.vllm", **config),
    )
    registry.register(
        XINFERENCE_METADATA,
        lambda **config: create_openai_compatible_provider("model.xinference", **config),
    )
    registry.register(
        LOCALAI_METADATA,
        lambda **config: create_openai_compatible_provider("model.localai", **config),
    )
    registry.register(BGE_EMBEDDING_METADATA, create_bge_embedding_provider)
    registry.register(BGE_RERANKER_METADATA, create_bge_reranker_provider)

    # Cloud stubs (complex auth — Bedrock/Vertex AI kept as stubs)
    registry.register(
        VERTEX_AI_METADATA,
        lambda **config: create_cloud_stub_provider("model.vertex_ai", **config),
    )
    registry.register(
        BEDROCK_METADATA,
        lambda **config: create_cloud_stub_provider("model.bedrock", **config),
    )

    # Real cloud providers
    registry.register(ANTHROPIC_METADATA, create_anthropic_provider)
    registry.register(AZURE_OPENAI_METADATA, create_azure_openai_provider)
    registry.register(COHERE_METADATA, create_cohere_provider)
    registry.register(JINA_METADATA, create_jina_provider)
    registry.register(VOYAGE_METADATA, create_voyage_provider)
    registry.register(
        GOOGLE_GEMINI_METADATA,
        lambda **config: GeminiProvider(
            api_key=config.get("api_key"),
            model_name=config.get("model_name", "gemini-2.5-flash"),
            client=config.get("client"),
        ),
    )

    # All OpenAI-compatible cloud providers via the generic factory
    for _meta, _env in _OAI_COMPAT_CLOUD:

        def _make_factory(meta: object = _meta, env: str = _env):
            return lambda **config: create_openai_compatible_cloud_provider(
                meta.name,
                meta,
                env,
                **config,  # type: ignore[attr-defined]
            )

        registry.register(_meta, _make_factory())  # type: ignore[arg-type]

    return registry


def get_provider_registry() -> ProviderRegistry:
    global _provider_registry
    if _provider_registry is None:
        _provider_registry = create_provider_registry()
    return _provider_registry


__all__ = [
    "BaseProvider",
    "DETERMINISTIC_LOCAL_METADATA",
    "DeterministicLocalProvider",
    "ProviderCapability",
    "ProviderError",
    "ProviderFactory",
    "ProviderHealth",
    "ProviderKind",
    "ProviderMetadata",
    "ProviderRegistry",
    "ProviderRetryPolicy",
    "create_provider_registry",
    "get_provider_registry",
]
