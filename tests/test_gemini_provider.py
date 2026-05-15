from __future__ import annotations

import pytest

from ragrig.providers import ProviderCapability
from ragrig.providers.cloud import GeminiProvider

pytestmark = pytest.mark.unit


class FakeGeminiModels:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def generate_content(self, *, model, contents):
        self.calls.append((model, contents))

        class Response:
            text = "Grounded answer [cit-1]"

        return Response()


class FakeGeminiClient:
    def __init__(self) -> None:
        self.models = FakeGeminiModels()


def test_gemini_provider_health_ready_with_client() -> None:
    provider = GeminiProvider(
        api_key="secret",
        model_name="gemini-2.5-flash",
        client=FakeGeminiClient(),
    )

    health = provider.health_check()

    assert health.status == "healthy"
    assert health.metrics["model"] == "gemini-2.5-flash"


def test_gemini_provider_chat_returns_openai_like_shape() -> None:
    client = FakeGeminiClient()
    provider = GeminiProvider(
        api_key="secret",
        model_name="gemini-2.5-flash",
        client=client,
    )

    result = provider.chat([{"role": "user", "content": "Question with [cit-1] evidence"}])

    assert result["choices"][0]["message"]["content"] == "Grounded answer [cit-1]"
    assert client.models.calls[0][0] == "gemini-2.5-flash"
    assert ProviderCapability.CHAT in provider.metadata.capabilities


def test_gemini_provider_health_unavailable_without_secret(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    provider = GeminiProvider()

    health = provider.health_check()

    assert health.status == "unavailable"
    assert "GEMINI_API_KEY" in health.detail
