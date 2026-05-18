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
    JinaProvider,
    OpenAICompatibleCloudProvider,
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
        "model.openai",
        "model.openrouter",
        "model.mistral",
        "model.groq",
        "model.deepseek",
        "model.together",
        "model.fireworks",
        "model.moonshot",
        "model.minimax",
        "model.dashscope",
        "model.siliconflow",
        "model.zhipu",
        "model.baidu_qianfan",
        "model.volcengine_ark",
        "model.xai",
        "model.perplexity",
        "model.nvidia_nim",
        "model.openai_compatible",
    ]
    registry = get_provider_registry()
    for name in oai_compat:
        health = registry.get(name).health_check()
        assert health.status != "stub", f"{name} still returns stub status"


# ── OpenAICompatibleCloudProvider ─────────────────────────────────────────────


def test_oai_compat_cloud_chat_returns_content() -> None:
    client, transport = _fake_client(
        body={"choices": [{"message": {"role": "assistant", "content": "Hello!"}}]}
    )
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
    client, _ = _fake_client(
        body={"choices": [{"message": {"role": "assistant", "content": "42"}}]}
    )
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
    client, transport = _fake_client(body={"data": [{"embedding": [0.1, 0.2, 0.3]}]})
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
    client, transport = _fake_client(
        body={
            "content": [{"type": "text", "text": "Bonjour!"}],
            "role": "assistant",
        }
    )
    provider = AnthropicProvider(config={"api_key": "sk-ant-test"}, client=client)
    result = provider.chat(
        [
            {"role": "system", "content": "Reply in French."},
            {"role": "user", "content": "Hello"},
        ]
    )
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
    client, transport = _fake_client(
        body={"choices": [{"message": {"role": "assistant", "content": "Azure!"}}]}
    )
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
    client, transport = _fake_client(
        body={
            "results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.3}]
        }
    )
    provider = JinaProvider(config={"api_key": "jina-test"}, client=client)
    docs = ["doc a", "doc b"]
    results = provider.rerank("query", docs)
    assert results[0]["index"] == 1
    assert results[0]["score"] == pytest.approx(0.9)
    assert "/rerank" in transport.calls[0]["url"]


def test_jina_health_ok_when_key_configured() -> None:
    provider = JinaProvider(config={"api_key": "jina-test"})
    health = provider.health_check()
    assert health.status == "healthy"
    assert "jina" in health.detail.lower()


def test_jina_health_unavailable_when_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JINA_API_KEY", raising=False)
    provider = JinaProvider(config={})
    assert provider.health_check().status == "unavailable"


def test_jina_post_raises_provider_error_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from ragrig.providers import ProviderError

    class ErrorTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

    client = httpx.Client(transport=ErrorTransport())
    provider = JinaProvider(config={"api_key": "jina-test"}, client=client)
    with pytest.raises(ProviderError, match="HTTP request failed"):
        provider.embed_text("test")


def test_create_jina_provider_factory() -> None:
    from ragrig.providers.cloud import create_jina_provider

    provider = create_jina_provider(api_key="jina-test")
    assert isinstance(provider, JinaProvider)


# ── AzureOpenAIProvider (extra coverage) ─────────────────────────────────────


def test_azure_openai_generate_returns_text() -> None:
    client, _ = _fake_client(
        body={"choices": [{"message": {"role": "assistant", "content": "Azure response"}}]}
    )
    provider = AzureOpenAIProvider(
        api_base_url="https://myresource.openai.azure.com/openai/deployments",
        deployment_name="gpt-4.1",
        config={"api_key": "azure-key"},
        client=client,
    )
    assert provider.generate("hello") == "Azure response"


def test_azure_openai_health_ok_when_key_configured() -> None:
    provider = AzureOpenAIProvider(
        api_base_url="https://myresource.openai.azure.com/openai/deployments",
        deployment_name="gpt-4.1",
        config={"api_key": "azure-key"},
    )
    health = provider.health_check()
    assert health.status == "healthy"
    assert "gpt-4.1" in health.detail or "gpt-4.1" in str(health.metrics)


def test_azure_openai_embed_raises_when_no_deployment() -> None:
    from ragrig.providers import ProviderError

    client, _ = _fake_client()
    provider = AzureOpenAIProvider(
        api_base_url="https://myresource.openai.azure.com/openai/deployments",
        deployment_name="gpt-4.1",
        config={"api_key": "azure-key"},
        client=client,
    )
    with pytest.raises(ProviderError, match="embedding"):
        provider.embed_text("test")


def test_azure_openai_post_raises_provider_error_on_http_error() -> None:
    from ragrig.providers import ProviderError

    class ErrorTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("network unreachable")

    client = httpx.Client(transport=ErrorTransport())
    provider = AzureOpenAIProvider(
        api_base_url="https://myresource.openai.azure.com/openai/deployments",
        deployment_name="gpt-4.1",
        config={"api_key": "azure-key"},
        client=client,
    )
    with pytest.raises(ProviderError, match="HTTP request failed"):
        provider.chat([{"role": "user", "content": "hi"}])


def test_create_azure_openai_provider_factory() -> None:
    from ragrig.providers.cloud import create_azure_openai_provider

    provider = create_azure_openai_provider(api_key="azure-key")
    assert isinstance(provider, AzureOpenAIProvider)


# ── AnthropicProvider (extra coverage) ───────────────────────────────────────


def test_anthropic_post_raises_provider_error_on_http_error() -> None:
    from ragrig.providers import ProviderError

    class ErrorTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("timeout")

    client = httpx.Client(transport=ErrorTransport())
    provider = AnthropicProvider(config={"api_key": "sk-ant-test"}, client=client)
    with pytest.raises(ProviderError, match="HTTP request failed"):
        provider.chat([{"role": "user", "content": "hi"}])


# ── OpenAICompatibleCloudProvider (extra coverage) ────────────────────────────


def test_oai_compat_cloud_rerank_returns_scored_results() -> None:
    client, transport = _fake_client(
        body={
            "results": [
                {"index": 1, "relevance_score": 0.95},
                {"index": 0, "relevance_score": 0.4},
            ]
        }
    )
    provider = OpenAICompatibleCloudProvider(
        provider_name="model.openai",
        metadata=get_provider_registry().read("model.openai"),
        api_base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        model_name="gpt-4o-mini",
        reranker_model_name="rerank-1",
        config={"api_key": "sk-test"},
        client=client,
    )
    docs = ["doc a", "doc b"]
    results = provider.rerank("query", docs)
    assert results[0]["score"] == pytest.approx(0.95)
    assert any("/rerank" in c["url"] for c in transport.calls)


def test_oai_compat_cloud_rerank_raises_when_no_reranker_model() -> None:
    from ragrig.providers import ProviderError

    client, _ = _fake_client()
    provider = OpenAICompatibleCloudProvider(
        provider_name="model.openai",
        metadata=get_provider_registry().read("model.openai"),
        api_base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        model_name="gpt-4o-mini",
        config={"api_key": "sk-test"},
        client=client,
    )
    with pytest.raises(ProviderError, match="rerank"):
        provider.rerank("query", ["doc a"])


def test_oai_compat_cloud_health_probes_api_when_key_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client, transport = _fake_client(body={"data": [{"id": "gpt-4o"}]})
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
    assert health.status == "healthy"
    assert any("/models" in c["url"] for c in transport.calls)


def test_oai_compat_cloud_health_returns_unavailable_on_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "bad-key")
    client, _ = _fake_client(status=401, body={"error": {"message": "Invalid key"}})
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


def test_oai_compat_cloud_health_handles_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class ErrorTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

    client = httpx.Client(transport=ErrorTransport())
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


# ── _check_response and _wrap_http_error helpers ──────────────────────────────


def test_check_response_raises_on_http_error_status() -> None:
    import json

    from ragrig.providers import ProviderError
    from ragrig.providers.cloud import _check_response

    request = httpx.Request("GET", "https://api.example.com/v1/models")
    response = httpx.Response(
        status_code=500,
        headers={"content-type": "application/json"},
        content=json.dumps({"error": {"message": "Internal Server Error"}}).encode(),
        request=request,
    )
    with pytest.raises(ProviderError, match="HTTP 500"):
        _check_response("model.openai", response)


def test_check_response_raises_on_non_json_error_body() -> None:
    from ragrig.providers import ProviderError
    from ragrig.providers.cloud import _check_response

    request = httpx.Request("GET", "https://api.example.com/v1/models")
    response = httpx.Response(
        status_code=503,
        headers={"content-type": "text/plain"},
        content=b"Service Unavailable",
        request=request,
    )
    with pytest.raises(ProviderError, match="HTTP 503"):
        _check_response("model.openai", response)


def test_wrap_http_error_creates_retryable_provider_error() -> None:
    from ragrig.providers import ProviderError
    from ragrig.providers.cloud import _wrap_http_error

    exc = httpx.ConnectError("timeout")
    err = _wrap_http_error("model.groq", exc)
    assert isinstance(err, ProviderError)
    assert err.retryable is True
    assert "model.groq" in str(err)


# ── GeminiProvider ────────────────────────────────────────────────────────────


def test_gemini_resolve_client_raises_when_google_genai_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    from ragrig.providers import ProviderError
    from ragrig.providers.cloud import GeminiProvider

    provider = GeminiProvider(api_key="google-test")
    for key in list(sys.modules.keys()):
        if "google" in key and "genai" in key:
            monkeypatch.delitem(sys.modules, key)

    original_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

    def mock_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "google.genai" or name == "google":
            raise ImportError("No module named 'google'")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", mock_import)
    with pytest.raises(ProviderError, match="optional cloud dependencies"):
        provider._resolve_client()


def test_gemini_resolve_client_returns_cached_client() -> None:
    from ragrig.providers.cloud import GeminiProvider

    fake_client = object()
    provider = GeminiProvider(api_key="google-test", client=fake_client)
    assert provider._resolve_client() is fake_client
