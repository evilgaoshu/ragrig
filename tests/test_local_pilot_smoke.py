from __future__ import annotations

from scripts.local_pilot_smoke import run_smoke


def test_local_pilot_smoke_covers_upload_retrieval_and_answer(tmp_path) -> None:
    result = run_smoke(tmp_path / "local-pilot-smoke.db")

    assert result["health"]["status"] == "healthy"
    assert result["console"]["contains_local_pilot"] is True
    assert result["model_health"]["status"] == "healthy"
    assert result["answer_smoke"]["status"] == "healthy"
    assert result["upload"]["indexing"]["indexed_count"] >= 1
    assert result["retrieval"]["total_results"] >= 1
    assert result["answer"]["grounding_status"] == "grounded"
    assert result["answer"]["citation_count"] >= 1
    assert result["answer"]["evidence_chunk_count"] >= 1
