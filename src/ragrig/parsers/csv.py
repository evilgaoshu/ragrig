from __future__ import annotations

import csv
from pathlib import Path

from ragrig.parsers.base import ParseResult, TextFileParser
from ragrig.parsers.sanitizer import sanitize_text_summary


class CsvParser(TextFileParser):
    parser_name = "csv"
    mime_type = "text/csv"

    def parse(self, path: Path) -> ParseResult:
        raw_bytes = path.read_bytes()
        text = raw_bytes.decode("utf-8")
        line_count = len(text.splitlines())
        if text == "":
            line_count = 0

        # Best-effort: extract row/column counts without failing on malformed CSV
        row_count = 0
        col_count = 0
        degraded_details: dict[str, object] | None = None
        try:
            # Increase csv field size limit for large rows
            csv.field_size_limit(max(1024 * 1024, len(text)))
            reader = csv.reader(text.splitlines())
            rows = list(reader)
            row_count = len(rows)
            col_count = max(len(r) for r in rows) if rows else 0
        except Exception as exc:
            degraded_details = {"csv_parse_error": str(exc)}

        summary, redactions = sanitize_text_summary(text)
        return ParseResult(
            extracted_text=text,
            content_hash=__import__("hashlib").sha256(raw_bytes).hexdigest(),
            mime_type=self.mime_type,
            parser_name=self.parser_name,
            metadata={
                "parser_id": "parser.csv",
                "status": "degraded",
                "degraded_reason": (
                    "Parsed as plain text; CSV structure awareness not implemented."
                ),
                "encoding": "utf-8",
                "extension": path.suffix.lower(),
                "line_count": line_count,
                "char_count": len(text),
                "byte_count": len(raw_bytes),
                "row_count": row_count,
                "col_count": col_count,
                "text_summary": summary,
                "redaction_count": redactions,
                **(
                    {"csv_parse_error": degraded_details["csv_parse_error"]}
                    if degraded_details
                    else {}
                ),
            },
        )
