from __future__ import annotations

import pytest

from ragrig.providers.model_catalog import (
    MAINSTREAM_MODEL_PROVIDERS,
    list_provider_models,
    measure_provider_latency,
)

pytestmark = pytest.mark.unit


class FakeModelTransport:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[dict[str, object]] = []

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        json_body: dict[str, object] | None = None,
        timeout_seconds: float = 10.0,
    ) -> tuple[int, dict[str, str], dict[str, object], float]:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "json_body": json_body,
                "timeout_seconds": timeout_seconds,
            }
        )
        return 200, {"content-type": "application/json"}, self.payload, 42.5


def test_mainstream_model_provider_catalog_covers_required_vendors_and_protocols() -> None:
    names = set(MAINSTREAM_MODEL_PROVIDERS)

    assert {
        "model.openai",
        "model.azure_openai",
        "model.anthropic",
        "model.google_gemini",
        "model.bedrock",
        "model.mistral",
        "model.cohere",
        "model.openrouter",
        "model.together",
        "model.fireworks",
        "model.groq",
        "model.deepseek",
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
        "model.ollama",
        "model.lm_studio",
        "model.llama_cpp",
        "model.vllm",
        "model.xinference",
        "model.localai",
        "embedding.bge",
        "reranker.bge",
    } <= names

    protocols = {spec.protocol for spec in MAINSTREAM_MODEL_PROVIDERS.values()}
    assert {
        "openai-compatible",
        "anthropic",
        "gemini",
        "bedrock",
        "ollama",
        "local-runtime",
    } <= protocols

    for provider_name, spec in MAINSTREAM_MODEL_PROVIDERS.items():
        assert spec.official_docs_url.startswith("https://"), provider_name
        assert spec.list_models_supported is not None, provider_name
        assert spec.auth_env_vars is not None, provider_name


def test_list_provider_models_missing_credentials_is_degraded_without_network() -> None:
    transport = FakeModelTransport({"data": [{"id": "should-not-call"}]})

    result = list_provider_models("model.openai", env={}, transport=transport)

    assert result["status"] == "missing_credentials"
    assert result["provider"] == "model.openai"
    assert result["models"] == []
    assert result["missing_credentials"] == ["OPENAI_API_KEY"]
    assert result["official_docs_url"].startswith("https://")
    assert transport.calls == []


@pytest.mark.parametrize(
    ("provider_name", "payload", "expected"),
    [
        (
            "model.openai",
            {"data": [{"id": "gpt-5.2"}, {"id": "text-embedding-3-large"}]},
            ["gpt-5.2", "text-embedding-3-large"],
        ),
        (
            "model.anthropic",
            {"data": [{"id": "claude-opus-4-1-20250805"}]},
            ["claude-opus-4-1-20250805"],
        ),
        ("model.google_gemini", {"models": [{"name": "models/gemini-3-pro"}]}, ["gemini-3-pro"]),
        (
            "model.bedrock",
            {"modelSummaries": [{"modelId": "anthropic.claude-sonnet-4-5"}]},
            ["anthropic.claude-sonnet-4-5"],
        ),
        ("model.cohere", {"models": [{"name": "command-r-plus"}]}, ["command-r-plus"]),
    ],
)
def test_list_provider_models_parses_official_response_shapes(
    provider_name: str,
    payload: dict[str, object],
    expected: list[str],
) -> None:
    transport = FakeModelTransport(payload)

    result = list_provider_models(
        provider_name,
        env={
            "OPENAI_API_KEY": "sk-test",
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "GOOGLE_API_KEY": "google-test",
            "AWS_ACCESS_KEY_ID": "aws",
            "AWS_SECRET_ACCESS_KEY": "aws-secret",
            "AWS_REGION": "us-east-1",
            "COHERE_API_KEY": "co-test",
        },
        transport=transport,
    )

    assert result["status"] == "ready"
    assert [item["id"] for item in result["models"]] == expected
    assert result["latency_ms"] == 42.5
    assert transport.calls[0]["method"] == "GET"


def test_measure_provider_latency_uses_model_listing_probe() -> None:
    transport = FakeModelTransport({"data": [{"id": "gpt-5.2"}]})

    result = measure_provider_latency(
        "model.openai",
        env={"OPENAI_API_KEY": "sk-test"},
        transport=transport,
    )

    assert result["status"] == "ready"
    assert result["measurement"] == "model_list_latency_ms"
    assert result["latency_ms"] == 42.5
    assert result["model_count"] == 1
