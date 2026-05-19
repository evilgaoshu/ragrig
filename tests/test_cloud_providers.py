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


# ── VertexAIProvider ──────────────────────────────────────────────────────────


class FakeVertexModel:
    def __init__(self, response_text: str) -> None:
        self._text = response_text

    def generate_content(self, prompt: str) -> object:
        class _Resp:
            text = None

        resp = _Resp()
        resp.text = self._text  # type: ignore[attr-defined]
        return resp


class FakeTextEmbeddingModel:
    def __init__(self, vector: list[float]) -> None:
        self._vector = vector

    @classmethod
    def from_pretrained(cls, name: str) -> "FakeTextEmbeddingModel":
        return cls([0.1, 0.2, 0.3])

    def get_embeddings(self, inputs: list[Any]) -> list[Any]:
        class _Emb:
            values = [0.1, 0.2, 0.3]

        return [_Emb()]


def _make_vertex_modules(response_text: str = "vertex answer") -> dict[str, Any]:
    import types

    vertexai_mod = types.ModuleType("vertexai")
    vertexai_mod.init = lambda **kw: None  # type: ignore[attr-defined]

    gen_models_mod = types.ModuleType("vertexai.generative_models")
    gen_models_mod.GenerativeModel = lambda name: FakeVertexModel(response_text)  # type: ignore[attr-defined]

    lang_models_mod = types.ModuleType("vertexai.language_models")
    lang_models_mod.TextEmbeddingModel = FakeTextEmbeddingModel  # type: ignore[attr-defined]

    class _FakeInput:
        def __init__(self, text: str) -> None:
            self.text = text

    lang_models_mod.TextEmbeddingInput = _FakeInput  # type: ignore[attr-defined]

    return {
        "vertexai": vertexai_mod,
        "vertexai.generative_models": gen_models_mod,
        "vertexai.language_models": lang_models_mod,
    }


def test_vertex_ai_health_unavailable_when_no_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ragrig.providers.cloud import VertexAIProvider

    monkeypatch.delenv("VERTEX_AI_PROJECT", raising=False)
    provider = VertexAIProvider(project="")
    health = provider.health_check()
    assert health.status == "unavailable"
    assert "VERTEX_AI_PROJECT" in health.detail


def test_vertex_ai_health_ok_with_project(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from ragrig.providers.cloud import VertexAIProvider

    for name, mod in _make_vertex_modules().items():
        monkeypatch.setitem(sys.modules, name, mod)

    provider = VertexAIProvider(project="my-gcp-project")
    health = provider.health_check()
    assert health.status == "healthy"
    assert "my-gcp-project" in health.detail


def test_vertex_ai_generate_returns_text(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from ragrig.providers.cloud import VertexAIProvider

    for name, mod in _make_vertex_modules("vertex answer").items():
        monkeypatch.setitem(sys.modules, name, mod)

    provider = VertexAIProvider(project="my-gcp-project")
    result = provider.generate("Tell me something")
    assert result == "vertex answer"


def test_vertex_ai_chat_formats_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from ragrig.providers.cloud import VertexAIProvider

    for name, mod in _make_vertex_modules("chat reply").items():
        monkeypatch.setitem(sys.modules, name, mod)

    provider = VertexAIProvider(project="my-gcp-project")
    result = provider.chat([{"role": "user", "content": "Hello"}])
    assert result["choices"][0]["message"]["content"] == "chat reply"


def test_vertex_ai_embed_text_returns_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from ragrig.providers.cloud import VertexAIProvider

    for name, mod in _make_vertex_modules().items():
        monkeypatch.setitem(sys.modules, name, mod)

    provider = VertexAIProvider(project="my-gcp-project")
    result = provider.embed_text("some text")
    assert result.provider == "model.vertex_ai"
    assert len(result.vector) == 3


def test_create_vertex_ai_provider_missing_project(monkeypatch: pytest.MonkeyPatch) -> None:
    from ragrig.providers import ProviderError
    from ragrig.providers.cloud import create_vertex_ai_provider

    monkeypatch.delenv("VERTEX_AI_PROJECT", raising=False)
    with pytest.raises(ProviderError, match="VERTEX_AI_PROJECT"):
        create_vertex_ai_provider()


def test_create_vertex_ai_provider_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from ragrig.providers.cloud import VertexAIProvider, create_vertex_ai_provider

    monkeypatch.setenv("VERTEX_AI_PROJECT", "env-project")
    provider = create_vertex_ai_provider()
    assert isinstance(provider, VertexAIProvider)
    assert provider._project == "env-project"


def test_vertex_ai_health_unavailable_when_sdk_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    from ragrig.providers.cloud import VertexAIProvider

    monkeypatch.setitem(sys.modules, "vertexai", None)  # type: ignore[arg-type]
    provider = VertexAIProvider(project="my-gcp-project")
    health = provider.health_check()
    assert health.status == "unavailable"


def test_registry_vertex_ai_returns_real_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from ragrig.providers import get_provider_registry
    from ragrig.providers.cloud import VertexAIProvider

    monkeypatch.delenv("VERTEX_AI_PROJECT", raising=False)
    registry = get_provider_registry()
    # Factory raises if no project, but health_check on a bare instance works
    provider = VertexAIProvider(project="")
    health = provider.health_check()
    assert health.status == "unavailable"
    # Verify registry factory produces the right type when project is provided
    monkeypatch.setenv("VERTEX_AI_PROJECT", "test-project")
    p = registry.get("model.vertex_ai")
    assert isinstance(p, VertexAIProvider)


# ── BedrockProvider ───────────────────────────────────────────────────────────


def _make_bedrock_client(converse_text: str = "bedrock reply") -> Any:
    import io
    import json
    import types

    class _FakeBedrockClient:
        def converse(self, **kwargs: Any) -> dict[str, Any]:
            return {"output": {"message": {"content": [{"text": converse_text}]}}}

        def invoke_model(self, **kwargs: Any) -> dict[str, Any]:
            model_id = kwargs.get("modelId", "")
            if "titan" in model_id:
                body = json.dumps({"embedding": [0.4, 0.5, 0.6]}).encode()
            elif "rerank" in model_id:
                body = json.dumps({"results": [{"index": 0, "relevanceScore": 0.9}]}).encode()
            else:
                # cohere.embed or any other non-titan embed model
                body = json.dumps({"embeddings": [[0.1, 0.2, 0.3]]}).encode()
            return {"body": io.BytesIO(body)}

    boto3_mod = types.ModuleType("boto3")
    boto3_mod.client = lambda service, region_name=None: _FakeBedrockClient()  # type: ignore[attr-defined]
    return boto3_mod


def test_bedrock_health_unavailable_when_boto3_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    from ragrig.providers.cloud import BedrockProvider

    monkeypatch.setitem(sys.modules, "boto3", None)  # type: ignore[arg-type]
    provider = BedrockProvider()
    health = provider.health_check()
    assert health.status == "unavailable"
    assert "boto3" in health.detail


def test_bedrock_health_unavailable_when_no_access_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    from ragrig.providers.cloud import BedrockProvider

    monkeypatch.setitem(sys.modules, "boto3", _make_bedrock_client())
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    provider = BedrockProvider()
    health = provider.health_check()
    assert health.status == "unavailable"
    assert "AWS_ACCESS_KEY_ID" in health.detail


def test_bedrock_health_ok_with_access_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from ragrig.providers.cloud import BedrockProvider

    monkeypatch.setitem(sys.modules, "boto3", _make_bedrock_client())
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIATEST")
    provider = BedrockProvider()
    health = provider.health_check()
    assert health.status == "healthy"
    assert "us-east-1" in health.detail


def test_bedrock_chat_returns_content(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from ragrig.providers.cloud import BedrockProvider

    monkeypatch.setitem(sys.modules, "boto3", _make_bedrock_client("hello from bedrock"))
    provider = BedrockProvider()
    result = provider.chat([{"role": "user", "content": "Hi"}])
    assert result["choices"][0]["message"]["content"] == "hello from bedrock"


def test_bedrock_chat_strips_system_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from ragrig.providers.cloud import BedrockProvider

    monkeypatch.setitem(sys.modules, "boto3", _make_bedrock_client("reply"))
    provider = BedrockProvider()
    result = provider.chat(
        [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "Hello"},
        ]
    )
    assert result["choices"][0]["message"]["content"] == "reply"


def test_bedrock_generate_delegates_to_chat(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from ragrig.providers.cloud import BedrockProvider

    monkeypatch.setitem(sys.modules, "boto3", _make_bedrock_client("generated"))
    provider = BedrockProvider()
    result = provider.generate("Tell me something")
    assert result == "generated"


def test_bedrock_embed_text_titan(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from ragrig.providers.cloud import BedrockProvider

    monkeypatch.setitem(sys.modules, "boto3", _make_bedrock_client())
    provider = BedrockProvider(embedding_model_name="amazon.titan-embed-text-v2:0")
    result = provider.embed_text("hello")
    assert result.provider == "model.bedrock"
    assert result.vector == [0.4, 0.5, 0.6]


def test_bedrock_embed_text_cohere(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from ragrig.providers.cloud import BedrockProvider

    monkeypatch.setitem(sys.modules, "boto3", _make_bedrock_client())
    provider = BedrockProvider(embedding_model_name="cohere.embed-multilingual-v3")
    result = provider.embed_text("hello")
    assert result.provider == "model.bedrock"
    assert len(result.vector) == 3


def test_bedrock_rerank_returns_scored_results(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from ragrig.providers.cloud import BedrockProvider

    monkeypatch.setitem(sys.modules, "boto3", _make_bedrock_client())
    provider = BedrockProvider()
    results = provider.rerank("query", ["doc 0"])
    assert results[0]["score"] == pytest.approx(0.9)
    assert results[0]["index"] == 0


def test_create_bedrock_provider_defaults() -> None:
    from ragrig.providers.cloud import BedrockProvider, create_bedrock_provider

    p = create_bedrock_provider()
    assert isinstance(p, BedrockProvider)
    assert p._region == "us-east-1"


def test_create_bedrock_provider_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from ragrig.providers.cloud import BedrockProvider, create_bedrock_provider

    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    p = create_bedrock_provider()
    assert isinstance(p, BedrockProvider)
    assert p._region == "eu-west-1"


def test_registry_bedrock_returns_real_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from ragrig.providers import get_provider_registry
    from ragrig.providers.cloud import BedrockProvider

    monkeypatch.setitem(sys.modules, "boto3", _make_bedrock_client())
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIATEST")
    registry = get_provider_registry()
    p = registry.get("model.bedrock")
    assert isinstance(p, BedrockProvider)
