from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ragrig.config import Settings
from ragrig.db.models import AuditEvent, Base, KnowledgeBase, UsageEvent
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.knowledge_base_config import StageModelPolicyRequest
from ragrig.main import create_app
from ragrig.providers import (
    BaseProvider,
    DeterministicLocalProvider,
    ProviderCapability,
    ProviderKind,
    ProviderMetadata,
    ProviderRetryPolicy,
)

pytestmark = [pytest.mark.integration]


_FAKE_METADATA = ProviderMetadata(
    name="fake-stage-provider",
    kind=ProviderKind.LOCAL,
    description="Fake provider for stage policy tests.",
    capabilities={ProviderCapability.CHAT, ProviderCapability.GENERATE},
    default_dimensions=None,
    max_dimensions=None,
    default_context_window=32_000,
    max_context_window=32_000,
    required_secrets=[],
    config_schema={},
    sdk_protocol="test",
    healthcheck="not-required",
    failure_modes=[],
    retry_policy=ProviderRetryPolicy(max_attempts=1, backoff_seconds=0),
    audit_fields=[],
    metric_fields=[],
    intended_uses=["test"],
)


class _FakeStageProvider(BaseProvider):
    metadata = _FAKE_METADATA

    def chat(self, messages: list[dict[str, object]]) -> dict[str, object]:
        prompt = str(messages[-1]["content"])
        if "Sources:\n" in prompt:
            sources = json.loads(prompt.split("Sources:\n", maxsplit=1)[1])
            source = sources[0]
            payload = {
                "entities": [
                    {
                        "name": "AlphaProject",
                        "type": "PROJECT",
                        "confidence": 0.9,
                        "source_chunk_id": source["source_chunk_id"],
                    }
                ],
                "relationships": [],
                "claims": [],
            }
        else:
            payload = {
                "summary": "Policy-selected understanding.",
                "table_of_contents": [],
                "entities": [],
                "key_claims": [],
                "limitations": [],
                "source_spans": [],
            }
        return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    def generate(self, prompt: str) -> str:
        if "impartial judge" in prompt:
            return "SCORE: 5\nREASON: The answer is fully supported."
        return str(self.chat([{"content": prompt}])["choices"][0]["message"]["content"])


class _FakeRegistry:
    def get(self, name: str, **config: object) -> BaseProvider:
        if name == "deterministic-local":
            return DeterministicLocalProvider(dimensions=int(config.get("dimensions", 8)))
        return _FakeStageProvider()


def _session_factory(tmp_path: Path) -> tuple[Callable[[], Session], str]:
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'stage-policy.db'}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text(
        "# Guide\n\nAlphaProject stores auditable retrieval evidence.",
        encoding="utf-8",
    )
    with Session(engine, expire_on_commit=False) as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="stage-policy-kb",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="stage-policy-kb")
        kb = session.scalars(
            select(KnowledgeBase).where(KnowledgeBase.name == "stage-policy-kb")
        ).one()
        kb_id = str(kb.id)

    def factory() -> Session:
        return Session(engine, expire_on_commit=False)

    return factory, kb_id


def _client(
    tmp_path: Path,
    *,
    settings: Settings | None = None,
) -> tuple[TestClient, Callable[[], Session], str]:
    factory, kb_id = _session_factory(tmp_path)
    app = create_app(
        check_database=lambda: None,
        session_factory=factory,
        settings=settings or Settings(ragrig_auth_enabled=False),
    )
    return TestClient(app), factory, kb_id


def _selection(payload: dict[str, object], stage: str) -> dict[str, object]:
    selections = payload["stage_model_selection"]
    assert isinstance(selections, list)
    return next(item for item in selections if item["stage"] == stage)


def test_stage_model_policy_schema_rejects_invalid_values() -> None:
    StageModelPolicyRequest(
        policy={
            "query": {
                "provider": "deterministic-local",
                "model": "hash-8d",
                "config": {"api_key": "env:QUERY_KEY"},
                "max_tokens": 100,
                "budget_hint_usd": 0,
            }
        }
    )
    invalid = [
        {"unknown": {"provider": "x"}},
        {"query": {"provider": 42}},
        {"query": {"model": 42}},
        {"query": {"config": "not-an-object"}},
        {"query": {"max_tokens": 0}},
        {"query": {"budget_hint_usd": -0.1}},
    ]
    for policy in invalid:
        with pytest.raises(ValidationError):
            StageModelPolicyRequest(policy=policy)


def test_stage_model_policy_api_persists_redacts_and_audits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QUERY_KEY", "super-secret-value")
    client, factory, kb_id = _client(tmp_path)
    policy = {
        "query": {
            "provider": "deterministic-local",
            "config": {"api_key": "env:QUERY_KEY", "raw_secret": "do-not-return"},
            "budget_hint_usd": 0.02,
            "tags": ["interactive"],
        },
        "parse": {
            "provider": "docling-service",
            "enabled": False,
            "notes": "Stored for visibility; parser execution remains separately configured.",
        },
    }

    saved = client.put(f"/knowledge-bases/{kb_id}/stage-model-policy", json={"policy": policy})
    assert saved.status_code == 200, saved.text
    assert saved.json()["stages"] == ["parse", "query"]
    assert saved.json()["policy"]["query"]["has_config"] is True
    assert saved.json()["policy"]["query"]["config_keys"] == ["api_key", "raw_secret"]
    assert "super-secret-value" not in saved.text
    assert "do-not-return" not in saved.text

    loaded = client.get(f"/knowledge-bases/{kb_id}/stage-model-policy")
    assert loaded.status_code == 200
    assert loaded.json()["policy"] == saved.json()["policy"]
    invalid = client.put(
        f"/knowledge-bases/{kb_id}/stage-model-policy",
        json={"policy": {"unknown": {"provider": "x"}}},
    )
    assert invalid.status_code == 422

    with factory() as session:
        kb = session.get(KnowledgeBase, uuid.UUID(kb_id))
        assert kb is not None
        assert kb.metadata_json["stage_model_policy"]["query"]["config"]["raw_secret"] == (
            "do-not-return"
        )
        audit = session.scalars(
            select(AuditEvent).where(AuditEvent.event_type == "stage_model_policy_update")
        ).one()
        assert audit.payload_json == {"stages": ["parse", "query"]}


def test_answer_stage_policy_priority_trace_and_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QUERY_KEY", "super-secret-value")
    monkeypatch.setattr("ragrig.retrieval.get_provider_registry", lambda: _FakeRegistry())
    monkeypatch.setattr("ragrig.providers.get_provider_registry", lambda: _FakeRegistry())
    client, factory, kb_id = _client(tmp_path)
    policy = {
        "query": {
            "provider": "deterministic-local",
            "config": {"api_key": "env:QUERY_KEY"},
        },
        "rerank": {"provider": "fake", "model": "policy-reranker"},
        "answer": {"provider": "deterministic-local", "model": "policy-answer"},
        "judge": {"enabled": True, "provider": "fake-stage-provider", "model": "judge-model"},
    }
    saved_policy = client.put(
        f"/knowledge-bases/{kb_id}/stage-model-policy",
        json={"policy": policy},
    )
    assert saved_policy.status_code == 200
    assert (
        client.put(
            f"/knowledge-bases/{kb_id}/role-model-config",
            json={
                "config": {
                    "reviewer": {
                        "answer_provider": "deterministic-local",
                        "answer_model": "role-answer",
                    }
                }
            },
        ).status_code
        == 200
    )

    policy_response = client.post(
        "/retrieval/answer",
        json={"knowledge_base": "stage-policy-kb", "query": "What is stored?"},
    )
    assert policy_response.status_code == 200, policy_response.text
    assert policy_response.json()["model"] == "policy-answer"
    assert _selection(policy_response.json(), "query")["source"] == "stage_model_policy"
    assert _selection(policy_response.json(), "answer")["source"] == "stage_model_policy"
    assert _selection(policy_response.json(), "judge")["provider"] == "fake-stage-provider"
    assert policy_response.json()["retrieval_trace"]["stage_model_selection"]

    role_response = client.post(
        "/retrieval/answer",
        json={
            "knowledge_base": "stage-policy-kb",
            "query": "What is stored?",
            "role": "reviewer",
        },
    )
    assert role_response.status_code == 200, role_response.text
    assert role_response.json()["model"] == "role-answer"
    assert _selection(role_response.json(), "answer")["source"] == "role_model_config"

    request_response = client.post(
        "/retrieval/answer",
        json={
            "knowledge_base": "stage-policy-kb",
            "query": "What is stored?",
            "role": "reviewer",
            "provider": "deterministic-local",
            "answer_provider": "deterministic-local",
            "answer_model": "request-answer",
        },
    )
    assert request_response.status_code == 200, request_response.text
    assert request_response.json()["model"] == "request-answer"
    assert _selection(request_response.json(), "query")["source"] == "request"
    assert _selection(request_response.json(), "answer")["source"] == "request"
    assert "super-secret-value" not in request_response.text

    with factory() as session:
        usage_rows = session.scalars(select(UsageEvent)).all()
        answer_usage = next(row for row in usage_rows if row.operation == "answer_generation")
        assert answer_usage.metadata_json["stage"] == "answer"
        assert answer_usage.metadata_json["model_selection"]["source"] in {
            "stage_model_policy",
            "role_model_config",
            "request",
        }
        assert "super-secret-value" not in json.dumps(answer_usage.metadata_json)
        judge_usage = next(row for row in usage_rows if row.operation == "faithfulness_judge")
        assert judge_usage.metadata_json["stage"] == "judge"
        assert judge_usage.metadata_json["model_selection"]["model"] == "judge-model"


def test_extract_and_understand_stages_use_stage_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _factory, kb_id = _client(tmp_path)
    monkeypatch.setattr("ragrig.services.knowledge.get_provider_registry", lambda: _FakeRegistry())
    monkeypatch.setattr(
        "ragrig.providers.get_provider_registry",
        lambda: _FakeRegistry(),
    )
    policy = {
        "extract": {"provider": "fake-stage-provider", "model": "extract-model"},
        "understand": {
            "provider": "fake-stage-provider",
            "model": "understand-model",
            "config": {"profile_id": "stage.understand.v1"},
        },
    }
    saved_policy = client.put(
        f"/knowledge-bases/{kb_id}/stage-model-policy",
        json={"policy": policy},
    )
    assert saved_policy.status_code == 200

    graph = client.post(f"/knowledge-bases/{kb_id}/knowledge-graph/rebuild", json={})
    assert graph.status_code == 200, graph.text
    assert graph.json()["trace"]["extractor_name"] == "provider-backed"
    assert graph.json()["trace"]["provider"] == "fake-stage-provider"
    assert graph.json()["trace"]["stage_model_selection"][0]["source"] == "stage_model_policy"

    understood = client.post(f"/knowledge-bases/{kb_id}/understand-all", json={})
    assert understood.status_code == 200, understood.text
    assert understood.json()["profile_id"] == "stage.understand.v1"
    selection = understood.json()["stage_model_selection"][0]
    assert selection["provider"] == "fake-stage-provider"
    assert selection["model"] == "understand-model"
    assert selection["source"] == "stage_model_policy"


def test_stage_model_policy_put_requires_editor(tmp_path: Path) -> None:
    settings = Settings(ragrig_auth_enabled=True, ragrig_open_registration=True)
    client, _factory, kb_id = _client(tmp_path, settings=settings)
    owner = client.post(
        "/auth/register",
        json={"email": "owner@example.com", "password": "hunter2hunter2"},
    )
    viewer = client.post(
        "/auth/register",
        json={"email": "viewer@example.com", "password": "hunter2hunter2"},
    )
    owner_headers = {"Authorization": f"Bearer {owner.json()['token']}"}
    viewer_headers = {"Authorization": f"Bearer {viewer.json()['token']}"}

    denied = client.put(
        f"/knowledge-bases/{kb_id}/stage-model-policy",
        json={"policy": {"answer": {"provider": "deterministic-local"}}},
        headers=viewer_headers,
    )
    assert denied.status_code == 403

    saved = client.put(
        f"/knowledge-bases/{kb_id}/stage-model-policy",
        json={"policy": {"answer": {"provider": "deterministic-local"}}},
        headers=owner_headers,
    )
    assert saved.status_code == 200
