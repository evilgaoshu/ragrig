"""Cohere embedding provider for RAGRig.

Uses the Cohere Embed API v2:
  POST https://api.cohere.com/v2/embed
  Authorization: Bearer {api_key}

Supported models: embed-v4.0, embed-english-v3.0, embed-multilingual-v3.0
Output dimension: 1024
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

COHERE_EMBEDDING_METADATA = ProviderMetadata(
    name="embedding.cohere",
    kind=ProviderKind.CLOUD,
    description="Cohere cloud embedding provider via the Embed API v2.",
    capabilities={ProviderCapability.EMBEDDING, ProviderCapability.BATCH},
    default_dimensions=1024,
    max_dimensions=1024,
    default_context_window=None,
    max_context_window=None,
    required_secrets=["COHERE_API_KEY"],
    config_schema={
        "model_name": {
            "type": "string",
            "default": "embed-v4.0",
            "description": "Cohere embedding model name.",
        },
        "input_type": {
            "type": "string",
            "default": "search_document",
            "description": "Cohere input_type parameter (search_document / search_query / etc.).",
        },
    },
    sdk_protocol="cohere-embed-v2-http",
    healthcheck="Validate COHERE_API_KEY is present without performing a live request.",
    failure_modes=["missing_required_secret", "request_failed", "api_error"],
    retry_policy=ProviderRetryPolicy(max_attempts=3, backoff_seconds=1.0),
    audit_fields=["provider", "model", "dimensions"],
    metric_fields=["requests_total", "dimensions"],
    intended_uses=["cloud_second", "managed_api"],
)

_SUPPORTED_MODELS = frozenset({"embed-v4.0", "embed-english-v3.0", "embed-multilingual-v3.0"})

_COHERE_EMBED_URL = "https://api.cohere.com/v2/embed"


@dataclass
class CohereEmbeddingProvider(BaseProvider):
    """Cohere cloud embedding provider."""

    model_name: str = "embed-v4.0"
    input_type: str = "search_document"
    metadata: ProviderMetadata = field(
        default_factory=lambda: COHERE_EMBEDDING_METADATA, init=False
    )
    _config: dict[str, Any] = field(default_factory=dict, repr=False)
    _client: httpx.Client | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.metadata = COHERE_EMBEDDING_METADATA

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _api_key(self) -> str:
        key = self._config.get("api_key") or os.getenv("COHERE_API_KEY")
        if not key:
            raise ProviderError(
                "Provider 'embedding.cohere' requires COHERE_API_KEY "
                "(set via env var or api_key config field)",
                code="missing_required_secret",
                retryable=False,
                details={"provider": "embedding.cohere", "secret": "COHERE_API_KEY"},
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
        key = self._config.get("api_key") or os.getenv("COHERE_API_KEY")
        if not key:
            return ProviderHealth(
                status="unavailable",
                detail="COHERE_API_KEY is not configured",
                metrics={"provider": "embedding.cohere"},
            )
        return ProviderHealth(
            status="healthy",
            detail="Cohere API key is configured",
            metrics={"provider": "embedding.cohere", "model": self.model_name},
        )

    def embed_text(self, text: str) -> EmbeddingResult:
        body = {
            "model": self.model_name,
            "texts": [text],
            "input_type": self.input_type,
            "embedding_types": ["float"],
        }
        try:
            client = self._http()
            owned = self._client is None
            try:
                response = client.post(_COHERE_EMBED_URL, headers=self._headers(), json=body)
            finally:
                if owned:
                    client.close()
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Provider 'embedding.cohere' HTTP request failed: {exc}",
                code="request_failed",
                retryable=True,
                details={"provider": "embedding.cohere", "error": str(exc)},
            ) from exc

        if not response.is_success:
            try:
                err_body = response.json()
            except Exception:
                err_body = {"raw": response.text}
            msg = err_body.get("message", response.text)
            raise ProviderError(
                f"Provider 'embedding.cohere' returned HTTP {response.status_code}: {msg}",
                code="api_error",
                retryable=response.status_code >= 500,
                details={"provider": "embedding.cohere", "status": response.status_code},
            )

        data = response.json()
        try:
            vector = [float(v) for v in data["embeddings"]["float"][0]]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                f"Provider 'embedding.cohere' returned unexpected response shape: {exc}",
                code="api_error",
                retryable=False,
                details={"provider": "embedding.cohere"},
            ) from exc

        return EmbeddingResult(
            provider="embedding.cohere",
            model=self.model_name,
            dimensions=len(vector),
            vector=vector,
            metadata={"input_type": self.input_type},
        )


def create_cohere_embedding_provider(**config: Any) -> CohereEmbeddingProvider:
    schema = COHERE_EMBEDDING_METADATA.config_schema
    provider = CohereEmbeddingProvider(
        model_name=str(config.get("model_name", schema["model_name"]["default"])),
        input_type=str(config.get("input_type", schema["input_type"]["default"])),
    )
    provider._config = dict(config)
    provider._client = config.get("client")
    return provider


__all__ = [
    "COHERE_EMBEDDING_METADATA",
    "CohereEmbeddingProvider",
    "create_cohere_embedding_provider",
]
