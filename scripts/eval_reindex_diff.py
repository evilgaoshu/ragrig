from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.db.models import Base
from ragrig.evaluation import run_evaluation
from ragrig.evaluation.report import build_evaluation_run_report
from ragrig.indexing.pipeline import IndexingReport, index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory

DEFAULT_GOLDEN_PATH = Path("tests/fixtures/evaluation_golden.yaml")
DEFAULT_INGEST_ROOT = Path("tests/fixtures/local_ingestion")
DEFAULT_OUTPUT = Path("docs/operations/artifacts/eval-reindex-diff.json")
DEFAULT_MARKDOWN_OUTPUT = Path("docs/operations/artifacts/eval-reindex-diff.md")
SCHEMA_VERSION = "1.0.0"

HIGHER_IS_BETTER = {
    "hit_at_1",
    "hit_at_3",
    "hit_at_5",
    "mrr",
    "citation_coverage_mean",
}
LOWER_IS_BETTER = {
    "mean_rank_of_expected",
    "zero_result_rate",
    "zero_result_count",
}
OBSERVED_ONLY = {
    "latency_ms_mean",
    "latency_ms_p50",
    "latency_ms_p95",
    "latency_ms_p99",
}


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


def run_reindex_diff_workflow(
    *,
    golden_path: Path,
    ingest_root: Path,
    knowledge_base: str,
    top_k: int,
    before_chunk_size: int,
    after_chunk_size: int,
    chunk_overlap: int,
    embedding_dimensions: int,
    store_dir: Path | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ragrig-eval-reindex-") as temp:
        temp_dir = Path(temp)
        database_path = temp_dir / "evaluation-reindex.db"
        engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
        Base.metadata.create_all(engine)
        run_store = store_dir or temp_dir / "evaluation_runs"

        with Session(engine, expire_on_commit=False) as session:
            ingest_local_directory(
                session=session,
                knowledge_base_name=knowledge_base,
                root_path=ingest_root,
            )
            before_index = index_knowledge_base(
                session=session,
                knowledge_base_name=knowledge_base,
                chunk_size=before_chunk_size,
                chunk_overlap=chunk_overlap,
                embedding_dimensions=embedding_dimensions,
            )
            before_run = run_evaluation(
                session=session,
                golden_path=golden_path,
                knowledge_base=knowledge_base,
                top_k=top_k,
                dimensions=embedding_dimensions,
                run_id="before-reindex",
                store_dir=run_store,
            )

            after_index = index_knowledge_base(
                session=session,
                knowledge_base_name=knowledge_base,
                chunk_size=after_chunk_size,
                chunk_overlap=chunk_overlap,
                embedding_dimensions=embedding_dimensions,
                force_reindex=True,
            )
            after_run = run_evaluation(
                session=session,
                golden_path=golden_path,
                knowledge_base=knowledge_base,
                top_k=top_k,
                dimensions=embedding_dimensions,
                run_id="after-reindex",
                store_dir=run_store,
            )

        engine.dispose()

        return build_reindex_diff_report(
            before_run=build_evaluation_run_report(before_run, include_items=True),
            after_run=build_evaluation_run_report(after_run, include_items=True),
            before_index=before_index,
            after_index=after_index,
            generated_at=generated_at,
            workflow={
                "knowledge_base": knowledge_base,
                "golden_path": str(golden_path),
                "ingest_root": str(ingest_root),
                "top_k": top_k,
                "before_chunk_size": before_chunk_size,
                "after_chunk_size": after_chunk_size,
                "chunk_overlap": chunk_overlap,
                "embedding_dimensions": embedding_dimensions,
                "store_dir": str(run_store),
                "database": "ephemeral_sqlite",
            },
        )


def build_reindex_diff_report(
    *,
    before_run: dict[str, Any],
    after_run: dict[str, Any],
    before_index: IndexingReport | dict[str, Any],
    after_index: IndexingReport | dict[str, Any],
    workflow: dict[str, Any],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    before_index_data = _index_report_dict(before_index)
    after_index_data = _index_report_dict(after_index)
    metric_deltas = _compare_metrics(
        before_run.get("metrics", {}),
        after_run.get("metrics", {}),
    )
    item_diffs = _compare_items(before_run.get("items", []), after_run.get("items", []))
    summary = _summarize(metric_deltas, item_diffs)
    status = _overall_status(
        before_run,
        after_run,
        before_index_data,
        after_index_data,
        summary,
    )
    report = {
        "artifact": "evaluation-reindex-diff",
        "schema_version": SCHEMA_VERSION,
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "status": status,
        "workflow": workflow,
        "before": {
            "run_id": before_run.get("id"),
            "created_at": before_run.get("created_at"),
            "status": before_run.get("status"),
            "indexing": before_index_data,
            "metrics": before_run.get("metrics", {}),
        },
        "after": {
            "run_id": after_run.get("id"),
            "created_at": after_run.get("created_at"),
            "status": after_run.get("status"),
            "indexing": after_index_data,
            "metrics": after_run.get("metrics", {}),
        },
        "metric_deltas": metric_deltas,
        "item_diffs": item_diffs,
        "summary": summary,
    }
    report["markdown_summary"] = render_markdown_summary(report)
    return report


def render_markdown_summary(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# Evaluation Reindex Diff",
        "",
        f"- Status: `{report.get('status', 'unknown')}`",
        f"- Generated at: `{report.get('generated_at', 'unknown')}`",
        f"- Before run: `{report.get('before', {}).get('run_id', 'unknown')}`",
        f"- After run: `{report.get('after', {}).get('run_id', 'unknown')}`",
        f"- Regressed items: `{summary.get('regressed_items', 0)}`",
        f"- Changed items: `{summary.get('changed_items', 0)}`",
        f"- Improved items: `{summary.get('improved_items', 0)}`",
        "",
        "## Metric Deltas",
        "",
        "| Metric | Before | After | Delta | Status |",
        "|---|---:|---:|---:|---|",
    ]
    for metric in report.get("metric_deltas", []):
        lines.append(
            "| {name} | {before} | {after} | {delta} | {status} |".format(
                name=metric["name"],
                before=_fmt(metric.get("before")),
                after=_fmt(metric.get("after")),
                delta=_fmt(metric.get("delta")),
                status=metric["status"],
            )
        )
    return "\n".join(lines) + "\n"


def _compare_metrics(
    before_metrics: dict[str, Any],
    after_metrics: dict[str, Any],
) -> list[dict[str, Any]]:
    names = sorted((HIGHER_IS_BETTER | LOWER_IS_BETTER | OBSERVED_ONLY) & set(before_metrics))
    rows: list[dict[str, Any]] = []
    for name in names:
        before = before_metrics.get(name)
        after = after_metrics.get(name)
        delta = _delta(after, before)
        rows.append(
            {
                "name": name,
                "before": before,
                "after": after,
                "delta": delta,
                "direction": _direction(name),
                "status": _metric_status(name, before, after),
            }
        )
    return rows


def _compare_items(
    before_items: list[dict[str, Any]],
    after_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    before_by_index = {item.get("question_index"): item for item in before_items}
    after_by_index = {item.get("question_index"): item for item in after_items}
    diffs: list[dict[str, Any]] = []
    for index in sorted(set(before_by_index) | set(after_by_index)):
        before = before_by_index.get(index, {})
        after = after_by_index.get(index, {})
        status = _item_status(before, after)
        before_top = (before.get("top_doc_uris") or [None])[0]
        after_top = (after.get("top_doc_uris") or [None])[0]
        diffs.append(
            {
                "question_index": index,
                "query": after.get("query") or before.get("query"),
                "status": status,
                "before": _item_summary(before),
                "after": _item_summary(after),
                "deltas": {
                    "rank_of_expected": _delta(
                        after.get("rank_of_expected"),
                        before.get("rank_of_expected"),
                    ),
                    "mrr": _delta(after.get("mrr"), before.get("mrr")),
                    "citation_coverage": _delta(
                        after.get("citation_coverage"),
                        before.get("citation_coverage"),
                    ),
                    "total_results": _delta(
                        after.get("total_results"),
                        before.get("total_results"),
                    ),
                },
                "top_doc_changed": before_top != after_top,
            }
        )
    return diffs


def _item_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "hit": item.get("hit"),
        "rank_of_expected": item.get("rank_of_expected"),
        "mrr": item.get("mrr"),
        "total_results": item.get("total_results"),
        "citation_coverage": item.get("citation_coverage"),
        "error": item.get("error"),
        "top_doc_uris": item.get("top_doc_uris", []),
    }


def _item_status(before: dict[str, Any], after: dict[str, Any]) -> str:
    if before.get("error") or after.get("error"):
        return "failure"
    before_hit = before.get("hit")
    after_hit = after.get("hit")
    if before_hit is True and after_hit is not True:
        return "regressed"
    if before_hit is not True and after_hit is True:
        return "improved"

    before_rank = before.get("rank_of_expected")
    after_rank = after.get("rank_of_expected")
    if isinstance(before_rank, int | float) and isinstance(after_rank, int | float):
        if after_rank > before_rank:
            return "regressed"
        if after_rank < before_rank:
            return "improved"

    before_mrr = before.get("mrr")
    after_mrr = after.get("mrr")
    if isinstance(before_mrr, int | float) and isinstance(after_mrr, int | float):
        if after_mrr < before_mrr:
            return "regressed"
        if after_mrr > before_mrr:
            return "improved"

    before_top = before.get("top_doc_uris") or []
    after_top = after.get("top_doc_uris") or []
    if before_top != after_top:
        return "changed"
    return "unchanged"


def _summarize(
    metric_deltas: list[dict[str, Any]],
    item_diffs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "total_items": len(item_diffs),
        "regressed_items": sum(1 for item in item_diffs if item["status"] == "regressed"),
        "improved_items": sum(1 for item in item_diffs if item["status"] == "improved"),
        "changed_items": sum(1 for item in item_diffs if item["status"] == "changed"),
        "failed_items": sum(1 for item in item_diffs if item["status"] == "failure"),
        "regressed_metrics": [
            metric["name"] for metric in metric_deltas if metric["status"] == "regressed"
        ],
        "improved_metrics": [
            metric["name"] for metric in metric_deltas if metric["status"] == "improved"
        ],
    }


def _overall_status(
    before_run: dict[str, Any],
    after_run: dict[str, Any],
    before_index: dict[str, Any],
    after_index: dict[str, Any],
    summary: dict[str, Any],
) -> str:
    if before_run.get("status") != "completed" or after_run.get("status") != "completed":
        return "failure"
    if before_index.get("failed_count", 0) or after_index.get("failed_count", 0):
        return "failure"
    if summary["failed_items"] or summary["regressed_items"] or summary["regressed_metrics"]:
        return "degraded"
    return "pass"


def _metric_status(name: str, before: Any, after: Any) -> str:
    delta = _delta(after, before)
    if delta is None:
        return "no_data"
    if name in OBSERVED_ONLY:
        return "observed"
    if delta == 0:
        return "unchanged"
    if name in HIGHER_IS_BETTER:
        return "improved" if delta > 0 else "regressed"
    if name in LOWER_IS_BETTER:
        return "improved" if delta < 0 else "regressed"
    return "observed"


def _direction(name: str) -> str:
    if name in HIGHER_IS_BETTER:
        return "higher_is_better"
    if name in LOWER_IS_BETTER:
        return "lower_is_better"
    return "observed_only"


def _delta(after: Any, before: Any) -> float | int | None:
    if before is None or after is None:
        return None
    if not isinstance(before, int | float) or not isinstance(after, int | float):
        return None
    value = after - before
    if isinstance(before, int) and isinstance(after, int):
        return value
    return round(float(value), 4)


def _index_report_dict(report: IndexingReport | dict[str, Any]) -> dict[str, Any]:
    data = asdict(report) if isinstance(report, IndexingReport) else dict(report)
    if "pipeline_run_id" in data:
        data["pipeline_run_id"] = str(data["pipeline_run_id"])
    return data


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run before/after reindex evaluation and emit a diff report."
    )
    parser.add_argument("--golden", default=str(DEFAULT_GOLDEN_PATH))
    parser.add_argument("--ingest-root", default=str(DEFAULT_INGEST_ROOT))
    parser.add_argument("--knowledge-base", default="fixture-local")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--before-chunk-size", type=int, default=500)
    parser.add_argument("--after-chunk-size", type=int, default=500)
    parser.add_argument("--chunk-overlap", type=int, default=50)
    parser.add_argument("--embedding-dimensions", type=int, default=8)
    parser.add_argument("--store-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_reindex_diff_workflow(
        golden_path=Path(args.golden),
        ingest_root=Path(args.ingest_root),
        knowledge_base=args.knowledge_base,
        top_k=args.top_k,
        before_chunk_size=args.before_chunk_size,
        after_chunk_size=args.after_chunk_size,
        chunk_overlap=args.chunk_overlap,
        embedding_dimensions=args.embedding_dimensions,
        store_dir=args.store_dir,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    indent = 2 if args.pretty else None
    payload = json.dumps(report, indent=indent, ensure_ascii=False, sort_keys=True)
    args.output.write_text(payload + "\n", encoding="utf-8")
    args.markdown_output.write_text(report["markdown_summary"], encoding="utf-8")
    print(payload)
    if report["status"] == "failure":
        return 1
    if report["status"] == "degraded":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
