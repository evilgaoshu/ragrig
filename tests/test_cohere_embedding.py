"""Unit tests for the Cohere embedding provider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ragrig.providers import ProviderError
from ragrig.providers.cohere import (
    COHERE_EMBEDDING_METADATA,
    CohereEmbeddingProvider,
    create_cohere_embedding_provider,
)

pytestmark = pytest.mark.unit


def _make_mock_response(vector: list[float], status_code: int = 200):
    """Build a mock httpx.Response for Cohere embed."""
    mock_resp = MagicMock()
    mock_resp.is_success = status_code < 400
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {
        "embeddings": {"float": [vector]},
        "texts": ["sample"],
    }
    return mock_resp


def _make_batch_mock_response(vectors: list[list[float]], status_code: int = 200):
    mock_resp = MagicMock()
    mock_resp.is_success = status_code < 400
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {
        "embeddings": {"float": vectors},
        "texts": ["sample"] * len(vectors),
    }
    return mock_resp


class TestCohereProviderMetadata:
    def test_metadata_name(self) -> None:
        assert COHERE_EMBEDDING_METADATA.name == "embedding.cohere"

    def test_metadata_default_dimensions(self) -> None:
        assert COHERE_EMBEDDING_METADATA.default_dimensions == 1024

    def test_metadata_required_secrets(self) -> None:
        assert "COHERE_API_KEY" in COHERE_EMBEDDING_METADATA.required_secrets


class TestCohereEmbedText:
    def test_embed_text_returns_embedding_result(self) -> None:
        vector = [0.1, 0.2, 0.3]
        mock_resp = _make_mock_response(vector)
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp

        provider = create_cohere_embedding_provider(
            model_name="embed-v4.0",
            api_key="test-key",
            client=mock_client,
        )
        result = provider.embed_text("hello world")

        assert result.provider == "embedding.cohere"
        assert result.model == "embed-v4.0"
        assert result.dimensions == 3
        assert result.vector == [0.1, 0.2, 0.3]

    def test_embed_texts_returns_ordered_embedding_results(self) -> None:
        mock_resp = _make_batch_mock_response([[0.1, 0.2], [0.3, 0.4]])
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        provider = create_cohere_embedding_provider(
            model_name="embed-v4.0",
            api_key="test-key",
            client=mock_client,
        )
        results = provider.embed_texts(["alpha", "beta"])

        call_kwargs = mock_client.post.call_args
        body = call_kwargs[1].get("json") or call_kwargs.kwargs.get("json", {})
        assert body["texts"] == ["alpha", "beta"]
        assert [result.vector for result in results] == [[0.1, 0.2], [0.3, 0.4]]

    def test_embed_text_raises_on_missing_api_key(self) -> None:
        provider = CohereEmbeddingProvider(model_name="embed-v4.0")
        provider._config = {}
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ProviderError, match="COHERE_API_KEY"):
                provider.embed_text("hello")

    def test_embed_text_raises_on_401_response(self) -> None:
        mock_resp = MagicMock()
        mock_resp.is_success = False
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"message": "Unauthorized"}
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        provider = create_cohere_embedding_provider(
            api_key="bad-key",
            client=mock_client,
        )
        with pytest.raises(ProviderError, match="401"):
            provider.embed_text("hello")

    def test_embed_text_raises_on_malformed_response(self) -> None:
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"unexpected": "shape"}
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        provider = create_cohere_embedding_provider(
            api_key="key",
            client=mock_client,
        )
        with pytest.raises(ProviderError, match="unexpected response shape"):
            provider.embed_text("hello")

    def test_embed_text_uses_correct_input_type(self) -> None:
        vector = [0.5] * 10
        mock_resp = _make_mock_response(vector)
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        provider = create_cohere_embedding_provider(
            api_key="key",
            input_type="search_query",
            client=mock_client,
        )
        provider.embed_text("query text")

        call_kwargs = mock_client.post.call_args
        body = call_kwargs[1].get("json") or call_kwargs.kwargs.get("json", {})
        assert body["input_type"] == "search_query"


class TestCohereHealthCheck:
    def test_healthy_when_api_key_set(self) -> None:
        provider = create_cohere_embedding_provider(api_key="my-key")
        health = provider.health_check()
        assert health.status == "healthy"

    def test_unavailable_when_no_api_key(self) -> None:
        provider = CohereEmbeddingProvider()
        provider._config = {}
        with patch.dict("os.environ", {}, clear=True):
            health = provider.health_check()
        assert health.status == "unavailable"


class TestCreateCohereProvider:
    def test_factory_sets_model_name(self) -> None:
        provider = create_cohere_embedding_provider(
            model_name="embed-multilingual-v3.0",
            api_key="k",
        )
        assert provider.model_name == "embed-multilingual-v3.0"

    def test_factory_default_model_name(self) -> None:
        provider = create_cohere_embedding_provider(api_key="k")
        assert provider.model_name == "embed-v4.0"
