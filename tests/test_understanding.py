from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from ragrig.db.models import DocumentUnderstanding, DocumentVersion
from ragrig.understanding.provider import (
    DeterministicUnderstandingProvider,
    compute_input_hash,
    get_understanding_provider,
)
from ragrig.understanding.schema import UnderstandingResult
from ragrig.understanding.service import (
    DocumentVersionNotFoundError,
    ProviderUnavailableError,
    delete_document_understanding,
    generate_document_understanding,
    get_understanding_by_version,
)

pytestmark = [pytest.mark.integration, pytest.mark.slow]

class TestComputeInputHash:
    def test_hash_is_deterministic(self) -> None:
        h1 = compute_input_hash("text", "profile", "provider", "model")
        h2 = compute_input_hash("text", "profile", "provider", "model")
        assert h1 == h2
        assert len(h1) == 64

    def test_hash_differs_on_input_change(self) -> None:
        h1 = compute_input_hash("text1", "profile", "provider", "model")
        h2 = compute_input_hash("text2", "profile", "provider", "model")
        assert h1 != h2


class TestDeterministicUnderstandingProvider:
    def test_empty_text_returns_empty_result(self) -> None:
        prov = DeterministicUnderstandingProvider()
        result = prov.generate("")
        assert result.summary == ""
        assert result.limitations == ["Empty input text: no content to analyze."]
        assert result.table_of_contents == []
        assert result.entities == []

    def test_markdown_headings_extracted(self) -> None:
        prov = DeterministicUnderstandingProvider()
        text = "# Hello\n\n## World\n\nContent here."
        result = prov.generate(text)
        assert len(result.table_of_contents) == 2
        assert result.table_of_contents[0].level == 1
        assert result.table_of_contents[0].title == "Hello"
        assert result.table_of_contents[1].level == 2
        assert result.table_of_contents[1].title == "World"

    def test_no_headings_fallback(self) -> None:
        prov = DeterministicUnderstandingProvider()
        result = prov.generate("Just plain text without any headings.")
        assert len(result.table_of_contents) == 1
        assert result.table_of_contents[0].title == "Content"

    def test_short_document_limitation(self) -> None:
        prov = DeterministicUnderstandingProvider()
        result = prov.generate("Short.")
        assert any("short" in lim.lower() for lim in result.limitations)

    def test_entities_extracted_from_capitalized_words(self) -> None:
        prov = DeterministicUnderstandingProvider()
        text = "RAGRig is a platform. PostgreSQL is used."
        result = prov.generate(text)
        assert len(result.entities) > 0

    def test_result_is_valid_schema(self) -> None:
        prov = DeterministicUnderstandingProvider()
        result = prov.generate("# Title\n\nSome content here.")
        parsed = UnderstandingResult.model_validate(result.model_dump())
        assert parsed.summary is not None


class TestGetUnderstandingProvider:
    def test_returns_deterministic_provider(self) -> None:
        prov = get_understanding_provider("deterministic-local")
        assert isinstance(prov, DeterministicUnderstandingProvider)

    def test_raises_for_unregistered_provider(self) -> None:
        from ragrig.providers import ProviderError

        with pytest.raises(ProviderError) as exc_info:
            get_understanding_provider("nonexistent-provider")
        assert exc_info.value.code == "provider_not_registered"


class TestDeterministicProviderEdgeCases:
    def test_extracts_up_to_five_entities(self) -> None:
        prov = DeterministicUnderstandingProvider()
        text = "Alpha Beta Gamma Delta Epsilon Zeta Eta Theta"
        result = prov.generate(text)
        assert len(result.entities) == 5

    def test_extracts_h3_headings(self) -> None:
        prov = DeterministicUnderstandingProvider()
        result = prov.generate("# H1\n## H2\n### H3")
        assert len(result.table_of_contents) == 3
        assert result.table_of_contents[2].level == 3
        assert result.table_of_contents[2].title == "H3"

    def test_no_entities_when_no_capitalized_words(self) -> None:
        prov = DeterministicUnderstandingProvider()
        result = prov.generate("all lowercase words here")
        assert result.entities == []


class TestLLMUnderstandingProvider:
    def test_chat_path_with_valid_json_response(self) -> None:
        from ragrig.providers import (
            BaseProvider,
            ProviderCapability,
            ProviderKind,
            ProviderMetadata,
        )

        class FakeProvider(BaseProvider):
            metadata = ProviderMetadata(
                name="fake",
                kind=ProviderKind.LOCAL,
                description="fake",
                capabilities={ProviderCapability.CHAT},
                default_dimensions=None,
                max_dimensions=None,
                default_context_window=None,
                max_context_window=None,
                required_secrets=[],
                config_schema={},
                sdk_protocol="fake",
                healthcheck="fake",
                failure_modes=[],
                retry_policy=object(),  # type: ignore[arg-type]
                audit_fields=[],
                metric_fields=[],
                intended_uses=[],
            )

            def chat(self, messages: list[dict[str, object]]) -> dict[str, object]:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"summary": "test", "table_of_contents": [], '
                                    '"entities": [], "key_claims": [], '
                                    '"limitations": [], "source_spans": []}'
                                )
                            }
                        }
                    ]
                }

        from ragrig.understanding.provider import LLMUnderstandingProvider

        prov = LLMUnderstandingProvider(FakeProvider())
        result = prov.generate("some text")
        assert result.summary == "test"

    def test_generate_fallback_path(self) -> None:
        from ragrig.providers import (
            BaseProvider,
            ProviderCapability,
            ProviderKind,
            ProviderMetadata,
        )

        class FakeProvider(BaseProvider):
            metadata = ProviderMetadata(
                name="fake",
                kind=ProviderKind.LOCAL,
                description="fake",
                capabilities={ProviderCapability.GENERATE},
                default_dimensions=None,
                max_dimensions=None,
                default_context_window=None,
                max_context_window=None,
                required_secrets=[],
                config_schema={},
                sdk_protocol="fake",
                healthcheck="fake",
                failure_modes=[],
                retry_policy=object(),  # type: ignore[arg-type]
                audit_fields=[],
                metric_fields=[],
                intended_uses=[],
            )

            def generate(self, prompt: str) -> str:
                return (
                    '{"summary": "fallback", "table_of_contents": [], '
                    '"entities": [], "key_claims": [], '
                    '"limitations": [], "source_spans": []}'
                )

        from ragrig.understanding.provider import LLMUnderstandingProvider

        prov = LLMUnderstandingProvider(FakeProvider())
        result = prov.generate("some text")
        assert result.summary == "fallback"

    def test_raises_on_invalid_json(self) -> None:
        from ragrig.providers import (
            BaseProvider,
            ProviderCapability,
            ProviderError,
            ProviderKind,
            ProviderMetadata,
        )

        class FakeProvider(BaseProvider):
            metadata = ProviderMetadata(
                name="fake",
                kind=ProviderKind.LOCAL,
                description="fake",
                capabilities={ProviderCapability.CHAT},
                default_dimensions=None,
                max_dimensions=None,
                default_context_window=None,
                max_context_window=None,
                required_secrets=[],
                config_schema={},
                sdk_protocol="fake",
                healthcheck="fake",
                failure_modes=[],
                retry_policy=object(),  # type: ignore[arg-type]
                audit_fields=[],
                metric_fields=[],
                intended_uses=[],
            )

            def chat(self, messages: list[dict[str, object]]) -> dict[str, object]:
                return {"choices": [{"message": {"content": "not json"}}]}

        from ragrig.understanding.provider import LLMUnderstandingProvider

        prov = LLMUnderstandingProvider(FakeProvider())
        with pytest.raises(ProviderError) as exc_info:
            prov.generate("some text")
        assert exc_info.value.code == "understanding_schema_invalid"

    def test_strips_markdown_code_blocks(self) -> None:
        from ragrig.providers import (
            BaseProvider,
            ProviderCapability,
            ProviderKind,
            ProviderMetadata,
        )

        class FakeProvider(BaseProvider):
            metadata = ProviderMetadata(
                name="fake",
                kind=ProviderKind.LOCAL,
                description="fake",
                capabilities={ProviderCapability.CHAT},
                default_dimensions=None,
                max_dimensions=None,
                default_context_window=None,
                max_context_window=None,
                required_secrets=[],
                config_schema={},
                sdk_protocol="fake",
                healthcheck="fake",
                failure_modes=[],
                retry_policy=object(),  # type: ignore[arg-type]
                audit_fields=[],
                metric_fields=[],
                intended_uses=[],
            )

            def chat(self, messages: list[dict[str, object]]) -> dict[str, object]:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    "```json\n"
                                    '{"summary": "stripped", "table_of_contents": [], '
                                    '"entities": [], "key_claims": [], '
                                    '"limitations": [], "source_spans": []}\n'
                                    "```"
                                )
                            }
                        }
                    ]
                }

        from ragrig.understanding.provider import LLMUnderstandingProvider

        prov = LLMUnderstandingProvider(FakeProvider())
        result = prov.generate("some text")
        assert result.summary == "stripped"

    def test_response_key_path(self) -> None:
        from ragrig.providers import (
            BaseProvider,
            ProviderCapability,
            ProviderKind,
            ProviderMetadata,
        )

        class FakeProvider(BaseProvider):
            metadata = ProviderMetadata(
                name="fake",
                kind=ProviderKind.LOCAL,
                description="fake",
                capabilities={ProviderCapability.CHAT},
                default_dimensions=None,
                max_dimensions=None,
                default_context_window=None,
                max_context_window=None,
                required_secrets=[],
                config_schema={},
                sdk_protocol="fake",
                healthcheck="fake",
                failure_modes=[],
                retry_policy=object(),  # type: ignore[arg-type]
                audit_fields=[],
                metric_fields=[],
                intended_uses=[],
            )

            def chat(self, messages: list[dict[str, object]]) -> dict[str, object]:
                return {
                    "response": (
                        '{"summary": "response-key", "table_of_contents": [], '
                        '"entities": [], "key_claims": [], '
                        '"limitations": [], "source_spans": []}'
                    )
                }

        from ragrig.understanding.provider import LLMUnderstandingProvider

        prov = LLMUnderstandingProvider(FakeProvider())
        result = prov.generate("some text")
        assert result.summary == "response-key"

    def test_content_key_path(self) -> None:
        from ragrig.providers import (
            BaseProvider,
            ProviderCapability,
            ProviderKind,
            ProviderMetadata,
        )

        class FakeProvider(BaseProvider):
            metadata = ProviderMetadata(
                name="fake",
                kind=ProviderKind.LOCAL,
                description="fake",
                capabilities={ProviderCapability.CHAT},
                default_dimensions=None,
                max_dimensions=None,
                default_context_window=None,
                max_context_window=None,
                required_secrets=[],
                config_schema={},
                sdk_protocol="fake",
                healthcheck="fake",
                failure_modes=[],
                retry_policy=object(),  # type: ignore[arg-type]
                audit_fields=[],
                metric_fields=[],
                intended_uses=[],
            )

            def chat(self, messages: list[dict[str, object]]) -> dict[str, object]:
                return {
                    "content": (
                        '{"summary": "content-key", "table_of_contents": [], '
                        '"entities": [], "key_claims": [], '
                        '"limitations": [], "source_spans": []}'
                    )
                }

        from ragrig.understanding.provider import LLMUnderstandingProvider

        prov = LLMUnderstandingProvider(FakeProvider())
        result = prov.generate("some text")
        assert result.summary == "content-key"

    def test_get_provider_rejects_embedding_only_provider(self) -> None:
        from ragrig.providers import (
            ProviderCapability,
            ProviderError,
            ProviderKind,
            ProviderMetadata,
            ProviderRegistry,
            ProviderRetryPolicy,
        )

        fake_metadata = ProviderMetadata(
            name="embedding-only",
            kind=ProviderKind.LOCAL,
            description="fake embedding only",
            capabilities={ProviderCapability.EMBEDDING},
            default_dimensions=8,
            max_dimensions=8,
            default_context_window=None,
            max_context_window=None,
            required_secrets=[],
            config_schema={},
            sdk_protocol="fake",
            healthcheck="fake",
            failure_modes=[],
            retry_policy=ProviderRetryPolicy(max_attempts=1, backoff_seconds=0.0),
            audit_fields=[],
            metric_fields=[],
            intended_uses=[],
        )

        class FakeProvider:
            metadata = fake_metadata

        registry = ProviderRegistry()
        registry.register(fake_metadata, lambda **config: FakeProvider())

        # Temporarily swap global registry
        import ragrig.providers as providers_mod

        original = providers_mod._provider_registry
        providers_mod._provider_registry = registry
        try:
            with pytest.raises(ProviderError) as exc_info:
                get_understanding_provider("embedding-only")
            assert exc_info.value.code == "unsupported_capability"
        finally:
            providers_mod._provider_registry = original

    def test_strips_plain_code_block(self) -> None:
        from ragrig.providers import (
            BaseProvider,
            ProviderCapability,
            ProviderKind,
            ProviderMetadata,
        )

        class FakeProvider(BaseProvider):
            metadata = ProviderMetadata(
                name="fake",
                kind=ProviderKind.LOCAL,
                description="fake",
                capabilities={ProviderCapability.CHAT},
                default_dimensions=None,
                max_dimensions=None,
                default_context_window=None,
                max_context_window=None,
                required_secrets=[],
                config_schema={},
                sdk_protocol="fake",
                healthcheck="fake",
                failure_modes=[],
                retry_policy=object(),  # type: ignore[arg-type]
                audit_fields=[],
                metric_fields=[],
                intended_uses=[],
            )

            def chat(self, messages: list[dict[str, object]]) -> dict[str, object]:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    "```\n"
                                    '{"summary": "plain-block", "table_of_contents": [], '
                                    '"entities": [], "key_claims": [], '
                                    '"limitations": [], "source_spans": []}\n'
                                    "```"
                                )
                            }
                        }
                    ]
                }

        from ragrig.understanding.provider import LLMUnderstandingProvider

        prov = LLMUnderstandingProvider(FakeProvider())
        result = prov.generate("some text")
        assert result.summary == "plain-block"

    def test_get_provider_returns_llm_provider_for_chat_capable(self) -> None:
        from ragrig.providers import (
            ProviderCapability,
            ProviderKind,
            ProviderMetadata,
            ProviderRegistry,
            ProviderRetryPolicy,
        )

        fake_metadata = ProviderMetadata(
            name="chat-capable",
            kind=ProviderKind.LOCAL,
            description="fake chat",
            capabilities={ProviderCapability.CHAT},
            default_dimensions=None,
            max_dimensions=None,
            default_context_window=None,
            max_context_window=None,
            required_secrets=[],
            config_schema={},
            sdk_protocol="fake",
            healthcheck="fake",
            failure_modes=[],
            retry_policy=ProviderRetryPolicy(max_attempts=1, backoff_seconds=0.0),
            audit_fields=[],
            metric_fields=[],
            intended_uses=[],
        )

        class FakeProvider:
            metadata = fake_metadata

        registry = ProviderRegistry()
        registry.register(fake_metadata, lambda **config: FakeProvider())

        import ragrig.providers as providers_mod

        original = providers_mod._provider_registry
        providers_mod._provider_registry = registry
        try:
            prov = get_understanding_provider("chat-capable")
            from ragrig.understanding.provider import LLMUnderstandingProvider

            assert isinstance(prov, LLMUnderstandingProvider)
        finally:
            providers_mod._provider_registry = original


class TestUnderstandingSchema:
    def test_from_raw_with_invalid_input(self) -> None:
        result = UnderstandingResult.from_raw("not a dict")
        assert result.summary is None
        assert result.table_of_contents == []

    def test_from_raw_with_partial_dict(self) -> None:
        result = UnderstandingResult.from_raw({"summary": "hello"})
        assert result.summary == "hello"
        assert result.entities == []


class TestProviderUnavailableError:
    def test_error_attributes(self) -> None:

        exc = ProviderUnavailableError("my-provider", "connection refused")
        assert exc.code == "provider_unavailable"
        assert "my-provider" in str(exc)


class TestServiceProviderFailure:
    def test_provider_failure_marks_failed_and_raises(self, sqlite_session: Session) -> None:
        from ragrig.ingestion.pipeline import ingest_local_directory

        ingest_local_directory(
            session=sqlite_session,
            knowledge_base_name="test-kb",
            root_path=Path("tests/fixtures/local_ingestion"),
        )
        version = sqlite_session.query(DocumentVersion).first()
        assert version is not None

        with pytest.raises(ProviderUnavailableError) as exc_info:
            generate_document_understanding(
                sqlite_session,
                document_version_id=str(version.id),
                provider="nonexistent-provider",
            )
        assert exc_info.value.code == "provider_unavailable"

        # Verify the row was marked failed
        row = sqlite_session.query(DocumentUnderstanding).first()
        assert row is not None
        assert row.status == "failed"


class TestGenerateDocumentUnderstanding:
    def test_raises_when_version_not_found(self, sqlite_session: Session) -> None:
        with pytest.raises(DocumentVersionNotFoundError):
            generate_document_understanding(sqlite_session, document_version_id=str(uuid.uuid4()))

    def test_generates_and_persists_result(self, sqlite_session: Session) -> None:
        from ragrig.ingestion.pipeline import ingest_local_directory

        # Seed a document
        ingest_local_directory(
            session=sqlite_session,
            knowledge_base_name="test-kb",
            root_path=Path("tests/fixtures/local_ingestion"),
        )
        version = sqlite_session.query(DocumentVersion).first()
        assert version is not None

        record = generate_document_understanding(
            sqlite_session,
            document_version_id=str(version.id),
            provider="deterministic-local",
        )

        assert record.status == "completed"
        assert record.result["summary"] is not None
        assert record.document_version_id == str(version.id)

        # Verify persisted
        row = sqlite_session.query(DocumentUnderstanding).first()
        assert row is not None
        assert row.status == "completed"

    def test_idempotency_same_hash(self, sqlite_session: Session) -> None:
        from ragrig.ingestion.pipeline import ingest_local_directory

        ingest_local_directory(
            session=sqlite_session,
            knowledge_base_name="test-kb",
            root_path=Path("tests/fixtures/local_ingestion"),
        )
        version = sqlite_session.query(DocumentVersion).first()
        assert version is not None

        record1 = generate_document_understanding(
            sqlite_session,
            document_version_id=str(version.id),
            provider="deterministic-local",
        )
        record2 = generate_document_understanding(
            sqlite_session,
            document_version_id=str(version.id),
            provider="deterministic-local",
        )

        assert record1.id == record2.id
        assert sqlite_session.query(DocumentUnderstanding).count() == 1

    def test_overwrite_on_text_change(self, sqlite_session: Session) -> None:
        from ragrig.ingestion.pipeline import ingest_local_directory

        ingest_local_directory(
            session=sqlite_session,
            knowledge_base_name="test-kb",
            root_path=Path("tests/fixtures/local_ingestion"),
        )
        version = sqlite_session.query(DocumentVersion).first()
        assert version is not None

        record1 = generate_document_understanding(
            sqlite_session,
            document_version_id=str(version.id),
            provider="deterministic-local",
        )

        # Change text to invalidate hash
        version.extracted_text = version.extracted_text + " modified"
        sqlite_session.flush()

        record2 = generate_document_understanding(
            sqlite_session,
            document_version_id=str(version.id),
            provider="deterministic-local",
        )

        assert record1.id == record2.id
        assert record2.status == "completed"
        assert sqlite_session.query(DocumentUnderstanding).count() == 1

    def test_empty_extracted_text(self, sqlite_session: Session) -> None:
        from ragrig.ingestion.pipeline import ingest_local_directory

        ingest_local_directory(
            session=sqlite_session,
            knowledge_base_name="test-kb",
            root_path=Path("tests/fixtures/local_ingestion"),
        )
        version = sqlite_session.query(DocumentVersion).first()
        assert version is not None
        version.extracted_text = ""
        sqlite_session.flush()

        record = generate_document_understanding(
            sqlite_session,
            document_version_id=str(version.id),
            provider="deterministic-local",
        )
        assert record.status == "completed"
        assert record.result["summary"] == ""
        assert any("empty" in lim.lower() for lim in record.result.get("limitations", []))


class TestGetUnderstandingByVersion:
    def test_returns_none_when_missing(self, sqlite_session: Session) -> None:
        result = get_understanding_by_version(sqlite_session, str(uuid.uuid4()))
        assert result is None

    def test_returns_record_when_exists(self, sqlite_session: Session) -> None:
        from ragrig.ingestion.pipeline import ingest_local_directory

        ingest_local_directory(
            session=sqlite_session,
            knowledge_base_name="test-kb",
            root_path=Path("tests/fixtures/local_ingestion"),
        )
        version = sqlite_session.query(DocumentVersion).first()
        assert version is not None

        generate_document_understanding(
            sqlite_session,
            document_version_id=str(version.id),
            provider="deterministic-local",
        )

        record = get_understanding_by_version(sqlite_session, str(version.id))
        assert record is not None
        assert record.status == "completed"


class TestDeleteDocumentUnderstanding:
    def test_deletes_existing(self, sqlite_session: Session) -> None:
        from ragrig.ingestion.pipeline import ingest_local_directory

        ingest_local_directory(
            session=sqlite_session,
            knowledge_base_name="test-kb",
            root_path=Path("tests/fixtures/local_ingestion"),
        )
        version = sqlite_session.query(DocumentVersion).first()
        assert version is not None

        generate_document_understanding(
            sqlite_session,
            document_version_id=str(version.id),
            provider="deterministic-local",
        )

        assert delete_document_understanding(sqlite_session, str(version.id)) is True
        assert get_understanding_by_version(sqlite_session, str(version.id)) is None

    def test_returns_false_when_missing(self, sqlite_session: Session) -> None:
        result = delete_document_understanding(sqlite_session, str(uuid.uuid4()))
        assert result is False
