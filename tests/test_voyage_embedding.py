"""Unit tests for the Voyage AI embedding provider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ragrig.providers import ProviderError
from ragrig.providers.voyage import (
    VOYAGE_EMBEDDING_METADATA,
    VoyageEmbeddingProvider,
    create_voyage_embedding_provider,
)

pytestmark = pytest.mark.unit


def _make_mock_response(vector: list[float], status_code: int = 200):
    """Build a mock httpx.Response for Voyage embed."""
    mock_resp = MagicMock()
    mock_resp.is_success = status_code < 400
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {
        "data": [{"embedding": vector, "index": 0}],
        "model": "voyage-3",
    }
    return mock_resp


def _make_batch_mock_response(vectors: list[list[float]], status_code: int = 200):
    mock_resp = MagicMock()
    mock_resp.is_success = status_code < 400
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {
        "data": [{"embedding": vector, "index": index} for index, vector in enumerate(vectors)],
        "model": "voyage-3",
    }
    return mock_resp


class TestVoyageProviderMetadata:
    def test_metadata_name(self) -> None:
        assert VOYAGE_EMBEDDING_METADATA.name == "embedding.voyage"

    def test_metadata_default_dimensions(self) -> None:
        assert VOYAGE_EMBEDDING_METADATA.default_dimensions == 1024

    def test_metadata_required_secrets(self) -> None:
        assert "VOYAGE_API_KEY" in VOYAGE_EMBEDDING_METADATA.required_secrets


class TestVoyageEmbedText:
    def test_embed_text_returns_embedding_result(self) -> None:
        vector = [0.1, 0.2, 0.3, 0.4]
        mock_resp = _make_mock_response(vector)
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        provider = create_voyage_embedding_provider(
            model_name="voyage-3",
            api_key="test-key",
            client=mock_client,
        )
        result = provider.embed_text("hello world")

        assert result.provider == "embedding.voyage"
        assert result.model == "voyage-3"
        assert result.dimensions == 4
        assert result.vector == [0.1, 0.2, 0.3, 0.4]

    def test_embed_texts_returns_ordered_embedding_results(self) -> None:
        mock_resp = _make_batch_mock_response([[0.1, 0.2], [0.3, 0.4]])
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        provider = create_voyage_embedding_provider(
            model_name="voyage-3",
            api_key="test-key",
            client=mock_client,
        )
        results = provider.embed_texts(["alpha", "beta"])

        call_kwargs = mock_client.post.call_args
        body = call_kwargs[1].get("json") or call_kwargs.kwargs.get("json", {})
        assert body["input"] == ["alpha", "beta"]
        assert [result.vector for result in results] == [[0.1, 0.2], [0.3, 0.4]]

    def test_embed_text_raises_on_missing_api_key(self) -> None:
        provider = VoyageEmbeddingProvider(model_name="voyage-3")
        provider._config = {}
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ProviderError, match="VOYAGE_API_KEY"):
                provider.embed_text("hello")

    def test_embed_text_raises_on_403_response(self) -> None:
        mock_resp = MagicMock()
        mock_resp.is_success = False
        mock_resp.status_code = 403
        mock_resp.json.return_value = {"message": "Forbidden"}
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        provider = create_voyage_embedding_provider(
            api_key="bad-key",
            client=mock_client,
        )
        with pytest.raises(ProviderError, match="403"):
            provider.embed_text("hello")

    def test_embed_text_raises_on_malformed_response(self) -> None:
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"unexpected": "shape"}
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        provider = create_voyage_embedding_provider(
            api_key="key",
            client=mock_client,
        )
        with pytest.raises(ProviderError, match="unexpected response shape"):
            provider.embed_text("hello")

    def test_embed_text_sends_correct_model_in_body(self) -> None:
        vector = [0.5] * 8
        mock_resp = _make_mock_response(vector)
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        provider = create_voyage_embedding_provider(
            api_key="key",
            model_name="voyage-code-3",
            client=mock_client,
        )
        provider.embed_text("some code")

        call_kwargs = mock_client.post.call_args
        body = call_kwargs[1].get("json") or call_kwargs.kwargs.get("json", {})
        assert body["model"] == "voyage-code-3"

    def test_embed_text_sends_input_type_in_body(self) -> None:
        vector = [0.1] * 4
        mock_resp = _make_mock_response(vector)
        mock_client = MagicMock()
        mock_client.post.return_value = mock_resp

        provider = create_voyage_embedding_provider(
            api_key="key",
            input_type="query",
            client=mock_client,
        )
        provider.embed_text("search query")

        call_kwargs = mock_client.post.call_args
        body = call_kwargs[1].get("json") or call_kwargs.kwargs.get("json", {})
        assert body["input_type"] == "query"


class TestVoyageHealthCheck:
    def test_healthy_when_api_key_set(self) -> None:
        provider = create_voyage_embedding_provider(api_key="my-key")
        health = provider.health_check()
        assert health.status == "healthy"

    def test_unavailable_when_no_api_key(self) -> None:
        provider = VoyageEmbeddingProvider()
        provider._config = {}
        with patch.dict("os.environ", {}, clear=True):
            health = provider.health_check()
        assert health.status == "unavailable"


class TestCreateVoyageProvider:
    def test_factory_sets_model_name(self) -> None:
        provider = create_voyage_embedding_provider(
            model_name="voyage-3-lite",
            api_key="k",
        )
        assert provider.model_name == "voyage-3-lite"

    def test_factory_default_model_name(self) -> None:
        provider = create_voyage_embedding_provider(api_key="k")
        assert provider.model_name == "voyage-3"
