from __future__ import annotations

import csv
from pathlib import Path

from ragrig.parsers.base import ParseResult, TextFileParser


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
        try:
            reader = csv.reader(text.splitlines())
            rows = list(reader)
            row_count = len(rows)
            col_count = max(len(r) for r in rows) if rows else 0
        except Exception:
            pass

        return ParseResult(
            extracted_text=text,
            content_hash=__import__("hashlib").sha256(raw_bytes).hexdigest(),
            mime_type=self.mime_type,
            parser_name=self.parser_name,
            metadata={
                "encoding": "utf-8",
                "extension": path.suffix.lower(),
                "line_count": line_count,
                "char_count": len(text),
                "row_count": row_count,
                "col_count": col_count,
                "degraded_reason": (
                    "Parsed as plain text; CSV structure awareness not implemented."
                ),
            },
        )
