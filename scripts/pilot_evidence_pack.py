"""Build the EVI-110 pilot go/no-go evidence manifest and Markdown record."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).parent.parent
ARTIFACTS_DIR = REPO_ROOT / "docs" / "operations" / "artifacts"
RECORD_PATH = REPO_ROOT / "docs" / "operations" / "records" / "EVI-110-pilot-go-no-go-evidence.md"
JSON_PATH = ARTIFACTS_DIR / "pilot-go-no-go-evidence.json"
GOLDEN_PATH = REPO_ROOT / "tests" / "fixtures" / "evaluation_golden.yaml"
LIVE_CORPUS_ROOT = REPO_ROOT / "tests" / "fixtures" / "fileshare_live"

EVIDENCE_REQUIREMENTS = (
    {
        "id": "real_source_connector",
        "title": "Equivalent real-source connector path",
        "command": "make test-live-fileshare",
        "artifact": "fileshare-live-smoke-record.json",
        "go_rule": "Live SMB/WebDAV/SFTP fileshare seed and smoke record reports passed.",
    },
    {
        "id": "retrieval_answer_baseline",
        "title": "Retrieval and answer quality baseline",
        "command": (
            "uv run python -m scripts.eval_local "
            "--ephemeral-sqlite "
            "--output docs/operations/artifacts/pilot-eval-local.json && "
            "uv run python -m scripts.retrieval_benchmark_compare --pretty "
            "--latency-threshold-pct 500 "
            "--output docs/operations/artifacts/pilot-retrieval-benchmark-compare.json"
        ),
        "artifact": "pilot-eval-local.json",
        "supporting_artifacts": ["pilot-retrieval-benchmark-compare.json"],
        "go_rule": "Golden retrieval metrics are recorded and benchmark comparison does not fail.",
    },
    {
        "id": "citation_refusal_diagnostics",
        "title": "Citation, refusal, and degraded answer diagnostics",
        "command": "make answer-live-smoke",
        "artifact": "answer-live-smoke.json",
        "go_rule": (
            "Answer diagnostics artifact records provider health, degraded, or skip explicitly."
        ),
    },
    {
        "id": "inspect_retry_audit",
        "title": "Failure inspect, retry, and audit trail",
        "command": "make pipeline-dag-smoke",
        "artifact": "pipeline-dag-smoke.json",
        "go_rule": (
            "Pipeline DAG smoke captures per-step state while regression tests protect retry/audit."
        ),
    },
    {
        "id": "operations_smoke",
        "title": "Backup, restore, and upgrade summary",
        "command": ("make ops-backup-smoke && make ops-restore-smoke && make ops-upgrade-smoke"),
        "artifact": "ops-backup-summary.json",
        "supporting_artifacts": ["ops-restore-summary.json", "ops-upgrade-summary.json"],
        "go_rule": (
            "Operations artifacts expose success, degraded, or explicit failure, never silent pass."
        ),
    },
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_corpus_manifest(corpus_root: Path = LIVE_CORPUS_ROOT) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for path in sorted(corpus_root.rglob("*")):
        if path.is_file():
            files.append(
                {
                    "path": _display(path),
                    "bytes": path.stat().st_size,
                    "sha256": _sha256(path),
                }
            )
    return files


def load_golden_questions(golden_path: Path = GOLDEN_PATH) -> list[dict[str, Any]]:
    data = yaml.safe_load(golden_path.read_text(encoding="utf-8"))
    questions = data["golden_question_set"]["questions"]
    return [
        {
            "query": row["query"],
            "tags": row.get("tags", []),
            "expected_doc_uri": row.get("expected_doc_uri"),
        }
        for row in questions
    ]


def _artifact_status(artifacts_dir: Path, artifact_name: str) -> dict[str, Any]:
    path = artifacts_dir / artifact_name
    status: dict[str, Any] = {
        "path": _display(path),
        "present": path.exists(),
    }
    if path.exists():
        status["bytes"] = path.stat().st_size
        status["sha256"] = _sha256(path)
        status["observed_status"] = _observed_status(path)
    return status


def _observed_status(path: Path) -> str:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unreadable"
    if not isinstance(data, dict):
        return "unknown"
    meta = data.get("meta")
    candidates = [
        meta.get("result") if isinstance(meta, dict) else None,
        data.get("operation_status"),
        data.get("overall_status"),
        data.get("status"),
        data.get("resume_status"),
    ]
    return next((str(value) for value in candidates if value is not None), "unknown")


def build_pack(
    *,
    artifacts_dir: Path = ARTIFACTS_DIR,
    corpus_root: Path = LIVE_CORPUS_ROOT,
    golden_path: Path = GOLDEN_PATH,
) -> dict[str, Any]:
    requirements: list[dict[str, Any]] = []
    for requirement in EVIDENCE_REQUIREMENTS:
        primary = _artifact_status(artifacts_dir, requirement["artifact"])
        supporting = [
            _artifact_status(artifacts_dir, name)
            for name in requirement.get("supporting_artifacts", [])
        ]
        complete = primary["present"] and all(item["present"] for item in supporting)
        requirements.append(
            {
                **requirement,
                "artifact_status": primary,
                "supporting_artifact_status": supporting,
                "evidence_status": "recorded" if complete else "pending",
            }
        )

    recorded = sum(item["evidence_status"] == "recorded" for item in requirements)
    return {
        "artifact": "pilot-go-no-go-evidence",
        "version": "1.0.0",
        "generated_at": _now(),
        "decision_status": "evidence_recorded"
        if recorded == len(requirements)
        else "evidence_pending",
        "source_equivalence": {
            "selected_source": "fileshare-live SMB/WebDAV/SFTP",
            "rationale": (
                "The pilot uses a live networked document connector with seeded fixtures "
                "as the explicit real-source equivalent when Google Workspace credentials "
                "are not part of reproducible repo CI."
            ),
        },
        "pilot_corpus": {
            "root": _display(corpus_root),
            "file_count": len(build_corpus_manifest(corpus_root)),
            "files": build_corpus_manifest(corpus_root),
        },
        "golden_questions": load_golden_questions(golden_path),
        "requirements": requirements,
        "go_no_go": {
            "go_when": [
                "All five evidence groups are recorded from the documented commands.",
                "ACL regression and citation/refusal checks remain covered by make test.",
                (
                    "Required repository gates make lint, make test, make coverage, "
                    "and make web-check pass."
                ),
            ],
            "no_go_when": [
                "Live connector evidence is blocked without an accepted equivalent-source record.",
                "Retrieval comparison reports failure or artifacts are missing.",
                (
                    "Restore/upgrade diagnostics hide failure instead of reporting "
                    "success/degraded/failure."
                ),
            ],
        },
    }


def render_markdown(pack: dict[str, Any]) -> str:
    lines = [
        "# EVI-110 Pilot Go/No-Go Evidence Pack",
        "",
        f"Generated: `{pack['generated_at']}`",
        f"Decision evidence status: `{pack['decision_status']}`",
        "",
        "## Pilot Source And Corpus",
        "",
        f"- Source path: `{pack['source_equivalence']['selected_source']}`",
        f"- Rationale: {pack['source_equivalence']['rationale']}",
        f"- Fixed corpus root: `{pack['pilot_corpus']['root']}`",
        f"- Fixed corpus file count: `{pack['pilot_corpus']['file_count']}`",
        "",
        "| Corpus file | Bytes | SHA-256 |",
        "| --- | ---: | --- |",
    ]
    for item in pack["pilot_corpus"]["files"]:
        lines.append(f"| `{item['path']}` | {item['bytes']} | `{item['sha256']}` |")

    lines.extend(
        [
            "",
            "## Golden Questions",
            "",
            "| Query | Tags | Expected document |",
            "| --- | --- | --- |",
        ]
    )
    for question in pack["golden_questions"]:
        tags = ", ".join(question["tags"]) or "-"
        expected = question["expected_doc_uri"] or "-"
        lines.append(f"| `{question['query']}` | {tags} | `{expected}` |")

    lines.extend(
        [
            "",
            "## Evidence Commands",
            "",
            "| Evidence | Command | Primary artifact | Evidence | Observed outcome |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for item in pack["requirements"]:
        artifact_path = item["artifact_status"]["path"]
        observed = item["artifact_status"].get("observed_status", "missing")
        lines.append(
            f"| {item['title']} | `{item['command']}` | `{artifact_path}` | "
            f"`{item['evidence_status']}` | `{observed}` |"
        )
        for supporting in item["supporting_artifact_status"]:
            supporting_observed = supporting.get("observed_status", "missing")
            lines.append(
                f"| Supporting artifact | - | `{supporting['path']}` | - | "
                f"`{supporting_observed}` |"
            )

    lines.extend(["", "## Go / No-Go Rules", "", "Go when:"])
    lines.extend(f"- {rule}" for rule in pack["go_no_go"]["go_when"])
    lines.extend(["", "No-go when:"])
    lines.extend(f"- {rule}" for rule in pack["go_no_go"]["no_go_when"])
    lines.extend(
        [
            "",
            "## Residual Risk",
            "",
            "- Google Workspace remains outside the reproducible repo-local pilot route; "
            "the live fileshare connector is the declared equivalent real-source evidence.",
            "- Answer provider smoke may intentionally report degraded or skip where a local "
            "LLM is unavailable; that remains decision evidence, not an unreported success.",
            "- Live connector smoke requires Docker and optional fileshare SDKs, so blocked "
            "preflight output must be retained as explicit evidence when the lab lacks them.",
            "",
        ]
    )
    return "\n".join(lines)


def write_pack(pack: dict[str, Any], *, json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(pack, indent=2, ensure_ascii=True), encoding="utf-8")
    markdown_path.write_text(render_markdown(pack), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", type=Path, default=ARTIFACTS_DIR)
    parser.add_argument("--corpus-root", type=Path, default=LIVE_CORPUS_ROOT)
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH)
    parser.add_argument("--json-output", type=Path, default=JSON_PATH)
    parser.add_argument("--markdown-output", type=Path, default=RECORD_PATH)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    pack = build_pack(
        artifacts_dir=args.artifacts_dir,
        corpus_root=args.corpus_root,
        golden_path=args.golden,
    )
    write_pack(pack, json_path=args.json_output, markdown_path=args.markdown_output)
    if args.pretty:
        print(json.dumps(pack, indent=2, ensure_ascii=True))
    print(f"JSON evidence: {_display(args.json_output)}")
    print(f"Markdown record: {_display(args.markdown_output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
