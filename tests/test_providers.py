from __future__ import annotations

from dataclasses import dataclass

import pytest

from ragrig.embeddings import EmbeddingResult
from ragrig.providers import (
    BaseProvider,
    ProviderCapability,
    ProviderError,
    ProviderHealth,
    ProviderKind,
    ProviderMetadata,
    ProviderRegistry,
    ProviderRetryPolicy,
    get_provider_registry,
)

pytestmark = pytest.mark.unit


@dataclass
class FakeEmbeddingProvider(BaseProvider):
    metadata: ProviderMetadata
    config: dict[str, object]

    def embed_text(self, text: str) -> EmbeddingResult:
        if ProviderCapability.EMBEDDING not in self.metadata.capabilities:
            self.raise_unsupported_capability(ProviderCapability.EMBEDDING)

        dimensions = int(self.config.get("dimensions", 3))
        return EmbeddingResult(
            provider=self.metadata.name,
            model="fake-embedding-model",
            dimensions=dimensions,
            vector=[0.25] * dimensions,
            metadata={"text": text},
        )

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(status="healthy", detail="fake provider ready")


def _fake_metadata() -> ProviderMetadata:
    return ProviderMetadata(
        name="fake-embedding",
        kind=ProviderKind.LOCAL,
        description="Test-only embedding provider",
        capabilities={ProviderCapability.EMBEDDING, ProviderCapability.BATCH},
        default_dimensions=3,
        max_dimensions=12,
        default_context_window=None,
        max_context_window=None,
        required_secrets=[],
        config_schema={"dimensions": {"type": "integer", "minimum": 1, "default": 3}},
        sdk_protocol="in-process",
        healthcheck="Instantiate provider and embed a sample string",
        failure_modes=["invalid_dimensions"],
        retry_policy=ProviderRetryPolicy(max_attempts=1, backoff_seconds=0.0),
        audit_fields=["provider", "model", "dimensions"],
        metric_fields=["latency_ms", "requests_total"],
        intended_uses=["tests"],
    )


def test_provider_registry_register_get_list_and_health_check() -> None:
    registry = ProviderRegistry()
    metadata = _fake_metadata()
    registry.register(
        metadata,
        lambda **config: FakeEmbeddingProvider(metadata=metadata, config=config),
    )

    provider = registry.get("fake-embedding", dimensions=5)

    assert provider.metadata.name == "fake-embedding"
    assert provider.embed_text("fixture").dimensions == 5
    assert registry.list() == [metadata]
    assert registry.read("fake-embedding") == metadata
    assert registry.health_check_all({"fake-embedding": {"dimensions": 5}}) == {
        "fake-embedding": ProviderHealth(status="healthy", detail="fake provider ready")
    }


def test_provider_registry_returns_structured_errors_for_unknown_provider_and_capability() -> None:
    registry = ProviderRegistry()
    metadata = _fake_metadata()
    registry.register(
        metadata,
        lambda **config: FakeEmbeddingProvider(metadata=metadata, config=config),
    )

    with pytest.raises(ProviderError) as missing_exc:
        registry.get("missing-provider")

    assert missing_exc.value.code == "provider_not_registered"
    assert missing_exc.value.retryable is False
    assert missing_exc.value.details == {"provider": "missing-provider"}

    provider = registry.get("fake-embedding")
    with pytest.raises(ProviderError) as unsupported_exc:
        provider.generate("hello")

    assert unsupported_exc.value.code == "unsupported_capability"
    assert unsupported_exc.value.retryable is False
    assert unsupported_exc.value.details == {
        "capability": "generate",
        "provider": "fake-embedding",
    }


def test_default_provider_registry_exposes_deterministic_local_contract() -> None:
    registry = get_provider_registry()

    metadata = registry.read("deterministic-local")
    provider = registry.get("deterministic-local", dimensions=6)
    result = provider.embed_text("fixture")

    assert metadata.name == "deterministic-local"
    assert metadata.kind is ProviderKind.LOCAL
    assert metadata.required_secrets == []
    assert metadata.sdk_protocol == "in-process"
    assert metadata.intended_uses == ["ci", "smoke"]
    assert ProviderCapability.EMBEDDING in metadata.capabilities
    assert result.provider == "deterministic-local"
    assert result.dimensions == 6


def test_base_provider_default_methods_raise_structured_errors() -> None:
    provider = FakeEmbeddingProvider(metadata=_fake_metadata(), config={})
    provider.metadata = ProviderMetadata(
        **{
            **provider.metadata.__dict__,
            "capabilities": set(),
        }
    )

    assert provider.health_check() == ProviderHealth(status="healthy", detail="fake provider ready")

    with pytest.raises(ProviderError) as embed_exc:
        BaseProvider.embed_text(provider, "fixture")
    with pytest.raises(ProviderError) as generate_exc:
        BaseProvider.generate(provider, "fixture")
    with pytest.raises(ProviderError) as chat_exc:
        BaseProvider.chat(provider, [{"role": "user", "content": "fixture"}])
    with pytest.raises(ProviderError) as rerank_exc:
        BaseProvider.rerank(provider, "fixture", ["doc"])

    assert embed_exc.value.details == {"provider": "fake-embedding", "capability": "embedding"}
    assert generate_exc.value.details == {"provider": "fake-embedding", "capability": "generate"}
    assert chat_exc.value.details == {"provider": "fake-embedding", "capability": "chat"}
    assert rerank_exc.value.details == {"provider": "fake-embedding", "capability": "rerank"}


def test_base_provider_default_health_check_returns_unknown() -> None:
    provider = FakeEmbeddingProvider(metadata=_fake_metadata(), config={})

    health = BaseProvider.health_check(provider)

    assert health == ProviderHealth(status="unknown", detail="Health check not implemented")


def test_provider_registry_read_missing_and_empty_health_checks() -> None:
    registry = ProviderRegistry()

    with pytest.raises(ProviderError) as missing_exc:
        registry.read("missing-provider")

    assert missing_exc.value.code == "provider_not_registered"
    assert registry.health_check_all() == {}


def test_deterministic_local_provider_health_check_reports_dimensions() -> None:
    provider = get_provider_registry().get("deterministic-local", dimensions=7)

    health = provider.health_check()

    assert health.status == "healthy"
    assert health.metrics == {"dimensions": 7}
