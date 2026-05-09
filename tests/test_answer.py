"""Tests for answer generation service with citation grounding."""

from __future__ import annotations

import httpx
import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.answer import (
    DeterministicAnswerProvider,
    EvidenceChunk,
    NoEvidenceError,
    ProviderUnavailableError,
    generate_answer,
    get_answer_provider,
)
from ragrig.db.models import Base
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.main import create_app

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


def _create_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def _seed_documents(tmp_path, files: dict[str, str]):
    docs = tmp_path / "docs"
    docs.mkdir()
    for name, content in files.items():
        (docs / name).write_text(content, encoding="utf-8")
    return docs


# ── Deterministic Provider Tests ──────────────────────────────────────────────


def test_deterministic_answer_provider_generates_grounded_answer() -> None:
    provider = DeterministicAnswerProvider()
    evidence = [
        EvidenceChunk(
            citation_id="cit-1",
            document_uri="guide.txt",
            chunk_id="chunk-1",
            chunk_index=0,
            text="RAGRig is a retrieval-augmented generation platform.",
            score=0.95,
            distance=0.05,
        ),
    ]

    answer, citation_ids = provider.generate(query="What is RAGRig?", evidence=evidence)

    assert "RAGRig" in answer
    assert "cit-1" in answer
    assert citation_ids == ["cit-1"]


def test_deterministic_answer_provider_refuses_without_evidence() -> None:
    provider = DeterministicAnswerProvider()
    answer, citation_ids = provider.generate(query="What is RAGRig?", evidence=[])

    assert "cannot answer" in answer.lower()
    assert citation_ids == []


# ── generate_answer tests ─────────────────────────────────────────────────────


def test_generate_answer_with_evidence_returns_grounded_report(tmp_path) -> None:
    docs = _seed_documents(tmp_path, {"guide.txt": "RAGRig is a retrieval platform."})

    with _create_session() as session:
        ingest_local_directory(session=session, knowledge_base_name="fixture-local", root_path=docs)
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        report = generate_answer(
            session=session,
            knowledge_base_name="fixture-local",
            query="What is RAGRig?",
            top_k=3,
            provider="deterministic-local",
        )

    assert report.answer
    assert "evidence" in report.answer.lower() or "ragrig" in report.answer.lower()
    assert len(report.citations) >= 1
    assert len(report.evidence_chunks) >= 1
    assert report.grounding_status == "grounded"
    assert report.refusal_reason is None
    assert report.retrieval_trace["knowledge_base"] == "fixture-local"
    assert report.retrieval_trace["total_results"] >= 1

    # Citation consistency: all citation_ids in answer match evidence chunks
    evidence_ids = {ec.citation_id for ec in report.evidence_chunks}
    for citation in report.citations:
        assert citation.citation_id in evidence_ids
        assert citation.document_uri
        assert citation.chunk_id
        assert citation.score >= 0.0
    # No secrets in answer
    assert "api_key" not in report.answer.lower()
    assert "secret" not in report.answer.lower()


def test_generate_answer_no_evidence_raises_no_evidence_error(tmp_path) -> None:
    docs = _seed_documents(tmp_path, {"guide.txt": "some content"})

    with _create_session() as session:
        # Ingest but do NOT index → no embeddings → zero results
        ingest_local_directory(session=session, knowledge_base_name="fixture-local", root_path=docs)

        with pytest.raises(NoEvidenceError) as exc_info:
            generate_answer(
                session=session,
                knowledge_base_name="fixture-local",
                query="does not matter what we query",
                top_k=3,
            )

    assert exc_info.value.code == "no_evidence"
    assert exc_info.value.details["knowledge_base"] == "fixture-local"


def test_generate_answer_provider_unavailable(monkeypatch) -> None:
    """When the answer provider raises, ProviderUnavailableError is propagated."""

    class FailingProvider:
        def generate(self, query, evidence):
            raise RuntimeError("simulated provider failure")

    monkeypatch.setattr(
        "ragrig.answer.service.get_answer_provider",
        lambda provider, model=None: FailingProvider(),
    )

    # We need a session with data, but the provider will fail
    import uuid

    from ragrig.retrieval import RetrievalReport, RetrievalResult

    # Create a mock retrieval that returns results
    mock_result = RetrievalResult(
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        chunk_index=0,
        document_uri="test.txt",
        source_uri="/tmp",
        text="test content",
        text_preview="test content",
        distance=0.1,
        score=0.9,
        chunk_metadata={},
    )
    mock_report = RetrievalReport(
        knowledge_base="test-kb",
        query="test query",
        top_k=1,
        provider="deterministic-local",
        model="hash-8d",
        dimensions=8,
        distance_metric="cosine_distance",
        backend="pgvector",
        backend_metadata={},
        total_results=1,
        results=[mock_result],
    )

    monkeypatch.setattr(
        "ragrig.answer.service.search_knowledge_base",
        lambda **kwargs: mock_report,
    )

    with _create_session() as session:
        with pytest.raises(ProviderUnavailableError) as exc_info:
            generate_answer(
                session=session,
                knowledge_base_name="test-kb",
                query="test query",
            )

    assert exc_info.value.code == "provider_unavailable"
    assert exc_info.value.details["provider"] == "deterministic-local"
    # Error message must be sanitized, not exceed 500 chars
    assert len(exc_info.value.details["reason"]) <= 500


# ── ACL integration tests ─────────────────────────────────────────────────────


def test_protected_evidence_not_in_answer_prompt(tmp_path) -> None:
    """ACL-protected evidence chunks should not appear in the answer prompt."""
    docs = _seed_documents(
        tmp_path,
        {
            "public.txt": "public information about the system",
            "secret.txt": "top secret internal operations details",
        },
    )

    with _create_session() as session:
        ingest_local_directory(session=session, knowledge_base_name="fixture-local", root_path=docs)
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        # Mark secret chunks as protected
        from ragrig.db.models import Chunk

        chunks = session.scalars(select(Chunk)).all()
        for chunk in chunks:
            if "top secret" in chunk.text:
                chunk.metadata_json = {
                    **chunk.metadata_json,
                    "acl": {
                        "visibility": "protected",
                        "allowed_principals": ["alice"],
                        "denied_principals": [],
                        "acl_source": "test",
                        "acl_source_hash": "abc",
                        "inheritance": "document",
                    },
                }
        session.commit()

        report = generate_answer(
            session=session,
            knowledge_base_name="fixture-local",
            query="information about the system",
            top_k=5,
            principal_ids=["guest"],
            enforce_acl=True,
        )

    # Protected content must not be in evidence or answer
    for chunk in report.evidence_chunks:
        assert "top secret" not in chunk.text.lower()
    assert "top secret" not in report.answer.lower()


def test_protected_evidence_accessible_with_valid_principal(tmp_path) -> None:
    """ACL-protected evidence should be accessible with the right principal."""
    docs = _seed_documents(
        tmp_path,
        {
            "secret.txt": "classified operational details",
        },
    )

    with _create_session() as session:
        ingest_local_directory(session=session, knowledge_base_name="fixture-local", root_path=docs)
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        from ragrig.db.models import Chunk

        chunks = session.scalars(select(Chunk)).all()
        for chunk in chunks:
            chunk.metadata_json = {
                **chunk.metadata_json,
                "acl": {
                    "visibility": "protected",
                    "allowed_principals": ["alice"],
                    "denied_principals": [],
                    "acl_source": "test",
                    "acl_source_hash": "abc",
                    "inheritance": "document",
                },
            }
        session.commit()

        report = generate_answer(
            session=session,
            knowledge_base_name="fixture-local",
            query="classified operational details",
            top_k=5,
            principal_ids=["alice"],
            enforce_acl=True,
        )

    assert len(report.evidence_chunks) >= 1
    for chunk in report.evidence_chunks:
        assert "classified" in chunk.text.lower()


# ── Citation ID consistency ───────────────────────────────────────────────────


def test_citation_ids_match_evidence_chunks(tmp_path) -> None:
    docs = _seed_documents(tmp_path, {"guide.txt": "citation test content here"})

    with _create_session() as session:
        ingest_local_directory(session=session, knowledge_base_name="fixture-local", root_path=docs)
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        report = generate_answer(
            session=session,
            knowledge_base_name="fixture-local",
            query="citation test content here",
            top_k=3,
        )

    # All citation IDs in answer should match evidence
    evidence_ids = {ec.citation_id for ec in report.evidence_chunks}
    for citation in report.citations:
        assert citation.citation_id in evidence_ids
        found = False
        for ec in report.evidence_chunks:
            if ec.citation_id == citation.citation_id:
                assert ec.document_uri == citation.document_uri
                assert ec.chunk_index == citation.chunk_index
                found = True
                break
        assert found, f"Citation {citation.citation_id} not found in evidence chunks"


# ── API endpoint tests ────────────────────────────────────────────────────────


def _create_file_session_factory(database_path):
    engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
    Base.metadata.create_all(engine)

    def _factory() -> Session:
        return Session(engine, expire_on_commit=False)

    return _factory


@pytest.mark.anyio
async def test_answer_api_returns_grounded_answer(tmp_path) -> None:
    database_path = tmp_path / "answer-api.db"
    session_factory = _create_file_session_factory(database_path)

    docs = _seed_documents(tmp_path, {"guide.txt": "Answer API contract test content."})
    with session_factory() as session:
        ingest_local_directory(session=session, knowledge_base_name="fixture-local", root_path=docs)
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/retrieval/answer",
            json={
                "knowledge_base": "fixture-local",
                "query": "Answer API contract",
                "top_k": 3,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert "answer" in payload
    assert payload["answer"]
    assert payload["grounding_status"] == "grounded"
    assert payload["refusal_reason"] is None
    assert len(payload["citations"]) >= 1
    assert len(payload["evidence_chunks"]) >= 1
    assert payload["retrieval_trace"]["total_results"] >= 1
    # No secrets in response
    response_text = str(payload)
    assert "secret" not in response_text.lower()
    assert "api_key" not in response_text.lower()


@pytest.mark.anyio
async def test_answer_api_returns_refusal_when_no_evidence(tmp_path) -> None:
    database_path = tmp_path / "answer-refusal.db"
    session_factory = _create_file_session_factory(database_path)

    docs = _seed_documents(tmp_path, {"notes.txt": "some unrelated notes"})
    with session_factory() as session:
        # Ingest but do not index → zero retrieval results
        ingest_local_directory(session=session, knowledge_base_name="fixture-local", root_path=docs)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/retrieval/answer",
            json={
                "knowledge_base": "fixture-local",
                "query": "zzzz nothing matches this query",
                "top_k": 3,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["grounding_status"] == "refused"
    assert payload["refusal_reason"]
    assert payload["answer"] == ""
    assert payload["citations"] == []
    assert payload["evidence_chunks"] == []


@pytest.mark.anyio
async def test_answer_api_rejects_empty_query() -> None:
    app = create_app(check_database=lambda: None, session_factory=_create_session)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/retrieval/answer",
            json={
                "knowledge_base": "fixture-local",
                "query": "   ",
            },
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_query"


@pytest.mark.anyio
async def test_answer_api_returns_not_found_for_missing_kb() -> None:
    app = create_app(check_database=lambda: None, session_factory=_create_session)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/retrieval/answer",
            json={
                "knowledge_base": "nonexistent-kb",
                "query": "test",
            },
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "knowledge_base_not_found"


# ── Provider error sanitisation ───────────────────────────────────────────────


@pytest.mark.anyio
async def test_answer_api_sanitizes_provider_error(tmp_path, monkeypatch) -> None:
    """Provider errors must be sanitized — no raw prompts or secrets leaked."""

    class ExplodingProvider:
        def generate(self, query, evidence):
            raise RuntimeError(
                "api_key=sk-abc123 secret=mysecret full prompt content leaked here " * 20
            )

    monkeypatch.setattr(
        "ragrig.answer.service.get_answer_provider",
        lambda provider, model=None: ExplodingProvider(),
    )

    import uuid

    from ragrig.retrieval import RetrievalReport, RetrievalResult

    mock_result = RetrievalResult(
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        chunk_index=0,
        document_uri="test.txt",
        source_uri="/tmp",
        text="test content",
        text_preview="test content",
        distance=0.1,
        score=0.9,
        chunk_metadata={},
    )
    mock_report = RetrievalReport(
        knowledge_base="test-kb",
        query="test query",
        top_k=1,
        provider="deterministic-local",
        model="hash-8d",
        dimensions=8,
        distance_metric="cosine_distance",
        backend="pgvector",
        backend_metadata={},
        total_results=1,
        results=[mock_result],
    )

    monkeypatch.setattr(
        "ragrig.answer.service.search_knowledge_base",
        lambda **kwargs: mock_report,
    )

    database_path = tmp_path / "answer-error-sanitize.db"
    session_factory = _create_file_session_factory(database_path)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/retrieval/answer",
            json={
                "knowledge_base": "test-kb",
                "query": "test query",
            },
        )

    assert response.status_code == 503
    payload = response.json()
    error_msg = payload.get("error", {}).get("message", "")
    assert len(error_msg) <= 700  # generous upper bound
    # The API error should not expose raw secrets
    assert "sk-abc123" not in str(payload)


# ── get_answer_provider tests ──────────────────────────────────────────────────


def test_get_answer_provider_returns_deterministic() -> None:
    provider = get_answer_provider("deterministic-local")
    assert isinstance(provider, DeterministicAnswerProvider)


def test_get_answer_provider_returns_deterministic_for_tests() -> None:
    provider = get_answer_provider("deterministic-local", model="hash-8d")
    answer, citations = provider.generate(
        "test",
        [
            EvidenceChunk(
                citation_id="cit-1",
                document_uri="doc.txt",
                chunk_id="c1",
                chunk_index=0,
                text="test content",
                score=0.9,
                distance=0.1,
            )
        ],
    )
    assert len(citations) >= 1
    assert "cit-1" in answer
    assert "test" in answer


def test_llm_answer_provider_with_evidence(monkeypatch) -> None:
    """LLMAnswerProvider should generate answer using chat capability."""
    from ragrig.answer.provider import LLMAnswerProvider

    fake_response = {
        "choices": [{"message": {"content": "Based on evidence [cit-1], the answer is 42."}}]
    }

    class FakeProvider:
        def chat(self, messages):
            assert any("question" in str(m).lower() for m in messages)
            return fake_response

    provider = LLMAnswerProvider(FakeProvider(), model="test-model")
    evidence = [
        EvidenceChunk(
            citation_id="cit-1",
            document_uri="doc.txt",
            chunk_id="c1",
            chunk_index=0,
            text="test content",
            score=0.9,
            distance=0.1,
        )
    ]

    answer, citations = provider.generate("what is the answer?", evidence)
    assert "42" in answer
    assert citations == ["cit-1"]


def test_llm_answer_provider_without_evidence(monkeypatch) -> None:
    """LLMAnswerProvider should refuse when no evidence is provided."""
    from ragrig.answer.provider import LLMAnswerProvider

    class FakeProvider:
        def chat(self, messages):
            raise AssertionError("should not be called")

    provider = LLMAnswerProvider(FakeProvider())
    answer, citations = provider.generate("test", [])
    assert "cannot answer" in answer.lower()
    assert citations == []


def test_llm_answer_provider_falls_back_to_generate(monkeypatch) -> None:
    """LLMAnswerProvider should fall back to generate() when chat() fails."""
    from ragrig.answer.provider import LLMAnswerProvider

    class FakeProvider:
        def chat(self, messages):
            raise RuntimeError("chat not available")

        def generate(self, prompt):
            return "Answer from generate: see [cit-1] for details."

    provider = LLMAnswerProvider(FakeProvider(), model="test-model")
    evidence = [
        EvidenceChunk(
            citation_id="cit-1",
            document_uri="doc.txt",
            chunk_id="c1",
            chunk_index=0,
            text="test content",
            score=0.9,
            distance=0.1,
        )
    ]

    answer, citations = provider.generate("test", evidence)
    assert "generate" in answer
    assert citations == ["cit-1"]


def test_llm_answer_provider_no_response_content(monkeypatch) -> None:
    """LLMAnswerProvider should handle response with no content field."""
    from ragrig.answer.provider import LLMAnswerProvider

    class FakeProvider:
        def chat(self, messages):
            return {"choices": [{"message": {}}]}

    provider = LLMAnswerProvider(FakeProvider(), model="test-model")
    evidence = [
        EvidenceChunk(
            citation_id="cit-1",
            document_uri="doc.txt",
            chunk_id="c1",
            chunk_index=0,
            text="test content",
            score=0.9,
            distance=0.1,
        )
    ]

    answer, citations = provider.generate("test", evidence)
    assert answer == ""
    assert citations == []


def test_deterministic_answer_provider_with_long_text() -> None:
    """DeterministicAnswerProvider truncates long texts with '...' suffix."""
    provider = DeterministicAnswerProvider()
    long_text = "x" * 200
    evidence = [
        EvidenceChunk(
            citation_id="cit-1",
            document_uri="long.txt",
            chunk_id="chunk-1",
            chunk_index=0,
            text=long_text,
            score=0.95,
            distance=0.05,
        ),
    ]

    answer, citation_ids = provider.generate(query="test", evidence=evidence)
    assert len(answer) > 0
    assert citation_ids == ["cit-1"]
    assert "..." in answer


def test_llm_answer_provider_both_chat_and_generate_fail(monkeypatch) -> None:
    """LLMAnswerProvider raises ProviderError when both chat() and generate() fail."""
    from ragrig.answer.provider import LLMAnswerProvider
    from ragrig.providers import ProviderError

    class FailingProvider:
        def chat(self, messages):
            raise RuntimeError("chat failed")

        def generate(self, prompt):
            raise RuntimeError("generate also failed")

    provider = LLMAnswerProvider(FailingProvider(), model="test-model")
    evidence = [
        EvidenceChunk(
            citation_id="cit-1",
            document_uri="doc.txt",
            chunk_id="c1",
            chunk_index=0,
            text="test content",
            score=0.9,
            distance=0.1,
        )
    ]

    with pytest.raises(ProviderError) as exc_info:
        provider.generate("test query", evidence)

    assert exc_info.value.code == "answer_generation_failed"


def test_get_answer_provider_rejects_unsupported_capability(monkeypatch) -> None:
    """get_answer_provider should raise ProviderError for providers without chat/generate."""
    from ragrig.providers import (
        ProviderCapability,
        ProviderError,
        ProviderKind,
        ProviderMetadata,
        ProviderRetryPolicy,
    )

    fake_metadata = ProviderMetadata(
        name="embedding-only",
        kind=ProviderKind.LOCAL,
        description="Embedding-only provider",
        capabilities={ProviderCapability.EMBEDDING},
        default_dimensions=8,
        max_dimensions=None,
        default_context_window=None,
        max_context_window=None,
        required_secrets=[],
        config_schema={},
        sdk_protocol="in-process",
        healthcheck="check",
        failure_modes=["crash"],
        retry_policy=ProviderRetryPolicy(max_attempts=1, backoff_seconds=0.0),
        audit_fields=[],
        metric_fields=[],
        intended_uses=["embed"],
    )

    class FakeBaseProvider:
        metadata = fake_metadata

    class FakeRegistry:
        def get(self, name, **config):
            return FakeBaseProvider()

    monkeypatch.setattr("ragrig.providers._provider_registry", FakeRegistry())

    with pytest.raises(ProviderError) as exc_info:
        get_answer_provider("embedding-only")
    assert exc_info.value.code == "unsupported_capability"


def test_llm_answer_provider_response_with_direct_content(monkeypatch) -> None:
    """LLMAnswerProvider should handle response with 'content' key."""
    from ragrig.answer.provider import LLMAnswerProvider

    class FakeProvider:
        def chat(self, messages):
            return {"content": "Direct answer with [cit-1] evidence."}

    provider = LLMAnswerProvider(FakeProvider(), model="test-model")
    evidence = [
        EvidenceChunk(
            citation_id="cit-1",
            document_uri="doc.txt",
            chunk_id="c1",
            chunk_index=0,
            text="test content",
            score=0.9,
            distance=0.1,
        )
    ]

    answer, citations = provider.generate("test", evidence)
    assert "Direct answer" in answer
    assert citations == ["cit-1"]


def test_llm_answer_provider_response_with_response_key(monkeypatch) -> None:
    """LLMAnswerProvider should handle response with 'response' key."""
    from ragrig.answer.provider import LLMAnswerProvider

    class FakeProvider:
        def chat(self, messages):
            return {"response": "Answer from response key [cit-1]."}

    provider = LLMAnswerProvider(FakeProvider(), model="test-model")
    evidence = [
        EvidenceChunk(
            citation_id="cit-1",
            document_uri="doc.txt",
            chunk_id="c1",
            chunk_index=0,
            text="test content",
            score=0.9,
            distance=0.1,
        )
    ]

    answer, citations = provider.generate("test", evidence)
    assert "Answer from response key" in answer
    assert citations == ["cit-1"]


def test_llm_answer_provider_empty_response(monkeypatch) -> None:
    """LLMAnswerProvider should handle completely empty response dict."""
    from ragrig.answer.provider import LLMAnswerProvider

    class FakeProvider:
        def chat(self, messages):
            return {}

    provider = LLMAnswerProvider(FakeProvider(), model="test-model")
    evidence = [
        EvidenceChunk(
            citation_id="cit-1",
            document_uri="doc.txt",
            chunk_id="c1",
            chunk_index=0,
            text="test content",
            score=0.9,
            distance=0.1,
        )
    ]

    answer, citations = provider.generate("test", evidence)
    assert answer == ""
    assert citations == []


def test_get_answer_provider_returns_llm_wrapper(monkeypatch) -> None:
    """get_answer_provider should return LLMAnswerProvider for non-deterministic providers."""
    from ragrig.providers import (
        ProviderCapability,
        ProviderKind,
        ProviderMetadata,
        ProviderRetryPolicy,
    )

    fake_metadata = ProviderMetadata(
        name="model.test",
        kind=ProviderKind.LOCAL,
        description="Test provider",
        capabilities={ProviderCapability.CHAT},
        default_dimensions=None,
        max_dimensions=None,
        default_context_window=4096,
        max_context_window=8192,
        required_secrets=[],
        config_schema={},
        sdk_protocol="in-process",
        healthcheck="check",
        failure_modes=["crash"],
        retry_policy=ProviderRetryPolicy(max_attempts=1, backoff_seconds=0.0),
        audit_fields=[],
        metric_fields=[],
        intended_uses=["test"],
    )

    class FakeRegistry:
        def get(self, name, **config):
            return FakeBaseProvider()

    from ragrig.answer.provider import LLMAnswerProvider

    class FakeBaseProvider:
        metadata = fake_metadata

    monkeypatch.setattr("ragrig.providers._provider_registry", FakeRegistry())

    provider = get_answer_provider("model.test")
    assert isinstance(provider, LLMAnswerProvider)


def test_generate_answer_degraded_with_invalid_citations(monkeypatch) -> None:
    """When provider returns citation IDs not in evidence, grounding is degraded."""
    import uuid

    from ragrig.retrieval import RetrievalReport, RetrievalResult

    mock_result = RetrievalResult(
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        chunk_index=0,
        document_uri="test.txt",
        source_uri="/tmp",
        text="test content",
        text_preview="test content",
        distance=0.1,
        score=0.9,
        chunk_metadata={},
    )
    mock_report = RetrievalReport(
        knowledge_base="test-kb",
        query="test query",
        top_k=1,
        provider="deterministic-local",
        model="hash-8d",
        dimensions=8,
        distance_metric="cosine_distance",
        backend="pgvector",
        backend_metadata={},
        total_results=1,
        results=[mock_result],
    )

    class BadCitationProvider:
        def generate(self, query, evidence):
            return "Answer with [cit-99] fake citation.", ["cit-99", "cit-100"]

    monkeypatch.setattr(
        "ragrig.answer.service.search_knowledge_base",
        lambda **kwargs: mock_report,
    )
    monkeypatch.setattr(
        "ragrig.answer.service.get_answer_provider",
        lambda provider, model=None: BadCitationProvider(),
    )

    with _create_session() as session:
        report = generate_answer(
            session=session,
            knowledge_base_name="test-kb",
            query="test query",
        )

    assert report.grounding_status == "degraded"
    assert report.refusal_reason is not None
    assert "cit-99" in report.refusal_reason or "cit-100" in report.refusal_reason


def test_generate_answer_degraded_with_no_citations(monkeypatch) -> None:
    """When provider returns no citation IDs, grounding is degraded."""
    import uuid

    from ragrig.retrieval import RetrievalReport, RetrievalResult

    mock_result = RetrievalResult(
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        chunk_index=0,
        document_uri="test.txt",
        source_uri="/tmp",
        text="test content",
        text_preview="test content",
        distance=0.1,
        score=0.9,
        chunk_metadata={},
    )
    mock_report = RetrievalReport(
        knowledge_base="test-kb",
        query="test query",
        top_k=1,
        provider="deterministic-local",
        model="hash-8d",
        dimensions=8,
        distance_metric="cosine_distance",
        backend="pgvector",
        backend_metadata={},
        total_results=1,
        results=[mock_result],
    )

    class NoCitationProvider:
        def generate(self, query, evidence):
            return "Answer without any citations.", []

    monkeypatch.setattr(
        "ragrig.answer.service.search_knowledge_base",
        lambda **kwargs: mock_report,
    )
    monkeypatch.setattr(
        "ragrig.answer.service.get_answer_provider",
        lambda provider, model=None: NoCitationProvider(),
    )

    with _create_session() as session:
        report = generate_answer(
            session=session,
            knowledge_base_name="test-kb",
            query="test query",
        )

    assert report.grounding_status == "degraded"
    assert report.refusal_reason is not None
    assert "no citations" in report.refusal_reason.lower()
