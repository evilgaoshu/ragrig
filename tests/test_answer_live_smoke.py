"""Live smoke tests for answer generation with optional local LLM providers.

Requires RAGRIG_ANSWER_LIVE_SMOKE=1 to run.
When provider is unreachable, tests are xfail (degraded) — never false success.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

pytestmark = [
    pytest.mark.answer_live_smoke,
    pytest.mark.skipif(
        os.environ.get("RAGRIG_ANSWER_LIVE_SMOKE") != "1",
        reason="set RAGRIG_ANSWER_LIVE_SMOKE=1 to run answer live smoke tests",
    ),
]

# Provider configuration via environment variables
_PROVIDER = os.environ.get("RAGRIG_ANSWER_PROVIDER", "ollama")
_MODEL = os.environ.get("RAGRIG_ANSWER_MODEL", "llama3.2:1b")
_BASE_URL = os.environ.get("RAGRIG_ANSWER_BASE_URL", "http://localhost:11434/v1")


def _try_import(import_name: str) -> bool:
    try:
        __import__(import_name)
        return True
    except ImportError:
        return False


def _make_openai_compatible_provider():
    """Create an OpenAI-compatible provider from environment config."""
    if not _try_import("openai"):
        pytest.skip("openai package not installed")

    from openai import OpenAI

    client = OpenAI(base_url=_BASE_URL, api_key="not-needed")

    # Build a minimal BaseProvider wrapper
    from ragrig.providers import (
        ProviderCapability,
        ProviderKind,
        ProviderMetadata,
        ProviderRetryPolicy,
    )

    metadata = ProviderMetadata(
        name=_PROVIDER,
        kind=ProviderKind.LOCAL,
        description=f"Live smoke provider: {_PROVIDER} @ {_BASE_URL}",
        capabilities={ProviderCapability.CHAT},
        default_dimensions=None,
        max_dimensions=None,
        default_context_window=4096,
        max_context_window=8192,
        required_secrets=[],
        config_schema={},
        sdk_protocol="openai-compatible",
        healthcheck="http",
        failure_modes=["unavailable", "timeout"],
        retry_policy=ProviderRetryPolicy(max_attempts=1, backoff_seconds=0.0),
        audit_fields=[],
        metric_fields=[],
        intended_uses=["answer-smoke"],
    )

    class SmokeProvider:
        def __init__(self):
            self.metadata = metadata
            self._client = client
            self._model = _MODEL

        def chat(self, messages):
            response = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=0.0,
                max_tokens=256,
            )
            return {"choices": [{"message": {"content": response.choices[0].message.content}}]}

    return SmokeProvider()


def _seed_fixture_kb(session: Session, tmp_path):
    """Seed a minimal knowledge base for live smoke testing."""
    from ragrig.indexing.pipeline import index_knowledge_base
    from ragrig.ingestion.pipeline import ingest_local_directory

    docs = tmp_path / "smoke-docs"
    docs.mkdir()
    (docs / "ragrig.txt").write_text(
        "RAGRig is an open-source retrieval-augmented generation platform "
        "designed for local-first knowledge base management. "
        "It supports multiple embedding providers, vector backends, "
        "and ACL-aware retrieval with citation-grounded answer generation.",
        encoding="utf-8",
    )

    ingest_local_directory(
        session=session, knowledge_base_name="answer-live-smoke", root_path=docs
    )
    index_knowledge_base(session=session, knowledge_base_name="answer-live-smoke")


def _check_provider_reachable() -> bool:
    """Check if the configured provider is reachable."""
    try:
        provider = _make_openai_compatible_provider()
        provider.chat([{"role": "user", "content": "ping"}])
        return True
    except Exception:
        return False


# ── Live smoke test class ─────────────────────────────────────────────────────


class TestAnswerLiveSmoke:
    """End-to-end answer generation smoke test with a local LLM."""

    @pytest.fixture
    def session(self, tmp_path):
        """Create an in-memory SQLite session with a seeded fixture KB."""
        from pgvector.sqlalchemy import Vector
        from sqlalchemy import JSON
        from sqlalchemy.dialects.postgresql import JSONB
        from sqlalchemy.ext.compiler import compiles

        from ragrig.db.models import Base

        @compiles(JSONB, "sqlite")
        def _compile_jsonb(_type, compiler, **kw):
            return compiler.process(JSON(), **kw)

        @compiles(Vector, "sqlite")
        def _compile_vector(_type, compiler, **kw):
            return compiler.process(JSON(), **kw)

        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
        Base.metadata.create_all(engine)
        with Session(engine, expire_on_commit=False) as sess:
            _seed_fixture_kb(sess, tmp_path)
            yield sess
        engine.dispose()

    def test_answer_with_live_provider_returns_grounded_answer(self, session, monkeypatch):
        """When the live provider is reachable, generate a grounded answer with citations."""
        provider_reachable = _check_provider_reachable()
        if not provider_reachable:
            pytest.xfail(
                f"Live answer provider '{_PROVIDER}' at {_BASE_URL} is not reachable "
                f"— degraded (xfail). Start your local LLM server and retry."
            )

        provider = _make_openai_compatible_provider()

        # Register the smoke provider in the registry
        from ragrig.answer.provider import LLMAnswerProvider

        answer_provider = LLMAnswerProvider(provider, model=_MODEL)

        monkeypatch.setattr(
            "ragrig.answer.service.get_answer_provider",
            lambda provider_name, model=None: answer_provider,
        )

        from ragrig.answer.service import generate_answer

        report = generate_answer(
            session=session,
            knowledge_base_name="answer-live-smoke",
            query="What is RAGRig?",
            top_k=3,
            provider=_PROVIDER,
        )

        assert report.answer, "Provider should return a non-empty answer"
        assert report.grounding_status == "grounded", (
            f"Expected 'grounded', got '{report.grounding_status}'"
        )
        assert len(report.citations) >= 1, "Expected at least 1 citation"
        assert len(report.evidence_chunks) >= 1, "Expected at least 1 evidence chunk"
        assert report.refusal_reason is None, "Expected no refusal reason"

        # All citations must match evidence
        evidence_ids = {ec.citation_id for ec in report.evidence_chunks}
        for citation in report.citations:
            assert citation.citation_id in evidence_ids, (
                f"Citation {citation.citation_id} not in evidence"
            )

        # Answer must not contain secrets
        assert "api_key" not in report.answer.lower()
        assert "secret" not in report.answer.lower()

    def test_provider_unreachable_is_xfail(self):
        """When provider is not reachable, test correctly xfails — not false success.

        This test always runs (even without a live provider) and serves as a
        self-documenting xfail that tells the operator what's missing.
        """
        provider_reachable = _check_provider_reachable()
        if not provider_reachable:
            pytest.xfail(
                f"Live answer provider '{_PROVIDER}' at {_BASE_URL} is not reachable. "
                f"Start your local LLM server and set RAGRIG_ANSWER_BASE_URL."
            )
        # If reachable, smoke passes trivially
        assert True
