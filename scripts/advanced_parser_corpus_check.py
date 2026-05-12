"""Advanced Parser Corpus Check - quality gate for document parsing fixtures.

Usage:
    python -m scripts.advanced_parser_corpus_check [--json-output PATH] [--markdown-output PATH]

Exits with code:
    0  - all fixtures healthy or skipped (missing deps)
    1  - any fixture degraded or failed
    2  - corrupt artifact detected
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ragrig.parsers.advanced import AdvancedParserRunner, ParserStatus
from ragrig.parsers.advanced.models import CorpusSummary

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "advanced_documents"
DEFAULT_ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "docs" / "operations" / "artifacts"


def _make_markdown(summary: CorpusSummary) -> str:
    return (
        "# Advanced Parser Corpus Status\n\n"
        f"- **Generated at**: {summary.generated_at}\n"
        f"- **Total fixtures**: {summary.total_fixtures}\n"
        f"- **Healthy**: {summary.healthy}\n"
        f"- **Degraded**: {summary.degraded}\n"
        f"- **Skipped**: {summary.skipped}\n"
        f"- **Failed**: {summary.failed}\n\n"
        "## Results\n\n"
        "| Fmt | Fixture ID | Parser | Status | TxtLen | Tbl | Pg | Degraded Reason |\n"
        "|-----|-----------|--------|--------|--------|-----|----|-----------------|\n"
        + "\n".join(
            f"| {r.format} | {r.fixture_id} | {r.parser} | {r.status.value} "
            f"| {r.text_length} | {r.table_count} | {r.page_or_slide_count} "
            f"| {r.degraded_reason or ''} |"
            for r in summary.results
        )
        + "\n"
    )


def _make_json(summary: CorpusSummary) -> str:
    return json.dumps(
        {
            "generated_at": summary.generated_at,
            "total_fixtures": summary.total_fixtures,
            "healthy": summary.healthy,
            "degraded": summary.degraded,
            "skipped": summary.skipped,
            "failed": summary.failed,
            "results": [
                {
                    "format": r.format,
                    "fixture_id": r.fixture_id,
                    "parser": r.parser,
                    "status": r.status.value,
                    "text_length": r.text_length,
                    "table_count": r.table_count,
                    "page_or_slide_count": r.page_or_slide_count,
                    "degraded_reason": r.degraded_reason,
                }
                for r in summary.results
            ],
            "report_path": summary.report_path,
        },
        indent=2,
        ensure_ascii=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Advanced Parser Corpus Check")
    parser.add_argument("--json-output", type=str, default=None, help="Path to JSON output")
    parser.add_argument("--markdown-output", type=str, default=None, help="Path to Markdown output")
    parser.add_argument("--ocr", action="store_true", help="Enable OCR fallback")
    args = parser.parse_args()

    runner = AdvancedParserRunner(fixtures_dir=FIXTURES_DIR, ocr_enabled=args.ocr)
    summary = runner.run_all()

    print("Advanced Parser Corpus Check")
    print(f"{'=' * 40}")
    print(f"  Total fixtures: {summary.total_fixtures}")
    print(f"  Healthy:        {summary.healthy}")
    print(f"  Degraded:       {summary.degraded}")
    print(f"  Skipped:        {summary.skipped}")
    print(f"  Failed:         {summary.failed}")
    print(f"{'=' * 40}")
    for r in summary.results:
        print(f"  [{r.status.value.upper():>8}] {r.format:>4} {r.fixture_id:20} "
              f"parser={r.parser:25} reason={r.degraded_reason or ''}")

    json_str = _make_json(summary)
    md_str = _make_markdown(summary)

    if args.json_output:
        out_path = Path(args.json_output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_str, encoding="utf-8")
        print(f"\nJSON report written to {out_path}")

    if args.markdown_output:
        out_path = Path(args.markdown_output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md_str, encoding="utf-8")
        print(f"\nMarkdown report written to {out_path}")

    has_failure = any(r.status == ParserStatus.FAILURE for r in summary.results)
    has_corrupt = any(
        r.degraded_reason == "corrupt_artifact" for r in summary.results
    )
    if has_corrupt:
        return 2
    if has_failure:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
