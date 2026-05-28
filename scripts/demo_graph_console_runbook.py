"""One-command external demo runbook for the GraphRAG Console loop."""

from __future__ import annotations

import argparse
import json
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ragrig.config import Settings
from ragrig.main import create_app
from ragrig.repositories import get_knowledge_base_by_name
from scripts.demo_rc_gate import (
    DEFAULT_GOLDEN_PATH,
    DEFAULT_INGEST_ROOT,
    DEFAULT_KNOWLEDGE_BASE,
    run_demo_rc_gate,
)
from scripts.demo_rc_gate import (
    DEFAULT_MARKDOWN_OUTPUT as DEFAULT_DEMO_RC_MARKDOWN,
)
from scripts.demo_rc_gate import (
    DEFAULT_OUTPUT as DEFAULT_DEMO_RC_OUTPUT,
)

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_DATABASE = REPO_ROOT / "docs" / "operations" / "artifacts" / "demo-graph-console.db"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "operations" / "artifacts" / "demo-graph-console-runbook.json"
DEFAULT_MARKDOWN_OUTPUT = (
    REPO_ROOT / "docs" / "operations" / "artifacts" / "demo-graph-console-runbook.md"
)
DEFAULT_RETRIEVAL_PREFERENCES = {
    "mode": "hybrid_graph",
    "lexical_weight": 0.3,
    "vector_weight": 0.7,
    "candidate_k": 20,
    "reranker_provider": None,
    "reranker_model": None,
    "graph_weight": 0.35,
    "graph_depth": 1,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _sqlite_url(database_path: Path) -> str:
    return f"sqlite+pysqlite:///{database_path.resolve()}"


def _console_url(host: str, port: int) -> str:
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{display_host}:{port}/"


def _persist_retrieval_preferences(
    *,
    database_path: Path,
    knowledge_base: str,
    preferences: dict[str, Any],
) -> None:
    engine = create_engine(_sqlite_url(database_path), future=True)
    try:
        with Session(engine, expire_on_commit=False) as session:
            kb = get_knowledge_base_by_name(session, knowledge_base)
            if kb is None:
                raise ValueError(f"knowledge base {knowledge_base!r} was not created")
            metadata = dict(kb.metadata_json or {})
            metadata["retrieval_preferences"] = dict(preferences)
            kb.metadata_json = metadata
            session.commit()
    finally:
        engine.dispose()


def render_markdown(report: dict[str, Any]) -> str:
    console = report.get("console") or {}
    comparison = report.get("comparison") or {}
    lines = [
        "# Demo Graph Console Runbook",
        "",
        f"- Status: `{report.get('status', 'unknown')}`",
        f"- Generated at: `{report.get('generated_at', 'unknown')}`",
        f"- Console URL: `{console.get('url', 'unknown')}`",
        f"- Knowledge Map URL: `{console.get('knowledge_map_url', 'unknown')}`",
        f"- Retrieval Lab URL: `{console.get('retrieval_lab_url', 'unknown')}`",
        f"- Knowledge base: `{console.get('knowledge_base', 'unknown')}`",
        f"- Database: `{console.get('database_path', 'unknown')}`",
        "",
        "## One Command",
        "",
        "```bash",
        "make demo-graph-console",
        "```",
        "",
        "Live talk track: `docs/operations/external-demo-script.md`.",
        "",
        "## What This Runs",
        "",
        "- Loads `examples/local-pilot/*.md` into a disposable SQLite demo database.",
        "- Builds KG-lite entity/relation rows.",
        "- Runs dense/graph/hybrid_graph eval comparison.",
        "- Saves `hybrid_graph` as the Console mode preference.",
        "- Starts the React Console with auth disabled against the demo database.",
        "",
        "## External Demo Checklist",
        "",
        "| Moment | Pass Signal |",
        "|---|---|",
        "| Preflight | `make demo-graph-console-runbook` returns `pass`. |",
        "| Browser smoke | `make demo-graph-console-smoke` records graph, retrieval, "
        "compare, and feedback evidence. |",
        "| Opening | Knowledge Map shows entities, relations, claims, evidence, "
        "and feedback controls. |",
        "| Core loop | Retrieval Lab shows `hybrid_graph`, compares `dense`, `graph`, "
        "and `hybrid_graph`, then shows graph context. |",
        "| Feedback | Marking a bad relation increments feedback and the next graph trace "
        "reports suppressed relations. |",
        "| Cleanup | `make demo-graph-console-cleanup CONFIRM_DELETE=1` removes local "
        "demo artifacts after rehearsal. |",
        "",
        "## Checks",
        "",
        "| Check | Status |",
        "|---|---|",
    ]
    for check in report.get("checks", []):
        lines.append(f"| {check.get('id')} | {check.get('status')} |")
    lines += [
        "",
        "## Retrieval Comparison",
        "",
        f"- Baseline mode: `{comparison.get('baseline_mode', 'unknown')}`",
        f"- Winner: `{comparison.get('winner', 'unknown')}`",
        f"- Quality gate: `{(comparison.get('quality_gate') or {}).get('status', 'unknown')}`",
    ]
    return "\n".join(lines) + "\n"


def run_demo_graph_console_runbook(
    *,
    database_path: Path,
    ingest_root: Path = DEFAULT_INGEST_ROOT,
    golden_path: Path = DEFAULT_GOLDEN_PATH,
    knowledge_base: str = DEFAULT_KNOWLEDGE_BASE,
    host: str = "127.0.0.1",
    port: int = 8000,
    reset_database: bool = True,
    demo_rc_output: Path = DEFAULT_DEMO_RC_OUTPUT,
    demo_rc_markdown_output: Path = DEFAULT_DEMO_RC_MARKDOWN,
) -> dict[str, Any]:
    if reset_database and database_path.exists():
        database_path.unlink()
    database_path.parent.mkdir(parents=True, exist_ok=True)

    gate = run_demo_rc_gate(
        database_path=database_path,
        ingest_root=ingest_root,
        golden_path=golden_path,
        knowledge_base=knowledge_base,
    )
    demo_rc_output.parent.mkdir(parents=True, exist_ok=True)
    demo_rc_output.write_text(
        json.dumps(gate, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    demo_rc_markdown_output.parent.mkdir(parents=True, exist_ok=True)
    demo_rc_markdown_output.write_text(gate["markdown_summary"], encoding="utf-8")
    _persist_retrieval_preferences(
        database_path=database_path,
        knowledge_base=knowledge_base,
        preferences=DEFAULT_RETRIEVAL_PREFERENCES,
    )
    report = {
        "artifact": "demo-graph-console-runbook",
        "schema_version": "1.0.0",
        "generated_at": _now(),
        "status": gate["status"],
        "console": {
            "url": _console_url(host, port),
            "knowledge_map_url": f"{_console_url(host, port)}knowledge-map",
            "retrieval_lab_url": f"{_console_url(host, port)}retrieval-lab",
            "knowledge_base": knowledge_base,
            "database_path": _display(database_path),
            "database_url": _sqlite_url(database_path),
            "retrieval_preferences": DEFAULT_RETRIEVAL_PREFERENCES,
        },
        "workflow": {
            "ingest_root": _display(ingest_root),
            "golden_path": _display(golden_path),
            "demo_rc_gate_output": _display(demo_rc_output),
            "demo_rc_gate_markdown": _display(demo_rc_markdown_output),
        },
        "checks": gate["checks"],
        "comparison": gate["comparison"],
    }
    report["markdown_summary"] = render_markdown(report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare and optionally serve the GraphRAG demo Console."
    )
    parser.add_argument("--database-path", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--ingest-root", type=Path, default=DEFAULT_INGEST_ROOT)
    parser.add_argument("--golden-path", type=Path, default=DEFAULT_GOLDEN_PATH)
    parser.add_argument("--knowledge-base", default=DEFAULT_KNOWLEDGE_BASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--demo-rc-output", type=Path, default=DEFAULT_DEMO_RC_OUTPUT)
    parser.add_argument("--demo-rc-markdown-output", type=Path, default=DEFAULT_DEMO_RC_MARKDOWN)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--keep-database", action="store_true")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_demo_graph_console_runbook(
        database_path=args.database_path,
        ingest_root=args.ingest_root,
        golden_path=args.golden_path,
        knowledge_base=args.knowledge_base,
        host=args.host,
        port=args.port,
        reset_database=not args.keep_database,
        demo_rc_output=args.demo_rc_output,
        demo_rc_markdown_output=args.demo_rc_markdown_output,
    )
    indent = 2 if args.pretty else None
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=indent, sort_keys=True), encoding="utf-8")
    if args.markdown_output is not None:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(report["markdown_summary"], encoding="utf-8")

    print(json.dumps(report, indent=indent, sort_keys=True))
    if report["status"] != "pass":
        return 1
    if not args.serve:
        return 0

    url = report["console"]["url"]
    if args.open_browser:
        webbrowser.open(url)
    settings = Settings(
        database_url=_sqlite_url(args.database_path),
        app_host=args.host,
        app_port=args.port,
        ragrig_auth_enabled=False,
        ragrig_metrics_enabled=False,
    )
    print(f"Serving demo Console at {url}")
    app = create_app(check_database=lambda: None, settings=settings)
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
