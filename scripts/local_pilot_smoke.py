from __future__ import annotations

import argparse
import io
import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from ragrig.db.models import Base
from ragrig.main import create_app


class LocalPilotSmokeError(RuntimeError):
    pass


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


def _create_file_session_factory(database_path: Path) -> tuple[Callable[[], Session], Any]:
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path}",
        future=True,
        poolclass=NullPool,
    )
    Base.metadata.create_all(engine)

    def _factory() -> Session:
        return Session(engine, expire_on_commit=False)

    return _factory, engine


def _json_response(client_response, *, expected_status: int = 200) -> dict[str, Any]:
    if client_response.status_code != expected_status:
        raise LocalPilotSmokeError(
            f"{client_response.request.method} {client_response.request.url.path} "
            f"returned {client_response.status_code}: {client_response.text}"
        )
    return client_response.json()


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise LocalPilotSmokeError(message)


def run_smoke(database_path: Path) -> dict[str, Any]:
    session_factory, engine = _create_file_session_factory(database_path)
    try:
        client = TestClient(
            create_app(check_database=lambda: None, session_factory=session_factory)
        )

        health = _json_response(client.get("/health"))
        console = client.get("/console")
        if console.status_code != 200 or "Local Pilot" not in console.text:
            raise LocalPilotSmokeError("console did not render the Local Pilot surface")

        status = _json_response(client.get("/local-pilot/status"))
        upload_extensions = set(status["upload"]["extensions"])
        _assert(
            {".md", ".txt", ".pdf", ".docx"}.issubset(upload_extensions),
            "local pilot status is missing required upload extensions",
        )

        model_health = _json_response(
            client.post(
                "/local-pilot/model-health",
                json={
                    "provider": "deterministic-local",
                    "model": "hash-8d",
                    "config": {},
                },
            )
        )
        _assert(model_health["status"] == "healthy", f"model health failed: {model_health}")

        answer_smoke = _json_response(
            client.post(
                "/local-pilot/answer-smoke",
                json={"provider": "deterministic-local"},
            )
        )
        _assert(
            answer_smoke["status"] == "healthy",
            f"deterministic answer smoke failed: {answer_smoke}",
        )

        kb = _json_response(
            client.post("/knowledge-bases", json={"name": "local-pilot-smoke"}),
            expected_status=201,
        )

        fixture_text = (
            "# Local Pilot Smoke Guide\n\n"
            "RAGRig Local Pilot proves a small team can upload documents, index chunks, "
            "retrieve evidence, and generate grounded answers with citations in one local flow.\n"
        )
        upload = _json_response(
            client.post(
                "/knowledge-bases/local-pilot-smoke/upload",
                files={
                    "files": (
                        "local-pilot-smoke.md",
                        io.BytesIO(fixture_text.encode("utf-8")),
                        "text/markdown",
                    )
                },
            ),
            expected_status=202,
        )
        indexing = upload.get("indexing") or {}
        _assert(indexing.get("indexed_count", 0) >= 1, f"upload did not index: {upload}")
        _assert(indexing.get("chunk_count", 0) >= 1, f"upload created no chunks: {upload}")
        _assert(indexing.get("failed_count", 0) == 0, f"indexing failed: {upload}")

        query = "What does the Local Pilot prove about citations?"
        search = _json_response(
            client.post(
                "/retrieval/search",
                json={
                    "knowledge_base": "local-pilot-smoke",
                    "query": query,
                    "top_k": 3,
                },
            )
        )
        _assert(search["total_results"] >= 1, f"retrieval returned no evidence: {search}")
        _assert(
            any("citations" in result["text"].lower() for result in search["results"]),
            f"retrieval evidence did not include the uploaded pilot content: {search}",
        )

        answer = _json_response(
            client.post(
                "/retrieval/answer",
                json={
                    "knowledge_base": "local-pilot-smoke",
                    "query": query,
                    "top_k": 3,
                    "provider": "deterministic-local",
                },
            )
        )
        _assert(answer["grounding_status"] == "grounded", f"answer was not grounded: {answer}")
        _assert(answer["citations"], f"answer returned no citations: {answer}")
        _assert(answer["evidence_chunks"], f"answer returned no evidence chunks: {answer}")

        return {
            "health": health,
            "console": {"contains_local_pilot": True},
            "status": status,
            "model_health": model_health,
            "answer_smoke": answer_smoke,
            "knowledge_base": kb,
            "upload": upload,
            "retrieval": {
                "query": query,
                "total_results": search["total_results"],
                "top_document_uri": search["results"][0]["document_uri"],
            },
            "answer": {
                "grounding_status": answer["grounding_status"],
                "citation_count": len(answer["citations"]),
                "evidence_chunk_count": len(answer["evidence_chunks"]),
            },
        }
    finally:
        engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the secret-free Local Pilot acceptance smoke."
    )
    parser.add_argument(
        "--database-path",
        type=Path,
        default=None,
        help="Optional SQLite database path. Defaults to a temporary file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional JSON artifact output path.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.database_path is not None:
        result = run_smoke(args.database_path)
    else:
        with tempfile.TemporaryDirectory(prefix="ragrig-local-pilot-smoke-") as temp_dir:
            result = run_smoke(Path(temp_dir) / "local-pilot-smoke.db")

    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
