"""Compare graph retrieval modes against dense retrieval on golden questions."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.db.models import Base
from ragrig.evaluation import build_evaluation_run_report, run_evaluation
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.knowledge_graph import rebuild_knowledge_graph

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_GOLDEN_PATH = REPO_ROOT / "tests" / "fixtures" / "evaluation_golden_demo_graph.yaml"
DEFAULT_INGEST_ROOT = REPO_ROOT / "examples" / "local-pilot"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "operations" / "artifacts" / "graph-eval-compare.json"
DEFAULT_MARKDOWN_OUTPUT = REPO_ROOT / "docs" / "operations" / "artifacts" / "graph-eval-compare.md"
DEFAULT_MODES = ("dense", "graph", "hybrid_graph")
SCHEMA_VERSION = "1.0.0"
GRAPH_FOCUS_TAGS = ("graph", "multi-hop", "cross-doc")

COMPARE_METRICS = (
    "hit_at_1",
    "hit_at_3",
    "hit_at_5",
    "mrr",
    "citation_coverage_mean",
    "context_precision_mean",
    "context_recall_mean",
    "zero_result_rate",
    "latency_ms_mean",
    "latency_ms_p95",
)

HIGHER_IS_BETTER = {
    "hit_at_1",
    "hit_at_3",
    "hit_at_5",
    "mrr",
    "citation_coverage_mean",
    "context_precision_mean",
    "context_recall_mean",
}
LOWER_IS_BETTER = {"zero_result_rate", "latency_ms_mean", "latency_ms_p95"}


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _as_modes(raw_modes: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(raw_modes, str):
        modes = tuple(mode.strip() for mode in raw_modes.split(",") if mode.strip())
    else:
        modes = tuple(mode.strip() for mode in raw_modes if mode.strip())
    if not modes:
        raise ValueError("at least one retrieval mode is required")
    return modes


def compare_graph_retrieval_modes(
    *,
    session: Session,
    golden_path: Path,
    knowledge_base: str,
    modes: Sequence[str] = DEFAULT_MODES,
    top_k: int = 5,
    store_dir: Path | None = None,
    run_prefix: str = "graph-compare",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Run one evaluation per retrieval mode and return a comparison artifact."""
    resolved_modes = _as_modes(modes)
    results: list[dict[str, Any]] = []

    for mode in resolved_modes:
        run = run_evaluation(
            session=session,
            golden_path=golden_path,
            knowledge_base=knowledge_base,
            top_k=top_k,
            mode=mode,
            run_id=f"{run_prefix}-{mode}",
            store_dir=store_dir,
        )
        report = build_evaluation_run_report(run, include_items=True)
        results.append(
            {
                "name": mode,
                "mode": mode,
                "run_id": report["id"],
                "status": report["status"],
                "item_error_count": sum(1 for item in run.items if item.error is not None),
                "metrics": run.metrics.model_dump(mode="json"),
                "items": _compact_items(report.get("items", [])),
                "config_snapshot": run.config_snapshot,
            }
        )

    return build_graph_eval_comparison_report(
        results=results,
        workflow={
            "knowledge_base": knowledge_base,
            "golden_path": _display(golden_path),
            "top_k": top_k,
            "modes": list(resolved_modes),
            "store_dir": _display(store_dir) if store_dir is not None else None,
        },
        baseline_mode=resolved_modes[0],
        generated_at=generated_at,
    )


def run_graph_eval_compare_workflow(
    *,
    golden_path: Path = DEFAULT_GOLDEN_PATH,
    ingest_root: Path = DEFAULT_INGEST_ROOT,
    knowledge_base: str = "local-pilot-graph-compare",
    modes: Sequence[str] = DEFAULT_MODES,
    top_k: int = 5,
    store_dir: Path | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Seed a local corpus, build KG-lite, and compare retrieval modes."""
    with tempfile.TemporaryDirectory(prefix="ragrig-graph-eval-") as temp:
        temp_dir = Path(temp)
        database_path = temp_dir / "graph-eval-compare.db"
        engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
        Base.metadata.create_all(engine)
        run_store = store_dir or temp_dir / "evaluation_runs"

        try:
            with Session(engine, expire_on_commit=False) as session:
                ingest_local_directory(
                    session=session,
                    knowledge_base_name=knowledge_base,
                    root_path=ingest_root,
                    include_patterns=["*.md", "*.markdown"],
                )
                index_knowledge_base(
                    session=session,
                    knowledge_base_name=knowledge_base,
                    chunk_size=500,
                    chunk_overlap=50,
                    force_reindex=True,
                )
                graph = rebuild_knowledge_graph(session, _resolve_kb_id(session, knowledge_base))

                comparison = compare_graph_retrieval_modes(
                    session=session,
                    golden_path=golden_path,
                    knowledge_base=knowledge_base,
                    modes=modes,
                    top_k=top_k,
                    store_dir=run_store,
                    generated_at=generated_at,
                )
                comparison["workflow"]["ingest_root"] = _display(ingest_root)
                comparison["workflow"]["database"] = "ephemeral_sqlite"
                comparison["knowledge_graph"] = {
                    "status": graph.status,
                    "stats": graph.stats.model_dump(),
                }
                return comparison
        finally:
            engine.dispose()


def build_graph_eval_comparison_report(
    *,
    results: list[dict[str, Any]],
    workflow: dict[str, Any],
    baseline_mode: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    baseline = next((result for result in results if result["mode"] == baseline_mode), None)
    for result in results:
        result["delta_vs_baseline"] = _metric_deltas(
            result.get("metrics", {}),
            baseline.get("metrics", {}) if baseline is not None else {},
        )
        result["per_tag_delta_vs_baseline"] = _per_tag_metric_deltas(
            result.get("metrics", {}),
            baseline.get("metrics", {}) if baseline is not None else {},
        )

    report = {
        "artifact": "graph-retrieval-eval-compare",
        "schema_version": SCHEMA_VERSION,
        "generated_at": (generated_at.isoformat() if generated_at else _now()),
        "workflow": workflow,
        "baseline_mode": baseline_mode,
        "winner": _pick_winner(results),
        "graph_value_summary": _graph_value_summary(results, baseline_mode=baseline_mode),
        "question_diffs": _question_diffs(results, baseline_mode=baseline_mode),
        "quality_gate": _build_quality_gate(results, baseline_mode=baseline_mode),
        "results": results,
    }
    report["markdown_summary"] = render_markdown_summary(report)
    return report


def render_markdown_summary(report: dict[str, Any]) -> str:
    results = report.get("results", [])
    modes = [result["mode"] for result in results]
    lines = [
        "# Graph Retrieval Evaluation Comparison",
        "",
        f"- Generated at: `{report.get('generated_at', 'unknown')}`",
        f"- Knowledge base: `{report.get('workflow', {}).get('knowledge_base', 'unknown')}`",
        f"- Baseline mode: `{report.get('baseline_mode', 'unknown')}`",
        f"- Winner: `{report.get('winner')}`",
        f"- Quality gate: `{(report.get('quality_gate') or {}).get('status', 'unknown')}`",
        "",
        "## Metrics",
        "",
        "| Metric | " + " | ".join(modes) + " |",
        "|---|" + "|".join("---:" for _ in modes) + "|",
    ]
    for metric in COMPARE_METRICS:
        values = [result.get("metrics", {}).get(metric) for result in results]
        if all(value is None for value in values):
            continue
        best_idx = _best_index(metric, values)
        cells = []
        for idx, value in enumerate(values):
            if value is None:
                cells.append("")
                continue
            formatted = f"{value:.4f}" if isinstance(value, float) else str(value)
            cells.append(f"**{formatted}**" if idx == best_idx else formatted)
        lines.append("| " + metric + " | " + " | ".join(cells) + " |")

    graph_value = (report.get("graph_value_summary") or {}).get("modes") or []
    if graph_value:
        lines += [
            "",
            "## Graph Value Summary",
            "",
            "| Mode | Improved | Regressed | New hits | Lost hits | Graph-focus improvements |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for item in graph_value:
            lines.append(
                "| "
                + f"{item.get('mode')} | {item.get('improved_questions', 0)} | "
                + f"{item.get('regressed_questions', 0)} | "
                + f"{item.get('new_hits', 0)} | {item.get('lost_hits', 0)} | "
                + f"{item.get('graph_focus_improvements', 0)} |"
            )

    quality_gate = report.get("quality_gate") or {}
    mode_results = quality_gate.get("mode_results") or []
    if mode_results:
        lines += [
            "",
            "## Soft Quality Gate",
            "",
            "| Mode | Status | hit_at_5 Δ | zero_result_rate Δ |",
            "|---|---|---:|---:|",
        ]
        for item in mode_results:
            deltas = item.get("delta_vs_baseline") or {}
            lines.append(
                "| "
                + f"{item.get('mode')} | {item.get('status')} | "
                + f"{_format_delta(deltas.get('hit_at_5'))} | "
                + f"{_format_delta(deltas.get('zero_result_rate'))} |"
            )

    tag_rows = _focused_tag_rows(results)
    if tag_rows:
        lines += [
            "",
            "## Graph-Focused Per-Tag Delta",
            "",
            "| Mode | Tag | hit_at_5 Δ | MRR Δ | context_recall_mean Δ |",
            "|---|---|---:|---:|---:|",
        ]
        for row in tag_rows:
            lines.append(
                "| "
                + f"{row['mode']} | {row['tag']} | "
                + f"{_format_delta(row.get('hit_at_5'))} | "
                + f"{_format_delta(row.get('mrr'))} | "
                + f"{_format_delta(row.get('context_recall_mean'))} |"
            )

    question_diffs = report.get("question_diffs") or []
    if question_diffs:
        lines += [
            "",
            "## Question-Level Movement",
            "",
            "| Mode | Question | Tags | Dense rank | Mode rank | Rank Δ | Recall Δ |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
        for row in question_diffs[:12]:
            lines.append(
                "| "
                + f"{row.get('mode')} | {str(row.get('query') or '')[:80]} | "
                + f"{', '.join(row.get('tags') or [])} | "
                + f"{row.get('baseline_rank') or ''} | {row.get('mode_rank') or ''} | "
                + f"{_format_delta(row.get('rank_delta'))} | "
                + f"{_format_delta(row.get('context_recall_delta'))} |"
            )
    return "\n".join(lines) + "\n"


def _resolve_kb_id(session: Session, knowledge_base: str) -> str:
    from ragrig.repositories import get_knowledge_base_by_name

    kb = get_knowledge_base_by_name(session, knowledge_base)
    if kb is None:
        raise ValueError(f"knowledge base {knowledge_base!r} was not created")
    return str(kb.id)


def _metric_deltas(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, float | None]:
    deltas: dict[str, float | None] = {}
    for metric in COMPARE_METRICS:
        current_value = current.get(metric)
        baseline_value = baseline.get(metric)
        if isinstance(current_value, int | float) and isinstance(baseline_value, int | float):
            deltas[metric] = round(float(current_value) - float(baseline_value), 4)
        else:
            deltas[metric] = None
    return deltas


def _compact_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "question_index": item.get("question_index"),
                "query": item.get("query"),
                "tags": item.get("tags") or [],
                "hit": item.get("hit"),
                "rank_of_expected": item.get("rank_of_expected"),
                "mrr": item.get("mrr"),
                "context_recall": item.get("context_recall"),
                "citation_coverage": item.get("citation_coverage"),
                "total_results": item.get("total_results"),
                "top_doc_uri": (item.get("top_doc_uris") or [None])[0],
                "top_score": (item.get("top_scores") or [None])[0],
                "error": item.get("error"),
            }
        )
    return compact


def _question_diffs(
    results: list[dict[str, Any]],
    *,
    baseline_mode: str,
) -> list[dict[str, Any]]:
    baseline = next((result for result in results if result.get("mode") == baseline_mode), None)
    if baseline is None:
        return []
    baseline_by_index = {
        item.get("question_index"): item
        for item in baseline.get("items", [])
        if isinstance(item, dict)
    }
    rows: list[dict[str, Any]] = []
    for result in results:
        mode = str(result.get("mode") or "")
        if mode == baseline_mode or "graph" not in mode:
            continue
        for item in result.get("items", []):
            if not isinstance(item, dict):
                continue
            baseline_item = baseline_by_index.get(item.get("question_index"))
            if not isinstance(baseline_item, dict):
                continue
            baseline_rank = baseline_item.get("rank_of_expected")
            current_rank = item.get("rank_of_expected")
            rank_delta: int | None = None
            if isinstance(baseline_rank, int) and isinstance(current_rank, int):
                rank_delta = baseline_rank - current_rank
            elif baseline_rank is None and isinstance(current_rank, int):
                rank_delta = 99
            elif isinstance(baseline_rank, int) and current_rank is None:
                rank_delta = -99
            rows.append(
                {
                    "mode": mode,
                    "question_index": item.get("question_index"),
                    "query": item.get("query"),
                    "tags": item.get("tags") or [],
                    "baseline_hit": baseline_item.get("hit"),
                    "mode_hit": item.get("hit"),
                    "baseline_rank": baseline_rank,
                    "mode_rank": current_rank,
                    "rank_delta": rank_delta,
                    "baseline_top_doc_uri": baseline_item.get("top_doc_uri"),
                    "mode_top_doc_uri": item.get("top_doc_uri"),
                    "context_recall_delta": _numeric_delta(
                        item.get("context_recall"),
                        baseline_item.get("context_recall"),
                    ),
                }
            )
    rows.sort(
        key=lambda row: (
            -int(row.get("rank_delta") or 0),
            str(row.get("mode") or ""),
            int(row.get("question_index") or 0),
        )
    )
    return rows


def _numeric_delta(current: Any, baseline: Any) -> float | None:
    if isinstance(current, int | float) and isinstance(baseline, int | float):
        return round(float(current) - float(baseline), 4)
    return None


def _graph_value_summary(
    results: list[dict[str, Any]],
    *,
    baseline_mode: str,
) -> dict[str, Any]:
    diffs = _question_diffs(results, baseline_mode=baseline_mode)
    by_mode: dict[str, dict[str, Any]] = {}
    for row in diffs:
        mode = str(row.get("mode") or "")
        summary = by_mode.setdefault(
            mode,
            {
                "mode": mode,
                "improved_questions": 0,
                "regressed_questions": 0,
                "new_hits": 0,
                "lost_hits": 0,
                "graph_focus_improvements": 0,
            },
        )
        rank_delta = row.get("rank_delta")
        if isinstance(rank_delta, int | float) and rank_delta > 0:
            summary["improved_questions"] += 1
            if set(row.get("tags") or []) & set(GRAPH_FOCUS_TAGS):
                summary["graph_focus_improvements"] += 1
        elif isinstance(rank_delta, int | float) and rank_delta < 0:
            summary["regressed_questions"] += 1
        if not row.get("baseline_hit") and row.get("mode_hit"):
            summary["new_hits"] += 1
        if row.get("baseline_hit") and not row.get("mode_hit"):
            summary["lost_hits"] += 1
    return {
        "baseline_mode": baseline_mode,
        "modes": sorted(by_mode.values(), key=lambda item: item["mode"]),
    }


def _per_tag_metric_deltas(
    current_metrics: dict[str, Any],
    baseline_metrics: dict[str, Any],
) -> dict[str, dict[str, float | None]]:
    current_tags = current_metrics.get("per_tag_metrics") or {}
    baseline_tags = baseline_metrics.get("per_tag_metrics") or {}
    tag_names = sorted(set(current_tags) | set(baseline_tags))
    return {
        tag: _metric_deltas(current_tags.get(tag, {}), baseline_tags.get(tag, {}))
        for tag in tag_names
        if isinstance(current_tags.get(tag, {}), dict)
        and isinstance(baseline_tags.get(tag, {}), dict)
    }


def _build_quality_gate(
    results: list[dict[str, Any]],
    *,
    baseline_mode: str,
) -> dict[str, Any]:
    baseline = next((result for result in results if result.get("mode") == baseline_mode), None)
    if baseline is None:
        return {
            "status": "warn",
            "reason": f"baseline mode {baseline_mode!r} not found",
            "rules": [],
            "mode_results": [],
        }

    rules = [
        {
            "metric": "hit_at_5",
            "direction": "not_lower_than_baseline",
            "severity": "warn",
        },
        {
            "metric": "zero_result_rate",
            "direction": "not_higher_than_baseline",
            "severity": "warn",
        },
        {
            "metric": "graph_focus_mrr_or_context_recall",
            "direction": "positive_delta_on_any_graph_focus_tag",
            "severity": "warn",
        },
    ]
    mode_results = []
    for result in results:
        mode = str(result.get("mode") or "")
        if mode == baseline_mode or "graph" not in mode:
            continue
        deltas = result.get("delta_vs_baseline") or {}
        failures = []
        hit_delta = deltas.get("hit_at_5")
        zero_delta = deltas.get("zero_result_rate")
        if isinstance(hit_delta, int | float) and hit_delta < 0:
            failures.append("hit_at_5 below baseline")
        if isinstance(zero_delta, int | float) and zero_delta > 0:
            failures.append("zero_result_rate above baseline")
        graph_focus_per_tag_delta = {
            tag: (result.get("per_tag_delta_vs_baseline") or {}).get(tag)
            for tag in GRAPH_FOCUS_TAGS
            if tag in (result.get("per_tag_delta_vs_baseline") or {})
        }
        if graph_focus_per_tag_delta and not _has_graph_focus_uplift(graph_focus_per_tag_delta):
            failures.append("no graph-focused MRR/context_recall uplift")
        mode_results.append(
            {
                "mode": mode,
                "status": "warn" if failures else "pass",
                "failures": failures,
                "delta_vs_baseline": {
                    "hit_at_5": hit_delta,
                    "zero_result_rate": zero_delta,
                },
                "graph_focus_per_tag_delta": graph_focus_per_tag_delta,
            }
        )
    return {
        "status": "warn" if any(item["status"] == "warn" for item in mode_results) else "pass",
        "rules": rules,
        "mode_results": mode_results,
    }


def _has_graph_focus_uplift(per_tag_delta: dict[str, Any]) -> bool:
    for values in per_tag_delta.values():
        if not isinstance(values, dict):
            continue
        for metric in ("mrr", "context_recall_mean"):
            delta = values.get(metric)
            if isinstance(delta, int | float) and delta > 0:
                return True
    return False


def _focused_tag_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in results:
        mode = result.get("mode")
        if mode == "dense":
            continue
        per_tag = result.get("per_tag_delta_vs_baseline") or {}
        for tag in GRAPH_FOCUS_TAGS:
            values = per_tag.get(tag)
            if not isinstance(values, dict):
                continue
            rows.append(
                {
                    "mode": mode,
                    "tag": tag,
                    "hit_at_5": values.get("hit_at_5"),
                    "mrr": values.get("mrr"),
                    "context_recall_mean": values.get("context_recall_mean"),
                }
            )
    return rows


def _format_delta(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, int | float):
        return f"{value:+.4f}"
    return str(value)


def _best_index(metric: str, values: list[Any]) -> int | None:
    numeric = [(idx, value) for idx, value in enumerate(values) if isinstance(value, int | float)]
    if not numeric:
        return None
    if metric in HIGHER_IS_BETTER:
        return max(numeric, key=lambda item: item[1])[0]
    if metric in LOWER_IS_BETTER:
        return min(numeric, key=lambda item: item[1])[0]
    return None


def _pick_winner(results: list[dict[str, Any]]) -> str | None:
    if not results:
        return None

    def score(result: dict[str, Any]) -> tuple[float, float, float, float]:
        metrics = result.get("metrics", {})
        return (
            float(metrics.get("hit_at_5") or 0.0),
            float(metrics.get("mrr") or 0.0),
            float(metrics.get("context_recall_mean") or 0.0),
            -float(metrics.get("zero_result_rate") or 0.0),
        )

    return max(results, key=score)["mode"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare dense and graph retrieval modes.")
    parser.add_argument("--golden-path", type=Path, default=DEFAULT_GOLDEN_PATH)
    parser.add_argument("--ingest-root", type=Path, default=DEFAULT_INGEST_ROOT)
    parser.add_argument("--knowledge-base", default="local-pilot-graph-compare")
    parser.add_argument("--modes", default=",".join(DEFAULT_MODES))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--store-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = run_graph_eval_compare_workflow(
        golden_path=args.golden_path,
        ingest_root=args.ingest_root,
        knowledge_base=args.knowledge_base,
        modes=_as_modes(args.modes),
        top_k=args.top_k,
        store_dir=args.store_dir,
    )

    indent = 2 if args.pretty else None
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=indent, sort_keys=True),
            encoding="utf-8",
        )
    if args.markdown_output is not None:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(report["markdown_summary"], encoding="utf-8")

    print(json.dumps(report, indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
