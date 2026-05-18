"""A/B configuration comparison for evaluation runs.

Runs the RAGRig evaluation pipeline under multiple retrieval configurations
(chunk size, overlap, embedding dimensions) and emits a comparison table so
you can pick the best set of hyper-parameters without manual bisection.

Usage:
    uv run python -m scripts.eval_config_compare --pretty
    uv run python -m scripts.eval_config_compare \\
        --configs configs/eval_configs.json \\
        --output docs/operations/artifacts/eval-config-compare.json \\
        --markdown-output docs/operations/artifacts/eval-config-compare.md

Built-in default configs (if --configs is not supplied):
  - small:   chunk_size=200, overlap=20,  dims=8
  - medium:  chunk_size=500, overlap=50,  dims=8
  - large:   chunk_size=1000, overlap=100, dims=8

JSON config file format:
    [
      {"name": "my-config", "chunk_size": 400, "chunk_overlap": 40,
       "embedding_dimensions": 16, "top_k": 5}
    ]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
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
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory

DEFAULT_GOLDEN_PATH = Path("tests/fixtures/evaluation_golden.yaml")
DEFAULT_INGEST_ROOT = Path("tests/fixtures/local_ingestion")
DEFAULT_OUTPUT = Path("docs/operations/artifacts/eval-config-compare.json")
DEFAULT_MARKDOWN_OUTPUT = Path("docs/operations/artifacts/eval-config-compare.md")
SCHEMA_VERSION = "1.0.0"

DEFAULT_CONFIGS: list[dict[str, Any]] = [
    {"name": "small", "chunk_size": 200, "chunk_overlap": 20, "embedding_dimensions": 8},
    {"name": "medium", "chunk_size": 500, "chunk_overlap": 50, "embedding_dimensions": 8},
    {"name": "large", "chunk_size": 1000, "chunk_overlap": 100, "embedding_dimensions": 8},
]

COMPARE_METRICS = [
    "hit_at_1",
    "hit_at_3",
    "hit_at_5",
    "mrr",
    "citation_coverage_mean",
    "context_precision_mean",
    "context_recall_mean",
    "answer_correctness_mean",
    "answer_relevance_mean",
    "mean_rank_of_expected",
    "zero_result_rate",
    "latency_ms_mean",
    "latency_ms_p95",
]

HIGHER_IS_BETTER = {
    "hit_at_1",
    "hit_at_3",
    "hit_at_5",
    "mrr",
    "citation_coverage_mean",
    "context_precision_mean",
    "context_recall_mean",
    "answer_correctness_mean",
    "answer_relevance_mean",
}
LOWER_IS_BETTER = {
    "mean_rank_of_expected",
    "zero_result_rate",
    "zero_result_count",
    "latency_ms_mean",
    "latency_ms_p95",
}


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


def run_config_compare_workflow(
    *,
    golden_path: Path,
    ingest_root: Path,
    knowledge_base: str,
    configs: list[dict[str, Any]],
    store_dir: Path | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ragrig-eval-compare-") as temp:
        temp_dir = Path(temp)
        database_path = temp_dir / "evaluation-compare.db"
        engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
        Base.metadata.create_all(engine)
        run_store = store_dir or temp_dir / "evaluation_runs"

        results: list[dict[str, Any]] = []

        with Session(engine, expire_on_commit=False) as session:
            ingest_local_directory(
                session=session,
                knowledge_base_name=knowledge_base,
                root_path=ingest_root,
            )

            for cfg in configs:
                name = cfg["name"]
                chunk_size = cfg.get("chunk_size", 500)
                chunk_overlap = cfg.get("chunk_overlap", 50)
                embedding_dimensions = cfg.get("embedding_dimensions", 8)
                top_k = cfg.get("top_k", 5)

                index_knowledge_base(
                    session=session,
                    knowledge_base_name=knowledge_base,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    embedding_dimensions=embedding_dimensions,
                    force_reindex=True,
                )
                eval_run = run_evaluation(
                    session=session,
                    golden_path=golden_path,
                    knowledge_base=knowledge_base,
                    top_k=top_k,
                    dimensions=embedding_dimensions,
                    run_id=f"compare-{name}",
                    store_dir=run_store,
                )
                report = build_evaluation_run_report(eval_run, include_items=False)
                results.append(
                    {
                        "name": name,
                        "config": {
                            "chunk_size": chunk_size,
                            "chunk_overlap": chunk_overlap,
                            "embedding_dimensions": embedding_dimensions,
                            "top_k": top_k,
                        },
                        "run_id": report.get("id"),
                        "status": report.get("status"),
                        "metrics": report.get("metrics", {}),
                    }
                )

        engine.dispose()

        comparison = build_comparison_report(
            results=results,
            generated_at=generated_at,
            workflow={
                "knowledge_base": knowledge_base,
                "golden_path": str(golden_path),
                "ingest_root": str(ingest_root),
                "store_dir": str(run_store),
                "database": "ephemeral_sqlite",
                "config_count": len(configs),
            },
        )
        return comparison


def build_comparison_report(
    *,
    results: list[dict[str, Any]],
    workflow: dict[str, Any],
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    winner = _pick_winner(results)
    report = {
        "artifact": "evaluation-config-compare",
        "schema_version": SCHEMA_VERSION,
        "generated_at": (generated_at or datetime.now(timezone.utc)).isoformat(),
        "workflow": workflow,
        "winner": winner,
        "results": results,
    }
    report["markdown_summary"] = render_markdown_summary(report)
    return report


def render_markdown_summary(report: dict[str, Any]) -> str:
    results = report.get("results", [])
    winner = report.get("winner")
    lines = [
        "# Evaluation Config Comparison",
        "",
        f"- Generated at: `{report.get('generated_at', 'unknown')}`",
        f"- Configs compared: `{len(results)}`",
        f"- Winner: `{winner}`",
        "",
        "## Retrieval Metrics",
        "",
    ]

    present_metrics = [
        m for m in COMPARE_METRICS if any(r.get("metrics", {}).get(m) is not None for r in results)
    ]
    config_names = [r["name"] for r in results]

    header = "| Metric | " + " | ".join(config_names) + " |"
    sep = "|---|" + "|".join("---:" for _ in config_names) + "|"
    lines += [header, sep]

    for metric in present_metrics:
        values = [r.get("metrics", {}).get(metric) for r in results]
        best_idx = _best_index(metric, values)
        cells = []
        for i, v in enumerate(values):
            if v is None:
                cells.append("")
            else:
                formatted = f"{v:.4f}" if isinstance(v, float) else str(v)
                cells.append(f"**{formatted}**" if i == best_idx else formatted)
        lines.append("| " + metric + " | " + " | ".join(cells) + " |")

    per_tag_present = any(r.get("metrics", {}).get("per_tag_metrics") for r in results)
    if per_tag_present:
        all_tags = sorted(
            {tag for r in results for tag in (r.get("metrics", {}).get("per_tag_metrics") or {})}
        )
        lines += [
            "",
            "## Per-Tag Hit@5",
            "",
            "| Tag | " + " | ".join(config_names) + " |",
            "|---|" + "|".join("---:" for _ in config_names) + "|",
        ]
        for tag in all_tags:
            cells = []
            tag_values = []
            for r in results:
                v = (r.get("metrics", {}).get("per_tag_metrics") or {}).get(tag, {}).get("hit_at_5")
                tag_values.append(v)
            best_idx = _best_index("hit_at_5", tag_values)
            for i, v in enumerate(tag_values):
                if v is None:
                    cells.append("")
                else:
                    formatted = f"{v:.3f}"
                    cells.append(f"**{formatted}**" if i == best_idx else formatted)
            lines.append("| " + tag + " | " + " | ".join(cells) + " |")

    return "\n".join(lines) + "\n"


def _best_index(metric: str, values: list[Any]) -> int | None:
    numeric = [(i, v) for i, v in enumerate(values) if isinstance(v, int | float)]
    if not numeric:
        return None
    if metric in HIGHER_IS_BETTER:
        return max(numeric, key=lambda t: t[1])[0]
    if metric in LOWER_IS_BETTER:
        return min(numeric, key=lambda t: t[1])[0]
    return None


def _pick_winner(results: list[dict[str, Any]]) -> str | None:
    if not results:
        return None
    scores: list[tuple[float, str]] = []
    for r in results:
        m = r.get("metrics", {})
        h5 = m.get("hit_at_5") or 0.0
        mrr = m.get("mrr") or 0.0
        cp = m.get("context_precision_mean") or 0.0
        ac = m.get("answer_correctness_mean") or 0.0
        score = h5 * 0.4 + mrr * 0.3 + cp * 0.2 + ac * 0.1
        scores.append((score, r["name"]))
    return max(scores, key=lambda t: t[0])[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare multiple retrieval configs and emit a comparison report."
    )
    parser.add_argument("--golden", default=str(DEFAULT_GOLDEN_PATH))
    parser.add_argument("--ingest-root", default=str(DEFAULT_INGEST_ROOT))
    parser.add_argument("--knowledge-base", default="fixture-local")
    parser.add_argument(
        "--configs",
        type=Path,
        default=None,
        help="JSON file with list of config dicts (name, chunk_size, chunk_overlap, "
        "embedding_dimensions, top_k). Defaults to built-in small/medium/large.",
    )
    parser.add_argument("--store-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.configs is not None:
        configs = json.loads(args.configs.read_text(encoding="utf-8"))
    else:
        configs = DEFAULT_CONFIGS

    report = run_config_compare_workflow(
        golden_path=Path(args.golden),
        ingest_root=Path(args.ingest_root),
        knowledge_base=args.knowledge_base,
        configs=configs,
        store_dir=args.store_dir,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    indent = 2 if args.pretty else None
    payload = json.dumps(report, indent=indent, ensure_ascii=False, sort_keys=True)
    args.output.write_text(payload + "\n", encoding="utf-8")
    args.markdown_output.write_text(report["markdown_summary"], encoding="utf-8")
    print(payload)
    failed = any(r.get("status") != "completed" for r in report.get("results", []))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
