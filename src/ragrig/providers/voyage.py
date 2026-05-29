"""Voyage AI embedding provider for RAGRig.

Uses the Voyage AI Embeddings API:
  POST https://api.voyageai.com/v1/embeddings
  Authorization: Bearer {api_key}

Supported models: voyage-3, voyage-3-lite, voyage-code-3, voyage-finance-2
Output dimension: 1024 (voyage-3)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx

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

VOYAGE_EMBEDDING_METADATA = ProviderMetadata(
    name="embedding.voyage",
    kind=ProviderKind.CLOUD,
    description="Voyage AI cloud embedding provider via the Embeddings API.",
    capabilities={ProviderCapability.EMBEDDING, ProviderCapability.BATCH},
    default_dimensions=1024,
    max_dimensions=1024,
    default_context_window=None,
    max_context_window=None,
    required_secrets=["VOYAGE_API_KEY"],
    config_schema={
        "model_name": {
            "type": "string",
            "default": "voyage-3",
            "description": "Voyage AI embedding model name.",
        },
        "input_type": {
            "type": "string",
            "default": "document",
            "description": "Voyage AI input_type parameter (document / query).",
        },
    },
    sdk_protocol="voyage-embeddings-http",
    healthcheck="Validate VOYAGE_API_KEY is present without performing a live request.",
    failure_modes=["missing_required_secret", "request_failed", "api_error"],
    retry_policy=ProviderRetryPolicy(max_attempts=3, backoff_seconds=1.0),
    audit_fields=["provider", "model", "dimensions"],
    metric_fields=["requests_total", "dimensions"],
    intended_uses=["cloud_second", "managed_api"],
)

_SUPPORTED_MODELS = frozenset({"voyage-3", "voyage-3-lite", "voyage-code-3", "voyage-finance-2"})

_VOYAGE_EMBED_URL = "https://api.voyageai.com/v1/embeddings"


@dataclass
class VoyageEmbeddingProvider(BaseProvider):
    """Voyage AI cloud embedding provider."""

    model_name: str = "voyage-3"
    input_type: str = "document"
    metadata: ProviderMetadata = field(
        default_factory=lambda: VOYAGE_EMBEDDING_METADATA, init=False
    )
    _config: dict[str, Any] = field(default_factory=dict, repr=False)
    _client: httpx.Client | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.metadata = VOYAGE_EMBEDDING_METADATA

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _api_key(self) -> str:
        key = self._config.get("api_key") or os.getenv("VOYAGE_API_KEY")
        if not key:
            raise ProviderError(
                "Provider 'embedding.voyage' requires VOYAGE_API_KEY "
                "(set via env var or api_key config field)",
                code="missing_required_secret",
                retryable=False,
                details={"provider": "embedding.voyage", "secret": "VOYAGE_API_KEY"},
            )
        return str(key)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key()}",
            "Content-Type": "application/json",
        }

    def _http(self) -> httpx.Client:
        return self._client or httpx.Client(timeout=60.0)

    # ------------------------------------------------------------------
    # BaseProvider interface
    # ------------------------------------------------------------------

    def health_check(self) -> ProviderHealth:
        key = self._config.get("api_key") or os.getenv("VOYAGE_API_KEY")
        if not key:
            return ProviderHealth(
                status="unavailable",
                detail="VOYAGE_API_KEY is not configured",
                metrics={"provider": "embedding.voyage"},
            )
        return ProviderHealth(
            status="healthy",
            detail="Voyage AI API key is configured",
            metrics={"provider": "embedding.voyage", "model": self.model_name},
        )

    def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        if not texts:
            return []

        body: dict[str, Any] = {
            "model": self.model_name,
            "input": list(texts),
        }
        if self.input_type:
            body["input_type"] = self.input_type

        try:
            client = self._http()
            owned = self._client is None
            try:
                response = client.post(_VOYAGE_EMBED_URL, headers=self._headers(), json=body)
            finally:
                if owned:
                    client.close()
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Provider 'embedding.voyage' HTTP request failed: {exc}",
                code="request_failed",
                retryable=True,
                details={"provider": "embedding.voyage", "error": str(exc)},
            ) from exc

        if not response.is_success:
            try:
                err_body = response.json()
            except Exception:
                err_body = {"raw": response.text}
            msg = err_body.get("message", err_body.get("detail", response.text))
            raise ProviderError(
                f"Provider 'embedding.voyage' returned HTTP {response.status_code}: {msg}",
                code="api_error",
                retryable=response.status_code >= 500,
                details={"provider": "embedding.voyage", "status": response.status_code},
            )

        data = response.json()
        try:
            items = list(data["data"])
            if all(isinstance(item, dict) and "index" in item for item in items):
                items = sorted(items, key=lambda item: int(item["index"]))
            vectors = [[float(v) for v in item["embedding"]] for item in items]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError(
                f"Provider 'embedding.voyage' returned unexpected response shape: {exc}",
                code="api_error",
                retryable=False,
                details={"provider": "embedding.voyage"},
            ) from exc

        if len(vectors) != len(texts):
            raise ProviderError(
                "Provider 'embedding.voyage' returned "
                f"{len(vectors)} embeddings for {len(texts)} inputs",
                code="api_error",
                retryable=False,
                details={"provider": "embedding.voyage"},
            )

        return [
            EmbeddingResult(
                provider="embedding.voyage",
                model=self.model_name,
                dimensions=len(vector),
                vector=vector,
                metadata={"input_type": self.input_type},
            )
            for vector in vectors
        ]

    def embed_text(self, text: str) -> EmbeddingResult:
        return self.embed_texts([text])[0]


def create_voyage_embedding_provider(**config: Any) -> VoyageEmbeddingProvider:
    schema = VOYAGE_EMBEDDING_METADATA.config_schema
    provider = VoyageEmbeddingProvider(
        model_name=str(config.get("model_name", schema["model_name"]["default"])),
        input_type=str(config.get("input_type", schema["input_type"]["default"])),
    )
    provider._config = dict(config)
    provider._client = config.get("client")
    return provider


__all__ = [
    "VOYAGE_EMBEDDING_METADATA",
    "VoyageEmbeddingProvider",
    "create_voyage_embedding_provider",
]
