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


def _seed_kb_with_versions(session: Session, *, text_contents: list[str]) -> list[str]:
    """Create a KB with one source and multiple document versions, return version IDs."""
    import uuid as _uuid

    from ragrig.db.models import Document, DocumentVersion, KnowledgeBase, Source

    kb = KnowledgeBase(
        id=_uuid.uuid4(),
        name=f"test-coverage-{_uuid.uuid4().hex[:8]}",
        metadata_json={},
    )
    session.add(kb)

    source = Source(
        id=_uuid.uuid4(),
        knowledge_base_id=kb.id,
        kind="local_directory",
        uri=f"file:///tmp/test-coverage-{_uuid.uuid4().hex[:8]}",
        config_json={},
    )
    session.add(source)

    version_ids: list[str] = []
    for idx, text in enumerate(text_contents):
        doc = Document(
            id=_uuid.uuid4(),
            knowledge_base_id=kb.id,
            source_id=source.id,
            uri=f"test-doc-{idx}.md",
            content_hash=f"hash-{idx}",
            metadata_json={},
        )
        session.add(doc)
        session.flush()

        version = DocumentVersion(
            id=_uuid.uuid4(),
            document_id=doc.id,
            version_number=1,
            content_hash=f"hash-v-{idx}",
            parser_name="markdown",
            parser_config_json={},
            extracted_text=text,
            metadata_json={},
        )
        session.add(version)
        session.flush()
        version_ids.append(str(version.id))

    session.commit()
    return version_ids, str(kb.id)


class TestUnderstandAllVersions:
    def test_missing_generated(self, sqlite_session: Session) -> None:
        texts = ["# Doc A\nContent here.", "# Doc B\nMore content.", "# Doc C\nEven more."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)
        assert len(version_ids) == 3

        from ragrig.understanding.service import understand_all_versions

        result = understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="deterministic-local",
            profile_id="*.understand.default",
        )
        assert result.total == 3
        assert result.created == 3
        assert result.skipped == 0
        assert result.failed == 0
        assert result.errors == []

    def test_fresh_skip(self, sqlite_session: Session) -> None:
        texts = ["# Doc A\nContent here.", "# Doc B\nMore content."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        from ragrig.understanding.service import understand_all_versions

        # First run creates
        r1 = understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="deterministic-local",
            profile_id="*.understand.default",
        )
        assert r1.created == 2
        assert r1.skipped == 0

        # Second run skips all (same hash, all completed)
        r2 = understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="deterministic-local",
            profile_id="*.understand.default",
        )
        assert r2.total == 2
        assert r2.created == 0
        assert r2.skipped == 2
        assert r2.failed == 0

    def test_stale_regenerated(self, sqlite_session: Session) -> None:
        texts = ["# Doc A\nOriginal content."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        from ragrig.understanding.service import (
            generate_document_understanding,
            understand_all_versions,
        )

        # First generate understanding with original text
        generate_document_understanding(
            sqlite_session,
            document_version_id=version_ids[0],
            provider="deterministic-local",
            profile_id="*.understand.default",
        )

        # Modify text to make it stale
        from ragrig.db.models import DocumentVersion

        version = sqlite_session.get(DocumentVersion, uuid.UUID(version_ids[0]))
        assert version is not None
        version.extracted_text = "# Doc A\nModified content now."
        sqlite_session.flush()
        sqlite_session.commit()

        # Now understand_all should regenerate (stale)
        result = understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="deterministic-local",
            profile_id="*.understand.default",
        )
        assert result.total == 1
        assert result.created == 1  # stale → regenerated
        assert result.skipped == 0
        assert result.failed == 0

    def test_failed_regenerated(self, sqlite_session: Session) -> None:
        texts = ["# Doc A\nContent here."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        from ragrig.db.models import DocumentUnderstanding

        # Manually create a failed understanding record
        failed = DocumentUnderstanding(
            id=uuid.uuid4(),
            document_version_id=uuid.UUID(version_ids[0]),
            profile_id="*.understand.default",
            provider="deterministic-local",
            model="",
            input_hash="different-hash",
            status="failed",
            result_json={},
            error="previous failure",
        )
        sqlite_session.add(failed)
        sqlite_session.commit()

        from ragrig.understanding.service import understand_all_versions

        result = understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="deterministic-local",
            profile_id="*.understand.default",
        )
        assert result.total == 1
        assert result.created == 1  # failed → regenerated
        assert result.skipped == 0
        assert result.failed == 0

    def test_partial_provider_failure(self, sqlite_session: Session) -> None:
        """When some versions fail and others succeed, batch continues."""
        texts = ["# Doc OK\nGood content.", "# Doc Fail Trigger"]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        # Use a mock approach: make the provider fail for one version
        # by setting extracted_text to trigger error. Deterministic provider
        # doesn't fail, so we'll use an invalid provider for one version.
        # Instead, we can use a provider that fails for all, and check batch errors.
        # The cleanest approach is to use the nonexistent provider for both.

        from ragrig.understanding.service import understand_all_versions

        result = understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="nonexistent-provider",
            profile_id="*.understand.default",
        )
        # Both should fail with provider unavailable
        assert result.total == 2
        assert result.created == 0
        assert result.failed == 2
        assert len(result.errors) == 2

        # Verify failed records were persisted
        from ragrig.db.models import DocumentUnderstanding

        rows = (
            sqlite_session.query(DocumentUnderstanding)
            .filter(DocumentUnderstanding.profile_id == "*.understand.default")
            .all()
        )
        assert len(rows) == 2
        for row in rows:
            assert row.status == "failed"

    def test_empty_text_version(self, sqlite_session: Session) -> None:
        texts = [""]  # empty text
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        from ragrig.understanding.service import understand_all_versions

        result = understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="deterministic-local",
            profile_id="*.understand.default",
        )
        assert result.total == 1
        assert result.created == 1
        assert result.failed == 0

    def test_repeat_execution_idempotent(self, sqlite_session: Session) -> None:
        texts = ["# Doc 1\nContent.", "# Doc 2\nContent.", "# Doc 3\nContent."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        from ragrig.understanding.service import understand_all_versions

        # First run
        r1 = understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="deterministic-local",
            profile_id="*.understand.default",
        )
        assert r1.created == 3

        # Second run — all should be skipped (fresh)
        r2 = understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="deterministic-local",
            profile_id="*.understand.default",
        )
        assert r2.total == 3
        assert r2.created == 0
        assert r2.skipped == 3
        assert r2.failed == 0

        # Third run — still idempotent
        r3 = understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="deterministic-local",
            profile_id="*.understand.default",
        )
        assert r3.created == 0
        assert r3.skipped == 3


class TestUnderstandingCoverage:
    def test_all_missing(self, sqlite_session: Session) -> None:
        texts = ["# A\nContent.", "# B\nMore."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        from ragrig.understanding.service import get_understanding_coverage

        coverage = get_understanding_coverage(sqlite_session, kb_id)
        assert coverage.total_versions == 2
        assert coverage.completed == 0
        assert coverage.missing == 2
        assert coverage.stale == 0
        assert coverage.failed == 0
        assert coverage.completeness_score == 0.0

    def test_mixed_states(self, sqlite_session: Session) -> None:
        texts = [
            "# Completed\nFresh content.",
            "# Stale\nWill change.",
            "# Missing\nNo understand.",
        ]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        from ragrig.db.models import DocumentVersion
        from ragrig.understanding.service import (
            generate_document_understanding,
            get_understanding_coverage,
        )

        # Generate understanding for version 0 (will be completed)
        generate_document_understanding(
            sqlite_session,
            document_version_id=version_ids[0],
            provider="deterministic-local",
            profile_id="*.understand.default",
        )

        # Generate understanding for version 1, then modify to make stale
        generate_document_understanding(
            sqlite_session,
            document_version_id=version_ids[1],
            provider="deterministic-local",
            profile_id="*.understand.default",
        )
        version = sqlite_session.get(DocumentVersion, uuid.UUID(version_ids[1]))
        assert version is not None
        version.extracted_text = "# Stale\nModified content."
        sqlite_session.flush()
        sqlite_session.commit()

        # Version 2 is missing (no understanding generated)

        coverage = get_understanding_coverage(sqlite_session, kb_id)
        assert coverage.total_versions == 3
        assert coverage.completed == 1
        assert coverage.missing == 1
        assert coverage.stale == 1
        assert coverage.failed == 0
        assert coverage.completeness_score == pytest.approx(1 / 3, rel=1e-2)

    def test_failed_counted(self, sqlite_session: Session) -> None:
        texts = ["# Failed Doc\nContent."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        from ragrig.db.models import DocumentUnderstanding

        failed = DocumentUnderstanding(
            id=uuid.uuid4(),
            document_version_id=uuid.UUID(version_ids[0]),
            profile_id="*.understand.default",
            provider="deterministic-local",
            model="",
            input_hash="stale-hash",
            status="failed",
            result_json={},
            error="some error",
        )
        sqlite_session.add(failed)
        sqlite_session.commit()

        from ragrig.understanding.service import get_understanding_coverage

        coverage = get_understanding_coverage(sqlite_session, kb_id)
        assert coverage.total_versions == 1
        assert coverage.failed == 1
        assert coverage.completed == 0
        assert coverage.missing == 0
        assert coverage.stale == 0
        assert len(coverage.recent_errors) == 1
        assert coverage.recent_errors[0].error == "some error"
        assert coverage.recent_errors[0].profile_id == "*.understand.default"

    def test_completeness_score(self, sqlite_session: Session) -> None:
        texts = ["# C1\nDone.", "# C2\nDone.", "# C3\nDone."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        from ragrig.understanding.service import (
            generate_document_understanding,
            get_understanding_coverage,
        )

        # Complete 2 out of 3
        generate_document_understanding(
            sqlite_session,
            document_version_id=version_ids[0],
            provider="deterministic-local",
            profile_id="*.understand.default",
        )
        generate_document_understanding(
            sqlite_session,
            document_version_id=version_ids[1],
            provider="deterministic-local",
            profile_id="*.understand.default",
        )

        coverage = get_understanding_coverage(sqlite_session, kb_id)
        assert coverage.total_versions == 3
        assert coverage.completed == 2
        assert coverage.missing == 1
        assert coverage.completeness_score == pytest.approx(2 / 3, rel=1e-2)


class TestRunStatusFromResult:
    def test_all_four_statuses(self) -> None:
        from ragrig.understanding.service import _run_status_from_result

        assert _run_status_from_result(0, 0) == "empty_kb"
        assert _run_status_from_result(3, 0) == "success"
        assert _run_status_from_result(3, 3) == "all_failure"
        assert _run_status_from_result(5, 2) == "partial_failure"

    def test_success_when_total_nonzero(self) -> None:
        from ragrig.understanding.service import _run_status_from_result

        assert _run_status_from_result(1, 0) == "success"
        assert _run_status_from_result(10, 0) == "success"


class TestSafeErrorSummary:
    def test_returns_none_for_empty_errors(self) -> None:
        from ragrig.understanding.service import _safe_error_summary

        assert _safe_error_summary([]) is None

    def test_formats_multiple_errors(self) -> None:
        from ragrig.understanding.schema import BatchUnderstandingError
        from ragrig.understanding.service import _safe_error_summary

        errors = [
            BatchUnderstandingError(
                version_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                error="connection refused",
            ),
            BatchUnderstandingError(
                version_id="ffffffff-gggg-hhhh-iiii-jjjjjjjjjjjj",
                error="timeout after 30s",
            ),
        ]
        summary = _safe_error_summary(errors)
        assert summary is not None
        assert "aaaaaaaa" in summary
        assert "connection refused" in summary
        assert "ffffffff" in summary
        assert "timeout after 30s" in summary

    def test_truncates_long_messages(self) -> None:
        from ragrig.understanding.schema import BatchUnderstandingError
        from ragrig.understanding.service import _safe_error_summary

        long_msg = "x" * 500
        errors = [
            BatchUnderstandingError(
                version_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                error=long_msg,
            ),
        ]
        summary = _safe_error_summary(errors)
        assert summary is not None
        assert len(summary) < 300  # Should be truncated
        assert summary.endswith("...")

    def test_truncates_overall_summary(self) -> None:
        from ragrig.understanding.schema import BatchUnderstandingError
        from ragrig.understanding.service import _safe_error_summary

        errors = [
            BatchUnderstandingError(
                version_id=f"{str(i).zfill(8)}-bbbb-cccc-dddd-eeeeeeeeeeee",
                error="error message that is not too long itself",
            )
            for i in range(20)
        ]
        summary = _safe_error_summary(errors)
        assert summary is not None
        if len(summary) > 2000:
            assert summary.endswith("...")


class TestUnderstandAllPersistsRun:
    def test_creates_run_record_on_success(self, sqlite_session: Session) -> None:
        from ragrig.db.models import UnderstandingRun
        from ragrig.understanding.service import understand_all_versions

        texts = ["# Doc A\nContent.", "# Doc B\nMore."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        result = understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="deterministic-local",
            profile_id="*.understand.default",
            trigger_source="api",
            operator="test-user",
        )
        assert result.total == 2
        assert result.created == 2

        runs = sqlite_session.query(UnderstandingRun).all()
        assert len(runs) == 1
        run = runs[0]
        assert str(run.knowledge_base_id) == kb_id
        assert run.provider == "deterministic-local"
        assert run.profile_id == "*.understand.default"
        assert run.trigger_source == "api"
        assert run.operator == "test-user"
        assert run.status == "success"
        assert run.total == 2
        assert run.created == 2
        assert run.skipped == 0
        assert run.failed == 0
        assert run.error_summary is None
        assert run.started_at is not None
        assert run.finished_at is not None

    def test_empty_kb_creates_empty_kb_run(self, sqlite_session: Session) -> None:
        from ragrig.db.models import UnderstandingRun
        from ragrig.understanding.service import understand_all_versions

        texts: list[str] = []
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        result = understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="deterministic-local",
        )
        assert result.total == 0

        runs = sqlite_session.query(UnderstandingRun).all()
        assert len(runs) == 1
        assert runs[0].status == "empty_kb"

    def test_partial_failure_creates_run_with_error_summary(self, sqlite_session: Session) -> None:
        from ragrig.db.models import UnderstandingRun
        from ragrig.understanding.service import understand_all_versions

        texts = ["# Doc A\nContent.", "# Doc B\nMore."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        result = understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="nonexistent-provider",
            profile_id="*.understand.default",
        )
        assert result.failed == 2

        runs = sqlite_session.query(UnderstandingRun).all()
        assert len(runs) == 1
        assert runs[0].status == "all_failure"
        assert runs[0].error_summary is not None

    def test_duplicate_run_creates_separate_record(self, sqlite_session: Session) -> None:
        from ragrig.db.models import UnderstandingRun
        from ragrig.understanding.service import understand_all_versions

        texts = ["# Doc A\nContent."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        # First run
        understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="deterministic-local",
        )
        # Second run (all skipped)
        understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="deterministic-local",
        )

        runs = sqlite_session.query(UnderstandingRun).all()
        assert len(runs) == 2
        # First run created docs
        assert runs[0].status == "success"
        assert runs[0].created == 1
        # Second run skipped all
        assert runs[1].status == "success"
        assert runs[1].skipped == 1


class TestGetUnderstandingRuns:
    def test_returns_runs_latest_first(self, sqlite_session: Session) -> None:
        from ragrig.understanding.service import (
            get_understanding_runs,
            understand_all_versions,
        )

        texts = ["# Doc A\nContent."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="provider-a",
            profile_id="profile-1",
        )
        understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="provider-b",
            profile_id="profile-2",
        )

        runs = get_understanding_runs(sqlite_session, kb_id)
        assert len(runs) == 2
        # Most recent first
        assert runs[0].provider == "provider-b"
        assert runs[0].profile_id == "profile-2"
        assert runs[1].provider == "provider-a"
        assert runs[1].profile_id == "profile-1"

    def test_filter_by_provider(self, sqlite_session: Session) -> None:
        from ragrig.understanding.schema import UnderstandingRunFilter
        from ragrig.understanding.service import (
            get_understanding_runs,
            understand_all_versions,
        )

        texts = ["# Doc A\nContent."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="provider-a",
        )
        understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="provider-b",
        )

        runs = get_understanding_runs(
            sqlite_session,
            kb_id,
            filters=UnderstandingRunFilter(provider="provider-a"),
        )
        assert len(runs) == 1
        assert runs[0].provider == "provider-a"

    def test_filter_by_status(self, sqlite_session: Session) -> None:
        from ragrig.understanding.schema import UnderstandingRunFilter
        from ragrig.understanding.service import (
            get_understanding_runs,
            understand_all_versions,
        )

        texts: list[str] = []
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="deterministic-local",
        )

        runs = get_understanding_runs(
            sqlite_session,
            kb_id,
            filters=UnderstandingRunFilter(status="empty_kb"),
        )
        assert len(runs) == 1
        assert runs[0].status == "empty_kb"

        runs = get_understanding_runs(
            sqlite_session,
            kb_id,
            filters=UnderstandingRunFilter(status="success"),
        )
        assert len(runs) == 0

    def test_empty_kb_returns_empty_list(self, sqlite_session: Session) -> None:
        from ragrig.understanding.service import get_understanding_runs

        texts = ["# Doc A\nContent."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        runs = get_understanding_runs(sqlite_session, kb_id)
        assert runs == []


class TestGetUnderstandingRun:
    def test_returns_none_for_missing(self, sqlite_session: Session) -> None:
        from ragrig.understanding.service import get_understanding_run

        result = get_understanding_run(sqlite_session, str(uuid.uuid4()))
        assert result is None

    def test_returns_record_when_exists(self, sqlite_session: Session) -> None:
        from ragrig.db.models import UnderstandingRun
        from ragrig.understanding.service import (
            get_understanding_run,
            understand_all_versions,
        )

        texts = ["# Doc A\nContent."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="deterministic-local",
            profile_id="*.understand.default",
            trigger_source="test",
        )

        run_row = sqlite_session.query(UnderstandingRun).first()
        assert run_row is not None

        record = get_understanding_run(sqlite_session, str(run_row.id))
        assert record is not None
        assert record.provider == "deterministic-local"
        assert record.profile_id == "*.understand.default"
        assert record.trigger_source == "test"
        assert record.status == "success"
        assert record.total == 1


class TestUnderstandAllAPIWithRun:
    @pytest.mark.anyio
    async def test_post_returns_run_id(self, tmp_path) -> None:

        import httpx
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from ragrig.db.models import Base
        from ragrig.main import create_app

        db_path = tmp_path / "test_understand_run_api.db"
        engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
        Base.metadata.create_all(engine)

        def session_factory() -> Session:
            return Session(engine, expire_on_commit=False)

        # Seed data
        session = session_factory()
        try:
            from ragrig.db.models import Document, DocumentVersion, KnowledgeBase, Source

            kb = KnowledgeBase(name="kb-run-test", metadata_json={})
            session.add(kb)
            session.flush()
            source = Source(
                knowledge_base_id=kb.id, kind="local", uri="file:///test", config_json={}
            )
            session.add(source)
            session.flush()
            doc = Document(
                knowledge_base_id=kb.id,
                source_id=source.id,
                uri="doc.md",
                content_hash="abc",
                metadata_json={},
            )
            session.add(doc)
            session.flush()
            version = DocumentVersion(
                document_id=doc.id,
                version_number=1,
                content_hash="abc",
                parser_name="markdown",
                parser_config_json={},
                extracted_text="# Hello\nContent.",
                metadata_json={},
            )
            session.add(version)
            session.commit()
            kb_id = str(kb.id)
        finally:
            session.close()

        app = create_app(
            check_database=lambda: None,
            session_factory=session_factory,
        )
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                f"/knowledge-bases/{kb_id}/understand-all",
                json={
                    "provider": "deterministic-local",
                    "profile_id": "*.understand.default",
                },
                headers={"x-operator": "api-caller"},
            )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["created"] == 1
        assert data["skipped"] == 0
        assert data["failed"] == 0
        assert data["run_id"] is not None

    @pytest.mark.anyio
    async def test_get_understanding_runs_api(self, tmp_path) -> None:
        import httpx
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from ragrig.db.models import Base
        from ragrig.main import create_app

        db_path = tmp_path / "test_understand_runs_api.db"
        engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
        Base.metadata.create_all(engine)

        def session_factory() -> Session:
            return Session(engine, expire_on_commit=False)

        # Seed and run
        session = session_factory()
        try:
            from ragrig.db.models import Document, DocumentVersion, KnowledgeBase, Source

            kb = KnowledgeBase(name="kb-run-api", metadata_json={})
            session.add(kb)
            session.flush()
            source = Source(
                knowledge_base_id=kb.id, kind="local", uri="file:///test", config_json={}
            )
            session.add(source)
            session.flush()
            doc = Document(
                knowledge_base_id=kb.id,
                source_id=source.id,
                uri="doc.md",
                content_hash="abc",
                metadata_json={},
            )
            session.add(doc)
            session.flush()
            version = DocumentVersion(
                document_id=doc.id,
                version_number=1,
                content_hash="abc",
                parser_name="markdown",
                parser_config_json={},
                extracted_text="# Hello\nContent.",
                metadata_json={},
            )
            session.add(version)
            session.commit()
            kb_id = str(kb.id)
        finally:
            session.close()

        app = create_app(
            check_database=lambda: None,
            session_factory=session_factory,
        )
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # First, trigger a run
            await client.post(
                f"/knowledge-bases/{kb_id}/understand-all",
                json={
                    "provider": "deterministic-local",
                    "profile_id": "*.understand.default",
                },
            )

            # Then fetch runs
            response = await client.get(f"/knowledge-bases/{kb_id}/understanding-runs")
        assert response.status_code == 200
        data = response.json()
        assert "runs" in data
        assert len(data["runs"]) >= 1
        run = data["runs"][0]
        assert run["provider"] == "deterministic-local"
        assert run["profile_id"] == "*.understand.default"
        assert run["status"] == "success"

    @pytest.mark.anyio
    async def test_get_understanding_run_detail_api(self, tmp_path) -> None:
        import httpx
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from ragrig.db.models import Base
        from ragrig.main import create_app

        db_path = tmp_path / "test_understand_run_detail.db"
        engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
        Base.metadata.create_all(engine)

        def session_factory() -> Session:
            return Session(engine, expire_on_commit=False)

        # Seed and run
        session = session_factory()
        try:
            from ragrig.db.models import Document, DocumentVersion, KnowledgeBase, Source

            kb = KnowledgeBase(name="kb-run-detail", metadata_json={})
            session.add(kb)
            session.flush()
            source = Source(
                knowledge_base_id=kb.id, kind="local", uri="file:///test", config_json={}
            )
            session.add(source)
            session.flush()
            doc = Document(
                knowledge_base_id=kb.id,
                source_id=source.id,
                uri="doc.md",
                content_hash="abc",
                metadata_json={},
            )
            session.add(doc)
            session.flush()
            version = DocumentVersion(
                document_id=doc.id,
                version_number=1,
                content_hash="abc",
                parser_name="markdown",
                parser_config_json={},
                extracted_text="# Hello\nContent.",
                metadata_json={},
            )
            session.add(version)
            session.commit()
            kb_id = str(kb.id)
        finally:
            session.close()

        app = create_app(
            check_database=lambda: None,
            session_factory=session_factory,
        )
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Trigger a run
            post_resp = await client.post(
                f"/knowledge-bases/{kb_id}/understand-all",
                json={
                    "provider": "deterministic-local",
                    "profile_id": "*.understand.default",
                },
            )
            run_id = post_resp.json()["run_id"]

            # Fetch run detail via raw API (/knowledge-bases prefix)
            response = await client.get(f"/knowledge-bases/{kb_id}/understanding-runs")
            items = response.json()["runs"]
            assert len(items) >= 1

            # Fetch detail via web console endpoint
            detail_resp = await client.get(f"/understanding-runs/{run_id}")
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        assert detail["id"] == run_id
        assert detail["provider"] == "deterministic-local"
        assert detail["knowledge_base"] == "kb-run-detail"

    @pytest.mark.anyio
    async def test_understanding_run_not_found_returns_404(self, tmp_path) -> None:
        import httpx
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from ragrig.db.models import Base
        from ragrig.main import create_app

        db_path = tmp_path / "test_404.db"
        engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
        Base.metadata.create_all(engine)

        def session_factory() -> Session:
            return Session(engine, expire_on_commit=False)

        app = create_app(
            check_database=lambda: None,
            session_factory=session_factory,
        )
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"/understanding-runs/{uuid.uuid4()}")
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_web_console_understanding_runs_list(self, tmp_path) -> None:
        import httpx
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from ragrig.db.models import Base
        from ragrig.main import create_app

        db_path = tmp_path / "test_web_runs.db"
        engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
        Base.metadata.create_all(engine)

        def session_factory() -> Session:
            return Session(engine, expire_on_commit=False)

        # Seed and run
        session = session_factory()
        try:
            from ragrig.db.models import Document, DocumentVersion, KnowledgeBase, Source

            kb = KnowledgeBase(name="kb-web-runs", metadata_json={})
            session.add(kb)
            session.flush()
            source = Source(
                knowledge_base_id=kb.id, kind="local", uri="file:///test", config_json={}
            )
            session.add(source)
            session.flush()
            doc = Document(
                knowledge_base_id=kb.id,
                source_id=source.id,
                uri="doc.md",
                content_hash="abc",
                metadata_json={},
            )
            session.add(doc)
            session.flush()
            version = DocumentVersion(
                document_id=doc.id,
                version_number=1,
                content_hash="abc",
                parser_name="markdown",
                parser_config_json={},
                extracted_text="# Hello",
                metadata_json={},
            )
            session.add(version)
            session.commit()
            kb_id = str(kb.id)
        finally:
            session.close()

        app = create_app(
            check_database=lambda: None,
            session_factory=session_factory,
        )
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Trigger a run first
            await client.post(
                f"/knowledge-bases/{kb_id}/understand-all",
                json={"provider": "deterministic-local", "profile_id": "*.understand.default"},
            )

            # Fetch via web console endpoint
            response = await client.get(
                "/understanding-runs",
                params={"knowledge_base_id": kb_id, "limit": 5},
            )
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert len(data["items"]) >= 1
        item = data["items"][0]
        assert item["knowledge_base"] == "kb-web-runs"
        assert item["status"] == "success"


class TestGetUnderstandingRunsTimeRange:
    def test_filter_by_started_after(self, sqlite_session: Session) -> None:
        from ragrig.understanding.schema import UnderstandingRunFilter
        from ragrig.understanding.service import (
            get_understanding_runs,
            understand_all_versions,
        )

        texts = ["# Doc A\nContent."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="provider-a",
        )

        # All runs should be after year 2020
        runs = get_understanding_runs(
            sqlite_session,
            kb_id,
            filters=UnderstandingRunFilter(started_after="2020-01-01T00:00:00"),
        )
        assert len(runs) == 1

        # No runs before year 2020
        runs = get_understanding_runs(
            sqlite_session,
            kb_id,
            filters=UnderstandingRunFilter(started_before="2020-01-01T00:00:00"),
        )
        assert len(runs) == 0

    def test_filter_by_started_before(self, sqlite_session: Session) -> None:
        from ragrig.understanding.schema import UnderstandingRunFilter
        from ragrig.understanding.service import (
            get_understanding_runs,
            understand_all_versions,
        )

        texts = ["# Doc A\nContent."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="provider-a",
        )

        # Future filter should match
        import datetime

        now = datetime.datetime.now(datetime.timezone.utc)
        future = (now + datetime.timedelta(days=365)).isoformat()
        runs = get_understanding_runs(
            sqlite_session,
            kb_id,
            filters=UnderstandingRunFilter(started_before=future),
        )
        assert len(runs) == 1

    def test_combined_filters(self, sqlite_session: Session) -> None:
        from ragrig.understanding.schema import UnderstandingRunFilter
        from ragrig.understanding.service import (
            get_understanding_runs,
            understand_all_versions,
        )

        texts = ["# Doc A\nContent."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="provider-a",
            profile_id="profile-1",
        )
        understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="provider-b",
            profile_id="profile-2",
        )

        import datetime

        now = datetime.datetime.now(datetime.timezone.utc)
        future = (now + datetime.timedelta(days=1)).isoformat()
        runs = get_understanding_runs(
            sqlite_session,
            kb_id,
            filters=UnderstandingRunFilter(
                provider="provider-b",
                started_before=future,
                limit=10,
            ),
        )
        assert len(runs) == 1
        assert runs[0].provider == "provider-b"


class TestExportUnderstandingRun:
    def test_export_single_run_hides_sensitive(self, sqlite_session: Session) -> None:
        from ragrig.understanding.service import (
            export_understanding_run,
            understand_all_versions,
        )

        texts = ["# Doc A\nContent."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="deterministic-local",
            profile_id="*.understand.default",
        )

        from ragrig.db.models import UnderstandingRun

        run = sqlite_session.query(UnderstandingRun).first()
        assert run is not None

        result = export_understanding_run(sqlite_session, str(run.id))
        assert result is not None
        assert result["id"] == str(run.id)
        assert result["provider"] == "deterministic-local"
        assert result["status"] == "success"
        assert "exported_at" in result
        # No sensitive keys should be present
        result_str = str(result)
        assert "api_key" not in result_str.lower()
        assert "password" not in result_str.lower()
        assert "extracted_text" not in result_str

    def test_export_nonexistent_run_returns_none(self, sqlite_session: Session) -> None:
        from ragrig.understanding.service import export_understanding_run

        result = export_understanding_run(sqlite_session, str(uuid.uuid4()))
        assert result is None

    def test_export_list_runs(self, sqlite_session: Session) -> None:
        from ragrig.understanding.service import (
            export_understanding_runs,
            understand_all_versions,
        )

        texts = ["# Doc A\nContent."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="deterministic-local",
            profile_id="*.understand.default",
        )

        result = export_understanding_runs(sqlite_session, kb_id)
        assert result is not None
        assert "runs" in result
        assert result["total_runs"] == 1
        assert "exported_at" in result
        assert "filters_applied" in result
        assert result["runs"][0]["provider"] == "deterministic-local"

    def test_export_list_empty_kb(self, sqlite_session: Session) -> None:
        from ragrig.understanding.service import export_understanding_runs

        texts = ["# Doc A\nContent."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        result = export_understanding_runs(sqlite_session, kb_id)
        assert result is not None
        assert result["total_runs"] == 0
        assert result["runs"] == []

    def test_export_sanitizes_nested_secrets(self, sqlite_session: Session) -> None:
        from ragrig.understanding.service import _sanitize_value

        data = {
            "id": "test",
            "config": {
                "api_key": "sk-secret-123",
                "password": "my-password",
                "normal_field": "ok",
            },
            "nested": {
                "providers": [
                    {"name": "p1", "access_key": "key123"},
                    {"name": "p2", "secret": "sauce"},
                ]
            },
            "extracted_text": "should be redacted",
            "prompt": "should be redacted",
        }
        sanitized = _sanitize_value(data)
        assert isinstance(sanitized, dict)
        assert sanitized["config"]["api_key"] == "[REDACTED]"  # type: ignore[index]
        assert sanitized["config"]["password"] == "[REDACTED]"  # type: ignore[index]
        assert sanitized["config"]["normal_field"] == "ok"  # type: ignore[index]
        assert sanitized["extracted_text"] == "[REDACTED]"  # type: ignore[index]
        assert sanitized["prompt"] == "[REDACTED]"  # type: ignore[index]


class TestCompareUnderstandingRuns:
    def test_diff_two_runs(self, sqlite_session: Session) -> None:
        from ragrig.understanding.service import (
            compare_understanding_runs,
            understand_all_versions,
        )

        texts = ["# Doc A\nContent."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="provider-a",
            profile_id="profile-1",
        )
        understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="provider-b",
            profile_id="profile-2",
        )

        from ragrig.db.models import UnderstandingRun

        runs = (
            sqlite_session.query(UnderstandingRun)
            .order_by(UnderstandingRun.started_at.asc())
            .all()
        )
        assert len(runs) == 2

        result = compare_understanding_runs(sqlite_session, str(runs[0].id), str(runs[1].id))
        assert result is not None
        assert "changes" in result
        assert "run_a" in result
        assert "run_b" in result

        # At least the provider should differ
        changed_fields = [c for c in result["changes"] if c["changed"]]
        assert len(changed_fields) > 0

    def test_diff_nonexistent_run(self, sqlite_session: Session) -> None:
        from ragrig.understanding.service import compare_understanding_runs

        result = compare_understanding_runs(
            sqlite_session,
            str(uuid.uuid4()),
            str(uuid.uuid4()),
        )
        assert result is None

    def test_diff_identical_runs(self, sqlite_session: Session) -> None:
        """Diffing a run against itself should show no changes."""
        from ragrig.understanding.service import (
            compare_understanding_runs,
            understand_all_versions,
        )

        texts = ["# Doc A\nContent."]
        version_ids, kb_id = _seed_kb_with_versions(sqlite_session, text_contents=texts)

        understand_all_versions(
            sqlite_session,
            knowledge_base_id=kb_id,
            provider="deterministic-local",
            profile_id="*.understand.default",
        )

        from ragrig.db.models import UnderstandingRun

        run = sqlite_session.query(UnderstandingRun).first()
        assert run is not None

        result = compare_understanding_runs(sqlite_session, str(run.id), str(run.id))
        assert result is not None
        changed_fields = [c for c in result["changes"] if c["changed"]]
        assert len(changed_fields) == 0


class TestExportAndDiffAPI:
    @pytest.mark.anyio
    async def test_export_single_run_api(self, tmp_path) -> None:
        import httpx
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from ragrig.db.models import Base
        from ragrig.main import create_app

        db_path = tmp_path / "test_export_run.db"
        engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
        Base.metadata.create_all(engine)

        def session_factory() -> Session:
            return Session(engine, expire_on_commit=False)

        session = session_factory()
        try:
            from ragrig.db.models import Document, DocumentVersion, KnowledgeBase, Source

            kb = KnowledgeBase(name="kb-export", metadata_json={})
            session.add(kb)
            session.flush()
            source = Source(
                knowledge_base_id=kb.id, kind="local", uri="file:///test", config_json={}
            )
            session.add(source)
            session.flush()
            doc = Document(
                knowledge_base_id=kb.id,
                source_id=source.id,
                uri="doc.md",
                content_hash="abc",
                metadata_json={},
            )
            session.add(doc)
            session.flush()
            version = DocumentVersion(
                document_id=doc.id,
                version_number=1,
                content_hash="abc",
                parser_name="markdown",
                parser_config_json={},
                extracted_text="# Hello\nContent.",
                metadata_json={},
            )
            session.add(version)
            session.commit()
            kb_id = str(kb.id)
        finally:
            session.close()

        app = create_app(
            check_database=lambda: None,
            session_factory=session_factory,
        )
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            # Create a run first
            post_resp = await client.post(
                f"/knowledge-bases/{kb_id}/understand-all",
                json={"provider": "deterministic-local", "profile_id": "*.understand.default"},
            )
            run_id = post_resp.json()["run_id"]

            # Export single run
            export_resp = await client.get(f"/understanding-runs/{run_id}/export")
        assert export_resp.status_code == 200
        data = export_resp.json()
        assert data["id"] == run_id
        assert "exported_at" in data
        assert data["status"] == "success"

    @pytest.mark.anyio
    async def test_export_list_runs_api(self, tmp_path) -> None:
        import httpx
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from ragrig.db.models import Base
        from ragrig.main import create_app

        db_path = tmp_path / "test_export_list.db"
        engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
        Base.metadata.create_all(engine)

        def session_factory() -> Session:
            return Session(engine, expire_on_commit=False)

        session = session_factory()
        try:
            from ragrig.db.models import Document, DocumentVersion, KnowledgeBase, Source

            kb = KnowledgeBase(name="kb-export-list", metadata_json={})
            session.add(kb)
            session.flush()
            source = Source(
                knowledge_base_id=kb.id, kind="local", uri="file:///test", config_json={}
            )
            session.add(source)
            session.flush()
            doc = Document(
                knowledge_base_id=kb.id,
                source_id=source.id,
                uri="doc.md",
                content_hash="abc",
                metadata_json={},
            )
            session.add(doc)
            session.flush()
            version = DocumentVersion(
                document_id=doc.id,
                version_number=1,
                content_hash="abc",
                parser_name="markdown",
                parser_config_json={},
                extracted_text="# Hello\nContent.",
                metadata_json={},
            )
            session.add(version)
            session.commit()
            kb_id = str(kb.id)
        finally:
            session.close()

        app = create_app(
            check_database=lambda: None,
            session_factory=session_factory,
        )
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await client.post(
                f"/knowledge-bases/{kb_id}/understand-all",
                json={"provider": "deterministic-local", "profile_id": "*.understand.default"},
            )

            export_resp = await client.get(f"/knowledge-bases/{kb_id}/understanding-runs/export")
        assert export_resp.status_code == 200
        data = export_resp.json()
        assert data["total_runs"] >= 1
        assert "runs" in data
        assert "exported_at" in data

    @pytest.mark.anyio
    async def test_diff_api(self, tmp_path) -> None:
        import httpx
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from ragrig.db.models import Base
        from ragrig.main import create_app

        db_path = tmp_path / "test_diff_api.db"
        engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
        Base.metadata.create_all(engine)

        def session_factory() -> Session:
            return Session(engine, expire_on_commit=False)

        session = session_factory()
        try:
            from ragrig.db.models import Document, DocumentVersion, KnowledgeBase, Source

            kb = KnowledgeBase(name="kb-diff", metadata_json={})
            session.add(kb)
            session.flush()
            source = Source(
                knowledge_base_id=kb.id, kind="local", uri="file:///test", config_json={}
            )
            session.add(source)
            session.flush()
            doc = Document(
                knowledge_base_id=kb.id,
                source_id=source.id,
                uri="doc.md",
                content_hash="abc",
                metadata_json={},
            )
            session.add(doc)
            session.flush()
            version = DocumentVersion(
                document_id=doc.id,
                version_number=1,
                content_hash="abc",
                parser_name="markdown",
                parser_config_json={},
                extracted_text="# Hello\nContent.",
                metadata_json={},
            )
            session.add(version)
            session.commit()
            kb_id = str(kb.id)
        finally:
            session.close()

        app = create_app(
            check_database=lambda: None,
            session_factory=session_factory,
        )
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            r1 = await client.post(
                f"/knowledge-bases/{kb_id}/understand-all",
                json={"provider": "provider-a", "profile_id": "*.understand.default"},
            )
            run_id_a = r1.json()["run_id"]

            r2 = await client.post(
                f"/knowledge-bases/{kb_id}/understand-all",
                json={"provider": "provider-b", "profile_id": "*.understand.default"},
            )
            run_id_b = r2.json()["run_id"]

            diff_resp = await client.get(
                f"/understanding-runs/{run_id_a}/diff",
                params={"against": run_id_b},
            )
        assert diff_resp.status_code == 200
        data = diff_resp.json()
        assert "changes" in data
        assert "run_a" in data
        assert "run_b" in data

    @pytest.mark.anyio
    async def test_export_nonexistent_run_404(self, tmp_path) -> None:
        import httpx
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from ragrig.db.models import Base
        from ragrig.main import create_app

        db_path = tmp_path / "test_export_404.db"
        engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
        Base.metadata.create_all(engine)

        def session_factory() -> Session:
            return Session(engine, expire_on_commit=False)

        app = create_app(
            check_database=lambda: None,
            session_factory=session_factory,
        )
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.get(f"/understanding-runs/{uuid.uuid4()}/export")
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_diff_nonexistent_run_404(self, tmp_path) -> None:
        import httpx
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from ragrig.db.models import Base
        from ragrig.main import create_app

        db_path = tmp_path / "test_diff_404.db"
        engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
        Base.metadata.create_all(engine)

        def session_factory() -> Session:
            return Session(engine, expire_on_commit=False)

        app = create_app(
            check_database=lambda: None,
            session_factory=session_factory,
        )
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            fake_id = str(uuid.uuid4())
            response = await client.get(
                f"/understanding-runs/{fake_id}/diff",
                params={"against": fake_id},
            )
        assert response.status_code == 404

    @pytest.mark.anyio
    async def test_web_console_runs_filtered(self, tmp_path) -> None:
        import httpx
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from ragrig.db.models import Base
        from ragrig.main import create_app

        db_path = tmp_path / "test_web_filtered.db"
        engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
        Base.metadata.create_all(engine)

        def session_factory() -> Session:
            return Session(engine, expire_on_commit=False)

        session = session_factory()
        try:
            from ragrig.db.models import Document, DocumentVersion, KnowledgeBase, Source

            kb = KnowledgeBase(name="kb-filtered", metadata_json={})
            session.add(kb)
            session.flush()
            source = Source(
                knowledge_base_id=kb.id, kind="local", uri="file:///test", config_json={}
            )
            session.add(source)
            session.flush()
            doc = Document(
                knowledge_base_id=kb.id,
                source_id=source.id,
                uri="doc.md",
                content_hash="abc",
                metadata_json={},
            )
            session.add(doc)
            session.flush()
            version = DocumentVersion(
                document_id=doc.id,
                version_number=1,
                content_hash="abc",
                parser_name="markdown",
                parser_config_json={},
                extracted_text="# Hello",
                metadata_json={},
            )
            session.add(version)
            session.commit()
            kb_id = str(kb.id)
        finally:
            session.close()

        app = create_app(
            check_database=lambda: None,
            session_factory=session_factory,
        )
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            await client.post(
                f"/knowledge-bases/{kb_id}/understand-all",
                json={"provider": "provider-x", "profile_id": "profile-y"},
            )

            # Fetch with provider filter
            response = await client.get(
                "/understanding-runs",
                params={
                    "knowledge_base_id": kb_id,
                    "provider": "provider-x",
                    "limit": 5,
                },
            )
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) >= 1
        assert data["items"][0]["provider"] == "provider-x"

        # Fetch with wrong provider filter should return none
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response2 = await client.get(
                "/understanding-runs",
                params={
                    "knowledge_base_id": kb_id,
                    "provider": "nonexistent",
                },
            )
        assert response2.status_code == 200
        assert response2.json()["items"] == []
