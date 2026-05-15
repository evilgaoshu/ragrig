from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.pilot_evidence_pack import build_pack, render_markdown, write_pack

pytestmark = pytest.mark.unit


def _write_golden(path: Path) -> None:
    path.write_text(
        """
golden_question_set:
  questions:
    - query: "pilot question"
      expected_doc_uri: "guide.md"
      tags: ["hit", "pilot"]
""".strip(),
        encoding="utf-8",
    )


def test_build_pack_marks_all_requirement_groups_recorded(tmp_path) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    for name in (
        "local-pilot-smoke.json",
        "pilot-docker-smoke.json",
        "fileshare-live-smoke-record.json",
        "pilot-eval-local.json",
        "pilot-retrieval-benchmark-compare.json",
        "answer-live-smoke.json",
        "pipeline-dag-smoke.json",
        "ops-backup-summary.json",
        "ops-restore-summary.json",
        "ops-upgrade-summary.json",
    ):
        (artifacts_dir / name).write_text("{}", encoding="utf-8")
    (artifacts_dir / "ops-backup-summary.json").write_text(
        '{"operation_status": "degraded"}',
        encoding="utf-8",
    )
    (artifacts_dir / "local-pilot-smoke.json").write_text(
        '{"answer": {"grounding_status": "grounded"}, "status": {"upload": {}}}',
        encoding="utf-8",
    )
    (artifacts_dir / "pilot-docker-smoke.json").write_text(
        '{"answer_smoke": {"status": "healthy"}, "health": {"status": "healthy"}}',
        encoding="utf-8",
    )

    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()
    (corpus_root / "guide.md").write_text("retrieval ready", encoding="utf-8")
    golden_path = tmp_path / "golden.yaml"
    _write_golden(golden_path)

    pack = build_pack(
        artifacts_dir=artifacts_dir,
        corpus_root=corpus_root,
        golden_path=golden_path,
    )

    assert pack["decision_status"] == "evidence_recorded"
    assert pack["pilot_corpus"]["file_count"] == 1
    assert pack["golden_questions"][0]["query"] == "pilot question"
    assert {item["evidence_status"] for item in pack["requirements"]} == {"recorded"}
    acceptance = next(
        item for item in pack["requirements"] if item["id"] == "local_pilot_acceptance"
    )
    assert acceptance["artifact_status"]["observed_status"] == "grounded"
    dockerized = next(
        item for item in pack["requirements"] if item["id"] == "dockerized_local_pilot"
    )
    assert dockerized["artifact_status"]["observed_status"] == "healthy"
    operations = next(item for item in pack["requirements"] if item["id"] == "operations_smoke")
    assert operations["artifact_status"]["observed_status"] == "degraded"


def test_build_pack_reports_pending_when_evidence_is_missing(tmp_path) -> None:
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()
    (corpus_root / "notes.txt").write_text("notes", encoding="utf-8")
    golden_path = tmp_path / "golden.yaml"
    _write_golden(golden_path)

    pack = build_pack(
        artifacts_dir=tmp_path / "artifacts",
        corpus_root=corpus_root,
        golden_path=golden_path,
    )

    assert pack["decision_status"] == "evidence_pending"
    assert all(item["evidence_status"] == "pending" for item in pack["requirements"])


def test_write_pack_emits_json_and_markdown(tmp_path) -> None:
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()
    (corpus_root / "guide.md").write_text("guide", encoding="utf-8")
    golden_path = tmp_path / "golden.yaml"
    _write_golden(golden_path)
    pack = build_pack(
        artifacts_dir=tmp_path / "artifacts",
        corpus_root=corpus_root,
        golden_path=golden_path,
    )

    json_path = tmp_path / "out" / "pack.json"
    markdown_path = tmp_path / "out" / "pack.md"
    write_pack(pack, json_path=json_path, markdown_path=markdown_path)

    assert json.loads(json_path.read_text(encoding="utf-8"))["artifact"] == (
        "pilot-go-no-go-evidence"
    )
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "# EVI-110 Pilot Go/No-Go Evidence Pack" in markdown
    assert "pilot question" in render_markdown(pack)
