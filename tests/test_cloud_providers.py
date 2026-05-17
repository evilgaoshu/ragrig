"""Unit tests for real cloud provider implementations.

All tests use fake httpx transports or mock clients — no live API calls.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from ragrig.providers import get_provider_registry
from ragrig.providers.cloud import (
    AnthropicProvider,
    AzureOpenAIProvider,
    CohereProvider,
    JinaProvider,
    OpenAICompatibleCloudProvider,
    VoyageProvider,
)

pytestmark = pytest.mark.unit


# ── Fake httpx transport ──────────────────────────────────────────────────────

class FakeTransport(httpx.BaseTransport):
    """Returns a canned JSON response for every request."""

    def __init__(self, status: int = 200, body: dict[str, Any] | None = None) -> None:
        self.status = status
        self.body = body or {}
        self.calls: list[dict[str, Any]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append({"method": request.method, "url": str(request.url)})
        import json

        return httpx.Response(
            status_code=self.status,
            headers={"content-type": "application/json"},
            content=json.dumps(self.body).encode(),
            request=request,
        )


def _fake_client(
    status: int = 200, body: dict[str, Any] | None = None
) -> tuple[httpx.Client, FakeTransport]:
    transport = FakeTransport(status=status, body=body)
    return httpx.Client(transport=transport), transport


# ── Registry wiring ───────────────────────────────────────────────────────────

def test_registry_has_no_stub_status_for_openai_when_key_missing() -> None:
    registry = get_provider_registry()
    health = registry.get("model.openai").health_check()
    assert health.status == "unavailable"
    assert "OPENAI_API_KEY" in health.detail


def test_registry_has_no_stub_status_for_anthropic_when_key_missing() -> None:
    registry = get_provider_registry()
    health = registry.get("model.anthropic").health_check()
    assert health.status == "unavailable"
    assert "ANTHROPIC_API_KEY" in health.detail


def test_registry_oai_compat_cloud_providers_are_real(monkeypatch: pytest.MonkeyPatch) -> None:
    """All OpenAI-compatible cloud providers must not return 'stub' health status."""
    oai_compat = [
        "model.openai", "model.openrouter", "model.mistral", "model.groq",
        "model.deepseek", "model.together", "model.fireworks", "model.moonshot",
        "model.minimax", "model.dashscope", "model.siliconflow", "model.zhipu",
        "model.baidu_qianfan", "model.volcengine_ark", "model.xai",
        "model.perplexity", "model.nvidia_nim", "model.openai_compatible",
    ]
    registry = get_provider_registry()
    for name in oai_compat:
        health = registry.get(name).health_check()
        assert health.status != "stub", f"{name} still returns stub status"


# ── OpenAICompatibleCloudProvider ─────────────────────────────────────────────

def test_oai_compat_cloud_chat_returns_content() -> None:
    client, transport = _fake_client(body={
        "choices": [{"message": {"role": "assistant", "content": "Hello!"}}]
    })
    provider = OpenAICompatibleCloudProvider(
        provider_name="model.openai",
        metadata=get_provider_registry().read("model.openai"),
        api_base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        model_name="gpt-4o-mini",
        config={"api_key": "sk-test"},
        client=client,
    )
    result = provider.chat([{"role": "user", "content": "hi"}])
    assert result["choices"][0]["message"]["content"] == "Hello!"
    assert any("/chat/completions" in c["url"] for c in transport.calls)


def test_oai_compat_cloud_generate_wraps_chat() -> None:
    client, _ = _fake_client(body={
        "choices": [{"message": {"role": "assistant", "content": "42"}}]
    })
    provider = OpenAICompatibleCloudProvider(
        provider_name="model.groq",
        metadata=get_provider_registry().read("model.groq"),
        api_base_url="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
        model_name="llama3",
        config={"api_key": "gsk-test"},
        client=client,
    )
    assert provider.generate("what is 6×7?") == "42"


def test_oai_compat_cloud_embed_text_returns_embedding() -> None:
    client, transport = _fake_client(body={
        "data": [{"embedding": [0.1, 0.2, 0.3]}]
    })
    provider = OpenAICompatibleCloudProvider(
        provider_name="model.openai",
        metadata=get_provider_registry().read("model.openai"),
        api_base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        model_name="gpt-4o-mini",
        embedding_model_name="text-embedding-3-large",
        config={"api_key": "sk-test"},
        client=client,
    )
    result = provider.embed_text("test")
    assert result.dimensions == 3
    assert result.vector == [0.1, 0.2, 0.3]
    assert any("/embeddings" in c["url"] for c in transport.calls)


def test_oai_compat_cloud_embed_raises_when_no_embedding_model() -> None:
    client, _ = _fake_client()
    provider = OpenAICompatibleCloudProvider(
        provider_name="model.groq",
        metadata=get_provider_registry().read("model.groq"),
        api_base_url="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
        model_name="llama3",
        config={"api_key": "gsk-test"},
        client=client,
    )
    from ragrig.providers import ProviderError
    with pytest.raises(ProviderError, match="embedding"):
        provider.embed_text("test")


def test_oai_compat_cloud_health_unavailable_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client, _ = _fake_client()
    provider = OpenAICompatibleCloudProvider(
        provider_name="model.openai",
        metadata=get_provider_registry().read("model.openai"),
        api_base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        model_name="gpt-4o-mini",
        config={},
        client=client,
    )
    health = provider.health_check()
    assert health.status == "unavailable"


# ── AnthropicProvider ─────────────────────────────────────────────────────────

def test_anthropic_chat_maps_messages_to_anthropic_format() -> None:
    client, transport = _fake_client(body={
        "content": [{"type": "text", "text": "Bonjour!"}],
        "role": "assistant",
    })
    provider = AnthropicProvider(config={"api_key": "sk-ant-test"}, client=client)
    result = provider.chat([
        {"role": "system", "content": "Reply in French."},
        {"role": "user", "content": "Hello"},
    ])
    assert result["choices"][0]["message"]["content"] == "Bonjour!"
    call = transport.calls[0]
    assert "/messages" in call["url"]


def test_anthropic_generate_returns_text() -> None:
    client, _ = _fake_client(body={"content": [{"type": "text", "text": "Hi"}]})
    provider = AnthropicProvider(config={"api_key": "sk-ant-test"}, client=client)
    assert provider.generate("Hello") == "Hi"


def test_anthropic_health_unavailable_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = AnthropicProvider(config={})
    health = provider.health_check()
    assert health.status == "unavailable"


def test_anthropic_health_ok_when_key_configured() -> None:
    provider = AnthropicProvider(config={"api_key": "sk-ant-test"})
    health = provider.health_check()
    assert health.status == "healthy"


# ── AzureOpenAIProvider ───────────────────────────────────────────────────────

def test_azure_openai_chat_uses_deployment_url() -> None:
    client, transport = _fake_client(body={
        "choices": [{"message": {"role": "assistant", "content": "Azure!"}}]
    })
    provider = AzureOpenAIProvider(
        api_base_url="https://myresource.openai.azure.com/openai/deployments",
        deployment_name="gpt-4.1",
        api_version="2025-01-01-preview",
        config={"api_key": "azure-test-key"},
        client=client,
    )
    result = provider.chat([{"role": "user", "content": "test"}])
    assert result["choices"][0]["message"]["content"] == "Azure!"
    assert "gpt-4.1" in transport.calls[0]["url"]


def test_azure_openai_embed_text() -> None:
    client, transport = _fake_client(body={"data": [{"embedding": [0.5, 0.6]}]})
    provider = AzureOpenAIProvider(
        api_base_url="https://myresource.openai.azure.com/openai/deployments",
        deployment_name="gpt-4.1",
        embedding_deployment_name="text-embedding-3-large",
        config={"api_key": "azure-test-key"},
        client=client,
    )
    result = provider.embed_text("hello")
    assert result.dimensions == 2
    assert "text-embedding-3-large" in transport.calls[0]["url"]


def test_azure_openai_health_unavailable_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    provider = AzureOpenAIProvider(
        api_base_url="https://x.openai.azure.com/openai/deployments",
        deployment_name="gpt-4.1",
        config={},
    )
    assert provider.health_check().status == "unavailable"


# ── JinaProvider ──────────────────────────────────────────────────────────────

def test_jina_embed_text() -> None:
    client, transport = _fake_client(body={"data": [{"embedding": [0.1, 0.9]}]})
    provider = JinaProvider(config={"api_key": "jina-test"}, client=client)
    result = provider.embed_text("hello")
    assert result.dimensions == 2
    assert "/embeddings" in transport.calls[0]["url"]


def test_jina_rerank() -> None:
    client, transport = _fake_client(body={
        "results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.3}]
    })
    provider = JinaProvider(config={"api_key": "jina-test"}, client=client)
    docs = ["doc a", "doc b"]
    results = provider.rerank("query", docs)
    assert results[0]["index"] == 1
    assert results[0]["score"] == pytest.approx(0.9)
    assert "/rerank" in transport.calls[0]["url"]


# ── VoyageProvider ────────────────────────────────────────────────────────────

def test_voyage_embed_text() -> None:
    client, _ = _fake_client(body={"data": [{"embedding": [0.2, 0.8, 0.4]}]})
    provider = VoyageProvider(config={"api_key": "voyage-test"}, client=client)
    result = provider.embed_text("test document")
    assert result.dimensions == 3
    assert result.provider == "model.voyage"


def test_voyage_rerank() -> None:
    client, _ = _fake_client(body={
        "data": [{"index": 0, "relevance_score": 0.95}]
    })
    provider = VoyageProvider(config={"api_key": "voyage-test"}, client=client)
    results = provider.rerank("query", ["only doc"])
    assert results[0]["score"] == pytest.approx(0.95)


# ── CohereProvider ────────────────────────────────────────────────────────────

def test_cohere_chat_returns_content() -> None:
    client, transport = _fake_client(body={
        "message": {"content": [{"text": "Cohere response"}]}
    })
    provider = CohereProvider(config={"api_key": "cohere-test"}, client=client)
    result = provider.chat([{"role": "user", "content": "hi"}])
    assert result["choices"][0]["message"]["content"] == "Cohere response"
    assert "/chat" in transport.calls[0]["url"]


def test_cohere_embed_text() -> None:
    client, _ = _fake_client(body={
        "embeddings": {"float": [[0.1, 0.2, 0.3]]}
    })
    provider = CohereProvider(config={"api_key": "cohere-test"}, client=client)
    result = provider.embed_text("hello")
    assert result.dimensions == 3


def test_cohere_rerank() -> None:
    client, _ = _fake_client(body={
        "results": [{"index": 1, "relevance_score": 0.85}, {"index": 0, "relevance_score": 0.2}]
    })
    provider = CohereProvider(config={"api_key": "cohere-test"}, client=client)
    docs = ["alpha", "beta"]
    results = provider.rerank("search query", docs)
    assert results[0]["index"] == 1
    assert results[0]["document"] == "beta"


def test_cohere_health_unavailable_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    provider = CohereProvider(config={})
    assert provider.health_check().status == "unavailable"
