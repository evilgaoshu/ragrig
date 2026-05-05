from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ragrig.embeddings import EmbeddingResult
from ragrig.providers import (
    BaseProvider,
    ProviderCapability,
    ProviderError,
    ProviderKind,
    ProviderMetadata,
    ProviderRetryPolicy,
)


def _optional_dependency_error(provider: str) -> ProviderError:
    return ProviderError(
        f"{provider} requires optional local ML dependencies",
        code="optional_dependency_missing",
        retryable=False,
        details={
            "provider": provider,
            "dependencies": ["FlagEmbedding", "sentence-transformers", "torch"],
        },
    )


def load_bge_embedding_runtime(model_name: str) -> Any:
    del model_name
    raise _optional_dependency_error("embedding.bge")


def load_bge_reranker_runtime(model_name: str) -> Any:
    del model_name
    raise _optional_dependency_error("reranker.bge")


BGE_EMBEDDING_METADATA = ProviderMetadata(
    name="embedding.bge",
    kind=ProviderKind.LOCAL,
    description="Optional local BGE embedding provider.",
    capabilities={ProviderCapability.EMBEDDING, ProviderCapability.BATCH},
    default_dimensions=None,
    max_dimensions=None,
    default_context_window=None,
    max_context_window=None,
    required_secrets=[],
    config_schema={
        "model_name": {
            "type": "string",
            "default": "BAAI/bge-small-en-v1.5",
            "description": "BGE embedding model name.",
        }
    },
    sdk_protocol="optional-local-ml",
    healthcheck="Instantiate the optional embedding runtime and encode a probe string.",
    failure_modes=["optional_dependency_missing", "model_load_failed"],
    retry_policy=ProviderRetryPolicy(max_attempts=1, backoff_seconds=0.0),
    audit_fields=["provider", "model", "dimensions"],
    metric_fields=["dimensions", "requests_total"],
    intended_uses=["local_development", "self_hosted"],
)


BGE_RERANKER_METADATA = ProviderMetadata(
    name="reranker.bge",
    kind=ProviderKind.LOCAL,
    description="Optional local BGE reranker provider.",
    capabilities={ProviderCapability.RERANK},
    default_dimensions=None,
    max_dimensions=None,
    default_context_window=None,
    max_context_window=None,
    required_secrets=[],
    config_schema={
        "model_name": {
            "type": "string",
            "default": "BAAI/bge-reranker-base",
            "description": "BGE reranker model name.",
        }
    },
    sdk_protocol="optional-local-ml",
    healthcheck="Instantiate the optional reranker runtime and score a probe query/document pair.",
    failure_modes=["optional_dependency_missing", "model_load_failed"],
    retry_policy=ProviderRetryPolicy(max_attempts=1, backoff_seconds=0.0),
    audit_fields=["provider", "model", "document_count"],
    metric_fields=["requests_total", "document_count"],
    intended_uses=["local_development", "self_hosted"],
)


@dataclass
class BgeEmbeddingProvider(BaseProvider):
    model_name: str = "BAAI/bge-small-en-v1.5"
    runtime: Any | None = None
    metadata: ProviderMetadata = field(default=BGE_EMBEDDING_METADATA, init=False)

    def __post_init__(self) -> None:
        self._runtime = self.runtime

    def embed_text(self, text: str) -> EmbeddingResult:
        runtime = self._runtime or load_bge_embedding_runtime(self.model_name)
        vector = [float(value) for value in runtime.encode(text)]
        return EmbeddingResult(
            provider=self.metadata.name,
            model=self.model_name,
            dimensions=len(vector),
            vector=vector,
            metadata={},
        )


@dataclass
class BgeRerankerProvider(BaseProvider):
    model_name: str = "BAAI/bge-reranker-base"
    runtime: Any | None = None
    metadata: ProviderMetadata = field(default=BGE_RERANKER_METADATA, init=False)

    def __post_init__(self) -> None:
        self._runtime = self.runtime

    def rerank(self, query: str, documents: list[str]) -> list[dict[str, Any]]:
        runtime = self._runtime or load_bge_reranker_runtime(self.model_name)
        scores = [float(value) for value in runtime.rerank(query, documents)]
        return [
            {"document": document, "index": index, "score": score}
            for index, (document, score) in enumerate(zip(documents, scores, strict=False))
        ]


def create_bge_embedding_provider(**config: Any) -> BgeEmbeddingProvider:
    return BgeEmbeddingProvider(
        model_name=str(config.get("model_name", "BAAI/bge-small-en-v1.5")),
        runtime=config.get("runtime"),
    )


def create_bge_reranker_provider(**config: Any) -> BgeRerankerProvider:
    return BgeRerankerProvider(
        model_name=str(config.get("model_name", "BAAI/bge-reranker-base")),
        runtime=config.get("runtime"),
    )


__all__ = [
    "BGE_EMBEDDING_METADATA",
    "BGE_RERANKER_METADATA",
    "BgeEmbeddingProvider",
    "BgeRerankerProvider",
    "create_bge_embedding_provider",
    "create_bge_reranker_provider",
    "load_bge_embedding_runtime",
    "load_bge_reranker_runtime",
]
