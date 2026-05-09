"""Regenerate sanitizer golden snapshot files.

Usage::

    python -m scripts.snapshot_update

This re-parses every sensitive fixture and overwrites the corresponding
golden JSON file in tests/goldens/.  Review the diff before committing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "preview"
GOLDENS_DIR = REPO_ROOT / "tests" / "goldens"

MAPPING: list[tuple[str, str, str]] = [
    ("CsvParser", "sensitive.csv", "sanitizer_csv_sensitive.json"),
    ("HtmlParser", "sensitive.html", "sanitizer_html_sensitive.json"),
    ("PlainTextParser", "sensitive.txt", "sanitizer_plaintext_sensitive.json"),
    ("MarkdownParser", "sensitive.md", "sanitizer_markdown_sensitive.json"),
]


def _load_parser(name: str):
    if name == "CsvParser":
        from ragrig.parsers.csv import CsvParser

        return CsvParser()
    if name == "HtmlParser":
        from ragrig.parsers.html import HtmlParser

        return HtmlParser()
    if name == "PlainTextParser":
        from ragrig.parsers.plaintext import PlainTextParser

        return PlainTextParser()
    if name == "MarkdownParser":
        from ragrig.parsers.markdown import MarkdownParser

        return MarkdownParser()
    raise ValueError(f"Unknown parser: {name}")


def _build_record(metadata: dict) -> dict:
    record: dict = {
        "parser_id": metadata["parser_id"],
        "status": metadata["status"],
        "text_summary": metadata["text_summary"],
        "redaction_count": metadata["redaction_count"],
    }
    if "degraded_reason" in metadata:
        record["degraded_reason"] = metadata["degraded_reason"]
    if "csv_parse_error" in metadata:
        record["csv_parse_error"] = metadata["csv_parse_error"]
    return record


def main() -> None:
    GOLDENS_DIR.mkdir(parents=True, exist_ok=True)

    for parser_name, fixture_name, golden_name in MAPPING:
        fixture_path = FIXTURES_DIR / fixture_name
        if not fixture_path.is_file():
            print(f"Skipping {golden_name}: fixture {fixture_path} not found", file=sys.stderr)
            continue

        parser = _load_parser(parser_name)
        result = parser.parse(fixture_path)
        record = _build_record(result.metadata)

        golden_path = GOLDENS_DIR / golden_name
        golden_path.write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Updated {golden_path}  (redactions={record['redaction_count']})")


if __name__ == "__main__":
    main()
