from __future__ import annotations

import pytest

from ragrig.providers import ProviderCapability, ProviderError, ProviderKind, get_provider_registry
from ragrig.providers.bge import load_bge_embedding_runtime, load_bge_reranker_runtime
from ragrig.providers.local import load_ollama_client, load_openai_compatible_client


class FakeOllamaClient:
    def __init__(self, *, models: list[str], embedding_models: list[str] | None = None) -> None:
        self._models = models
        self._embedding_models = embedding_models or []

    def list_models(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for name in self._models:
            items.append(
                {
                    "name": name,
                    "supports_embeddings": name in self._embedding_models,
                }
            )
        return items

    def generate(self, *, model: str, prompt: str) -> dict[str, object]:
        return {"model": model, "response": f"ollama:{prompt}"}

    def chat(self, *, model: str, messages: list[dict[str, object]]) -> dict[str, object]:
        return {
            "model": model,
            "message": {
                "role": "assistant",
                "content": f"ollama-chat:{messages[-1]['content']}",
            },
        }

    def embed(self, *, model: str, text: str) -> dict[str, object]:
        return {
            "model": model,
            "embedding": [0.1, 0.2, 0.3],
            "text": text,
        }


class FakeOpenAICompatibleClient:
    def __init__(self, *, models: list[str]) -> None:
        self._models = models

    def list_models(self) -> list[str]:
        return self._models

    def generate(self, *, base_url: str, model: str, prompt: str) -> str:
        return f"{base_url}:{model}:{prompt}"

    def chat(
        self,
        *,
        base_url: str,
        model: str,
        messages: list[dict[str, object]],
    ) -> dict[str, object]:
        return {
            "base_url": base_url,
            "model": model,
            "message": {
                "role": "assistant",
                "content": f"{model}:{messages[-1]['content']}",
            },
        }


class FakeBgeEmbedder:
    def encode(self, text: str) -> list[float]:
        del text
        return [0.4, 0.5, 0.6]


class FakeBgeReranker:
    def rerank(self, query: str, documents: list[str]) -> list[float]:
        del query
        return [round(1.0 - (index * 0.25), 2) for index, _ in enumerate(documents)]


def test_default_provider_registry_exposes_pr2_local_provider_contracts() -> None:
    registry = get_provider_registry()
    names = {metadata.name for metadata in registry.list()}

    assert {
        "deterministic-local",
        "model.ollama",
        "model.lm_studio",
        "model.llama_cpp",
        "model.vllm",
        "model.xinference",
        "model.localai",
        "embedding.bge",
        "reranker.bge",
    } <= names

    ollama = registry.read("model.ollama")
    assert ollama.kind is ProviderKind.LOCAL
    assert {
        ProviderCapability.CHAT,
        ProviderCapability.GENERATE,
        ProviderCapability.EMBEDDING,
    } <= ollama.capabilities
    assert ollama.required_secrets == []
    assert ollama.config_schema["host"]["default"] == "http://localhost:11434"

    bge_embedding = registry.read("embedding.bge")
    assert bge_embedding.kind is ProviderKind.LOCAL
    assert bge_embedding.required_secrets == []
    assert bge_embedding.sdk_protocol == "optional-local-ml"


def test_ollama_provider_uses_fake_client_for_generation_chat_embedding_and_health() -> None:
    provider = get_provider_registry().get(
        "model.ollama",
        host="http://ollama.test",
        model_name="llama3.2",
        embedding_model_name="nomic-embed-text",
        client=FakeOllamaClient(
            models=["llama3.2", "nomic-embed-text"], embedding_models=["nomic-embed-text"]
        ),
    )

    health = provider.health_check()
    generated = provider.generate("hello")
    chat = provider.chat([{"role": "user", "content": "hi"}])
    embedding = provider.embed_text("fixture")

    assert health.status == "healthy"
    assert health.metrics == {
        "host": "http://ollama.test",
        "model_count": 2,
        "embedding_model": "nomic-embed-text",
    }
    assert provider.list_models() == [
        {"name": "llama3.2", "supports_embeddings": False},
        {"name": "nomic-embed-text", "supports_embeddings": True},
    ]
    assert generated == "ollama:hello"
    assert chat["message"]["content"] == "ollama-chat:hi"
    assert embedding.provider == "model.ollama"
    assert embedding.model == "nomic-embed-text"
    assert embedding.dimensions == 3


def test_ollama_provider_reports_embedding_not_supported_for_selected_model() -> None:
    provider = get_provider_registry().get(
        "model.ollama",
        host="http://ollama.test",
        model_name="llama3.2",
        client=FakeOllamaClient(models=["llama3.2"]),
    )

    with pytest.raises(ProviderError) as exc:
        provider.embed_text("fixture")

    assert exc.value.code == "embedding_not_supported"
    assert exc.value.details == {
        "provider": "model.ollama",
        "model": "llama3.2",
    }


@pytest.mark.parametrize(
    ("provider_name", "base_url"),
    [
        ("model.lm_studio", "http://localhost:1234/v1"),
        ("model.llama_cpp", "http://localhost:8080/v1"),
        ("model.vllm", "http://localhost:8000/v1"),
        ("model.xinference", "http://localhost:9997/v1"),
        ("model.localai", "http://localhost:8080/v1"),
    ],
)
def test_openai_compatible_local_providers_share_fake_client_contract(
    provider_name: str,
    base_url: str,
) -> None:
    provider = get_provider_registry().get(
        provider_name,
        base_url=base_url,
        model_name="qwen2.5",
        client=FakeOpenAICompatibleClient(models=["qwen2.5", "phi-4"]),
    )

    health = provider.health_check()

    assert health.status == "healthy"
    assert health.metrics == {"base_url": base_url, "model_count": 2}
    assert provider.list_models() == ["qwen2.5", "phi-4"]
    assert provider.generate("hello") == f"{base_url}:qwen2.5:hello"
    assert provider.chat([{"role": "user", "content": "hi"}])["message"]["content"] == "qwen2.5:hi"


def test_bge_embedding_and_reranker_support_fake_runtimes() -> None:
    registry = get_provider_registry()
    embedding_provider = registry.get(
        "embedding.bge",
        model_name="BAAI/bge-small-en-v1.5",
        runtime=FakeBgeEmbedder(),
    )
    reranker_provider = registry.get(
        "reranker.bge",
        model_name="BAAI/bge-reranker-base",
        runtime=FakeBgeReranker(),
    )

    embedding = embedding_provider.embed_text("fixture")
    ranked = reranker_provider.rerank("query", ["alpha", "beta", "gamma"])

    assert embedding.provider == "embedding.bge"
    assert embedding.model == "BAAI/bge-small-en-v1.5"
    assert embedding.dimensions == 3
    assert ranked == [
        {"document": "alpha", "index": 0, "score": 1.0},
        {"document": "beta", "index": 1, "score": 0.75},
        {"document": "gamma", "index": 2, "score": 0.5},
    ]


def test_bge_embedding_provider_returns_clear_optional_dependency_error(monkeypatch) -> None:
    def _raise_missing_dependency(model_name: str):
        del model_name
        raise ProviderError(
            "BGE embedding provider requires optional local ML dependencies",
            code="optional_dependency_missing",
            retryable=False,
            details={
                "provider": "embedding.bge",
                "dependencies": ["FlagEmbedding", "sentence-transformers", "torch"],
            },
        )

    monkeypatch.setattr(
        "ragrig.providers.bge.load_bge_embedding_runtime", _raise_missing_dependency
    )
    provider = get_provider_registry().get("embedding.bge", model_name="BAAI/bge-small-en-v1.5")

    with pytest.raises(ProviderError) as exc:
        provider.embed_text("fixture")

    assert exc.value.code == "optional_dependency_missing"
    assert exc.value.details["provider"] == "embedding.bge"


def test_direct_optional_dependency_loaders_return_structured_errors() -> None:
    with pytest.raises(ProviderError) as ollama_exc:
        load_ollama_client()
    with pytest.raises(ProviderError) as openai_exc:
        load_openai_compatible_client(provider="model.lm_studio")
    with pytest.raises(ProviderError) as bge_embed_exc:
        load_bge_embedding_runtime("BAAI/bge-small-en-v1.5")
    with pytest.raises(ProviderError) as bge_rerank_exc:
        load_bge_reranker_runtime("BAAI/bge-reranker-base")

    assert ollama_exc.value.details == {"provider": "model.ollama", "dependencies": ["ollama"]}
    assert openai_exc.value.details == {"provider": "model.lm_studio", "dependencies": ["openai"]}
    assert bge_embed_exc.value.details == {
        "provider": "embedding.bge",
        "dependencies": ["FlagEmbedding", "sentence-transformers", "torch"],
    }
    assert bge_rerank_exc.value.details == {
        "provider": "reranker.bge",
        "dependencies": ["FlagEmbedding", "sentence-transformers", "torch"],
    }
