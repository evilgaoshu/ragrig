from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from ragrig.db.models import AuditEvent, Base, Chunk, DocumentVersion
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.main import create_app


def _client_and_factory(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'chunk-review.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    app = create_app(check_database=lambda: None, session_factory=factory)
    return TestClient(app), factory


def test_chunk_preview_api_uses_real_template_and_returns_stable_errors(tmp_path) -> None:
    client, _ = _client_and_factory(tmp_path)

    templates = client.get("/chunking/templates")
    assert templates.status_code == 200
    assert {item["id"] for item in templates.json()["items"]} == {
        "char_window_v1",
        "paragraph_v1",
        "heading_v1",
        "sentence_v1",
        "parent_child_v1",
    }

    response = client.post(
        "/chunking/preview",
        json={
            "text": "First paragraph.\n\nSecond paragraph.",
            "template_id": "paragraph_v1",
            "parameters": {"chunk_size": 20, "chunk_overlap": 2},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["chunks"]
    assert payload["chunks"][0]["metadata"]["chunk_template_id"] == "paragraph_v1"
    assert payload["chunks"][0]["metadata"]["split_reason"] == "paragraph_boundary"
    assert payload["chunks"][0]["split_explanation"]

    invalid = client.post(
        "/chunking/preview",
        json={"text": "text", "template_id": "missing_v1", "parameters": {}},
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"] == "chunk_template_not_found"

    invalid_parameters = client.post(
        "/chunking/preview",
        json={
            "text": "text",
            "template_id": "char_window_v1",
            "parameters": {"chunk_size": 10, "chunk_overlap": 10},
        },
    )
    assert invalid_parameters.status_code == 400
    assert invalid_parameters.json()["error"] == "invalid_chunk_parameters"


def test_manual_chunk_override_is_audited_stale_and_applied_on_reindex(tmp_path) -> None:
    client, factory = _client_and_factory(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    source_text = "Alpha beta gamma delta epsilon zeta eta theta."
    (docs / "guide.txt").write_text(source_text, encoding="utf-8")

    with factory() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")
        version = session.scalar(select(DocumentVersion))
        assert version is not None
        version_id = str(version.id)
        extracted_text = version.extracted_text

    review = client.get(f"/document-versions/{version_id}/chunk-review")
    assert review.status_code == 200
    original = review.json()["items"][0]
    split_at = original["char_start"] + 17
    save = client.put(
        f"/document-versions/{version_id}/chunk-override",
        headers={"X-Operator": "reviewer@example.test"},
        json={
            "reason": "Separate the named concepts",
            "template_id": original["metadata"]["chunk_template_id"],
            "template_parameters": original["metadata"]["template_parameters"],
            "chunks": [
                {
                    "char_start": original["char_start"],
                    "char_end": split_at,
                    "split_reason": "manual_split",
                },
                {
                    "char_start": split_at,
                    "char_end": original["char_end"],
                    "split_reason": "manual_split",
                },
            ],
            "operations": [
                {
                    "operation": "split",
                    "before": {"chunk_index": original["chunk_index"]},
                    "after_count": 2,
                }
            ],
        },
    )

    assert save.status_code == 200
    assert save.json()["index_status"]["reindex_required"] is True
    assert save.json()["override"]["status"] == "pending_reindex"

    with factory() as session:
        version = session.get(DocumentVersion, version.id)
        assert version is not None
        assert version.extracted_text == extracted_text
        assert version.metadata_json["chunk_index_status"]["status"] == "stale"
        audit = session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "chunk_override_save")
        )
        assert audit is not None
        assert audit.actor == "reviewer@example.test"
        assert audit.payload_json["before_chunk_count"] == 1
        assert audit.payload_json["after_chunk_count"] == 2

    reindex = client.post(
        f"/document-versions/{version_id}/chunk-override/reindex",
        headers={"X-Operator": "reviewer@example.test"},
    )
    assert reindex.status_code == 200
    assert reindex.json()["indexed_count"] == 1
    assert reindex.json()["chunk_count"] == 2

    with factory() as session:
        version = session.get(DocumentVersion, version.id)
        chunks = list(
            session.scalars(
                select(Chunk)
                .where(Chunk.document_version_id == version.id)
                .order_by(Chunk.chunk_index)
            )
        )
        assert version.metadata_json["chunk_index_status"]["status"] == "current"
        assert [chunk.metadata_json["split_reason"] for chunk in chunks] == [
            "manual_split",
            "manual_split",
        ]
        assert all(chunk.metadata_json["document_uri"].endswith("guide.txt") for chunk in chunks)
        assert [(chunk.char_start, chunk.char_end) for chunk in chunks] == [
            (0, split_at),
            (split_at, len(source_text)),
        ]

    merge = client.put(
        f"/document-versions/{version_id}/chunk-override",
        json={
            "reason": "Merge the adjacent evidence",
            "template_id": "char_window_v1",
            "template_parameters": {"chunk_size": 500, "chunk_overlap": 50},
            "chunks": [
                {
                    "char_start": 0,
                    "char_end": len(source_text),
                    "split_reason": "manual_merge",
                }
            ],
            "operations": [{"operation": "merge", "chunk_index": 0, "next_chunk_index": 1}],
        },
    )
    assert merge.status_code == 200
    assert client.post(f"/document-versions/{version_id}/chunk-override/reindex").status_code == 200
    with factory() as session:
        merged = session.scalars(select(Chunk).where(Chunk.document_version_id == version.id)).one()
        assert merged.metadata_json["split_reason"] == "manual_merge"

    reset = client.post(
        f"/document-versions/{version_id}/chunk-override/reset",
        json={
            "reason": "Return to paragraph template",
            "template_id": "paragraph_v1",
            "template_parameters": {"chunk_size": 500, "chunk_overlap": 50},
        },
    )
    assert reset.status_code == 200
    assert reset.json()["index_status"]["reindex_required"] is True
    assert client.post(f"/document-versions/{version_id}/chunk-override/reindex").status_code == 200
    with factory() as session:
        reset_chunk = session.scalars(
            select(Chunk).where(Chunk.document_version_id == version.id)
        ).one()
        assert reset_chunk.metadata_json["chunk_template_id"] == "paragraph_v1"
        assert reset_chunk.metadata_json["split_reason"] == "paragraph_boundary"
        assert session.scalar(
            select(AuditEvent).where(AuditEvent.event_type == "chunk_override_reset")
        )
