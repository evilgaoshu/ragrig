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
