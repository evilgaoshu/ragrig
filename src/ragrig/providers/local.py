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


def _missing_optional_dependency_error(*, provider: str, dependencies: list[str]) -> ProviderError:
    return ProviderError(
        f"Provider '{provider}' requires optional dependencies: {', '.join(dependencies)}",
        code="optional_dependency_missing",
        retryable=False,
        details={"provider": provider, "dependencies": dependencies},
    )


def load_ollama_client() -> Any:
    raise _missing_optional_dependency_error(provider="model.ollama", dependencies=["ollama"])


def load_openai_compatible_client(*, provider: str) -> Any:
    raise _missing_optional_dependency_error(provider=provider, dependencies=["openai"])


def build_local_model_metadata(
    *,
    name: str,
    description: str,
    capabilities: set[ProviderCapability],
    config_schema: dict[str, Any],
    sdk_protocol: str,
    healthcheck: str,
    failure_modes: list[str],
    audit_fields: list[str],
    metric_fields: list[str],
    intended_uses: list[str],
    default_context_window: int | None = None,
    max_context_window: int | None = None,
) -> ProviderMetadata:
    return ProviderMetadata(
        name=name,
        kind=ProviderKind.LOCAL,
        description=description,
        capabilities=capabilities,
        default_dimensions=None,
        max_dimensions=None,
        default_context_window=default_context_window,
        max_context_window=max_context_window,
        required_secrets=[],
        config_schema=config_schema,
        sdk_protocol=sdk_protocol,
        healthcheck=healthcheck,
        failure_modes=failure_modes,
        retry_policy=ProviderRetryPolicy(max_attempts=2, backoff_seconds=0.5),
        audit_fields=audit_fields,
        metric_fields=metric_fields,
        intended_uses=intended_uses,
    )


OLLAMA_METADATA = build_local_model_metadata(
    name="model.ollama",
    description="Local Ollama runtime adapter for chat, generate, and optional embeddings.",
    capabilities={
        ProviderCapability.CHAT,
        ProviderCapability.GENERATE,
        ProviderCapability.EMBEDDING,
    },
    config_schema={
        "host": {
            "type": "string",
            "default": "http://localhost:11434",
            "description": "Base URL for the local Ollama server.",
        },
        "model_name": {
            "type": "string",
            "description": "Primary Ollama generation model.",
        },
        "embedding_model_name": {
            "type": "string",
            "description": "Optional Ollama embedding model override.",
        },
    },
    sdk_protocol="optional-ollama-sdk",
    healthcheck="List local models from Ollama and confirm the configured model is visible.",
    failure_modes=["model_not_available", "embedding_not_supported", "connection_failed"],
    audit_fields=["provider", "host", "model", "embedding_model"],
    metric_fields=["model_count", "requests_total"],
    intended_uses=["local_development", "self_hosted"],
    default_context_window=8192,
)


LM_STUDIO_METADATA = build_local_model_metadata(
    name="model.lm_studio",
    description="LM Studio local OpenAI-compatible runtime adapter.",
    capabilities={ProviderCapability.CHAT, ProviderCapability.GENERATE},
    config_schema={
        "base_url": {
            "type": "string",
            "default": "http://localhost:1234/v1",
            "description": "LM Studio OpenAI-compatible local API base URL.",
        },
        "model_name": {
            "type": "string",
            "description": "Configured LM Studio model name.",
        },
    },
    sdk_protocol="openai-compatible-local",
    healthcheck="List local models from the configured OpenAI-compatible endpoint.",
    failure_modes=["model_not_available", "connection_failed"],
    audit_fields=["provider", "base_url", "model"],
    metric_fields=["model_count", "requests_total"],
    intended_uses=["local_development", "desktop_inference"],
    default_context_window=8192,
)


LLAMA_CPP_METADATA = build_local_model_metadata(
    name="model.llama_cpp",
    description="llama.cpp server local OpenAI-compatible runtime adapter.",
    capabilities={ProviderCapability.CHAT, ProviderCapability.GENERATE},
    config_schema={
        "base_url": {
            "type": "string",
            "default": "http://localhost:8080/v1",
            "description": "llama.cpp server OpenAI-compatible base URL.",
        },
        "model_name": {"type": "string", "description": "Configured llama.cpp model name."},
    },
    sdk_protocol="openai-compatible-local",
    healthcheck="List local models from the configured OpenAI-compatible endpoint.",
    failure_modes=["model_not_available", "connection_failed"],
    audit_fields=["provider", "base_url", "model"],
    metric_fields=["model_count", "requests_total"],
    intended_uses=["local_development", "edge_inference"],
    default_context_window=4096,
)


VLLM_METADATA = build_local_model_metadata(
    name="model.vllm",
    description="vLLM local OpenAI-compatible runtime adapter.",
    capabilities={ProviderCapability.CHAT, ProviderCapability.GENERATE, ProviderCapability.BATCH},
    config_schema={
        "base_url": {
            "type": "string",
            "default": "http://localhost:8000/v1",
            "description": "vLLM OpenAI-compatible base URL.",
        },
        "model_name": {"type": "string", "description": "Configured vLLM model name."},
    },
    sdk_protocol="openai-compatible-local",
    healthcheck="List local models from the configured OpenAI-compatible endpoint.",
    failure_modes=["model_not_available", "connection_failed"],
    audit_fields=["provider", "base_url", "model"],
    metric_fields=["model_count", "requests_total"],
    intended_uses=["local_development", "gpu_self_hosted"],
    default_context_window=8192,
)


XINFERENCE_METADATA = build_local_model_metadata(
    name="model.xinference",
    description="Xinference local OpenAI-compatible runtime adapter.",
    capabilities={ProviderCapability.CHAT, ProviderCapability.GENERATE},
    config_schema={
        "base_url": {
            "type": "string",
            "default": "http://localhost:9997/v1",
            "description": "Xinference OpenAI-compatible base URL.",
        },
        "model_name": {"type": "string", "description": "Configured Xinference model name."},
    },
    sdk_protocol="openai-compatible-local",
    healthcheck="List local models from the configured OpenAI-compatible endpoint.",
    failure_modes=["model_not_available", "connection_failed"],
    audit_fields=["provider", "base_url", "model"],
    metric_fields=["model_count", "requests_total"],
    intended_uses=["local_development", "self_hosted"],
    default_context_window=8192,
)


LOCALAI_METADATA = build_local_model_metadata(
    name="model.localai",
    description="LocalAI local OpenAI-compatible runtime adapter.",
    capabilities={ProviderCapability.CHAT, ProviderCapability.GENERATE},
    config_schema={
        "base_url": {
            "type": "string",
            "default": "http://localhost:8080/v1",
            "description": "LocalAI OpenAI-compatible base URL.",
        },
        "model_name": {"type": "string", "description": "Configured LocalAI model name."},
    },
    sdk_protocol="openai-compatible-local",
    healthcheck="List local models from the configured OpenAI-compatible endpoint.",
    failure_modes=["model_not_available", "connection_failed"],
    audit_fields=["provider", "base_url", "model"],
    metric_fields=["model_count", "requests_total"],
    intended_uses=["local_development", "cpu_self_hosted"],
    default_context_window=8192,
)


@dataclass
class OllamaProvider(BaseProvider):
    host: str = "http://localhost:11434"
    model_name: str = "llama3.2"
    embedding_model_name: str | None = None
    client: Any | None = None
    metadata: ProviderMetadata = field(default=OLLAMA_METADATA, init=False)

    def __post_init__(self) -> None:
        self._client = self.client or load_ollama_client()

    def list_models(self) -> list[dict[str, Any]]:
        return list(self._client.list_models())

    def health_check(self) -> ProviderHealth:
        models = self.list_models()
        return ProviderHealth(
            status="healthy",
            detail="Ollama local runtime is reachable",
            metrics={
                "host": self.host,
                "model_count": len(models),
                "embedding_model": self.embedding_model_name or self.model_name,
            },
        )

    def generate(self, prompt: str) -> str:
        response = self._client.generate(model=self.model_name, prompt=prompt)
        return str(response["response"])

    def chat(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        response = self._client.chat(model=self.model_name, messages=messages)
        return dict(response)

    def embed_text(self, text: str) -> EmbeddingResult:
        target_model = self.embedding_model_name or self.model_name
        models = self.list_models()
        supported = any(
            item["name"] == target_model and bool(item.get("supports_embeddings", False))
            for item in models
        )
        if not supported:
            raise ProviderError(
                "Provider "
                f"'{self.metadata.name}' does not support embeddings for model '{target_model}'",
                code="embedding_not_supported",
                retryable=False,
                details={"provider": self.metadata.name, "model": target_model},
            )
        response = self._client.embed(model=target_model, text=text)
        vector = [float(value) for value in response["embedding"]]
        return EmbeddingResult(
            provider=self.metadata.name,
            model=target_model,
            dimensions=len(vector),
            vector=vector,
            metadata={"host": self.host},
        )


@dataclass
class OpenAICompatibleLocalProvider(BaseProvider):
    provider_name: str
    metadata: ProviderMetadata
    base_url: str
    model_name: str
    client: Any | None = None

    def __post_init__(self) -> None:
        self._client = self.client or load_openai_compatible_client(provider=self.provider_name)

    def list_models(self) -> list[str]:
        return list(self._client.list_models())

    def health_check(self) -> ProviderHealth:
        models = self.list_models()
        return ProviderHealth(
            status="healthy",
            detail=f"{self.provider_name} endpoint is reachable",
            metrics={"base_url": self.base_url, "model_count": len(models)},
        )

    def generate(self, prompt: str) -> str:
        return str(
            self._client.generate(base_url=self.base_url, model=self.model_name, prompt=prompt)
        )

    def chat(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        response = self._client.chat(
            base_url=self.base_url,
            model=self.model_name,
            messages=messages,
        )
        return dict(response)


LOCAL_MODEL_METADATA = {
    OLLAMA_METADATA.name: OLLAMA_METADATA,
    LM_STUDIO_METADATA.name: LM_STUDIO_METADATA,
    LLAMA_CPP_METADATA.name: LLAMA_CPP_METADATA,
    VLLM_METADATA.name: VLLM_METADATA,
    XINFERENCE_METADATA.name: XINFERENCE_METADATA,
    LOCALAI_METADATA.name: LOCALAI_METADATA,
}


def create_ollama_provider(**config: Any) -> OllamaProvider:
    return OllamaProvider(
        host=str(config.get("host", "http://localhost:11434")),
        model_name=str(config.get("model_name", "llama3.2")),
        embedding_model_name=(
            str(config["embedding_model_name"]) if config.get("embedding_model_name") else None
        ),
        client=config.get("client"),
    )


def create_openai_compatible_provider(
    provider_name: str, **config: Any
) -> OpenAICompatibleLocalProvider:
    metadata = LOCAL_MODEL_METADATA[provider_name]
    base_url = str(metadata.config_schema["base_url"]["default"])
    return OpenAICompatibleLocalProvider(
        provider_name=provider_name,
        metadata=metadata,
        base_url=str(config.get("base_url", base_url)),
        model_name=str(config.get("model_name", "local-model")),
        client=config.get("client"),
    )


__all__ = [
    "LLAMA_CPP_METADATA",
    "LM_STUDIO_METADATA",
    "LOCALAI_METADATA",
    "LOCAL_MODEL_METADATA",
    "OLLAMA_METADATA",
    "OpenAICompatibleLocalProvider",
    "OllamaProvider",
    "VLLM_METADATA",
    "XINFERENCE_METADATA",
    "create_ollama_provider",
    "create_openai_compatible_provider",
]
