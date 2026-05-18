from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from ragrig.parsers.base import ParseResult, TextFileParser
from ragrig.parsers.sanitizer import sanitize_text_summary


class CsvParser(TextFileParser):
    parser_name = "csv"
    mime_type = "text/csv"

    def parse(self, path: Path) -> ParseResult:
        raw_bytes = path.read_bytes()
        raw_text = raw_bytes.decode("utf-8")

        if not raw_text.strip():
            summary, redactions = sanitize_text_summary("")
            return ParseResult(
                extracted_text="",
                content_hash=hashlib.sha256(raw_bytes).hexdigest(),
                mime_type=self.mime_type,
                parser_name=self.parser_name,
                metadata={
                    "parser_id": "parser.csv",
                    "status": "success",
                    "encoding": "utf-8",
                    "extension": path.suffix.lower(),
                    "line_count": 0,
                    "char_count": 0,
                    "byte_count": len(raw_bytes),
                    "row_count": 0,
                    "col_count": 0,
                    "text_summary": summary,
                    "redaction_count": redactions,
                },
            )

        csv.field_size_limit(max(1024 * 1024, len(raw_text)))
        parse_error: str | None = None
        rows: list[list[str]] = []
        try:
            reader = csv.reader(raw_text.splitlines())
            rows = list(reader)
        except Exception as exc:
            parse_error = str(exc)

        if rows and not parse_error and len(rows) >= 2:
            headers = rows[0]
            data_rows = rows[1:]
            parts: list[str] = []
            for row in data_rows:
                pairs = []
                for i, val in enumerate(row):
                    header = headers[i] if i < len(headers) else f"col{i}"
                    val = val.strip()
                    if val:
                        pairs.append(f"{header}: {val}")
                if pairs:
                    parts.append(", ".join(pairs))
            extracted_text = "\n".join(parts) if parts else raw_text
            status = "success"
            row_count = len(data_rows)
            col_count = len(headers)
        else:
            extracted_text = raw_text
            status = "degraded" if parse_error else "success"
            row_count = len(rows)
            col_count = max((len(r) for r in rows), default=0)

        summary, redactions = sanitize_text_summary(extracted_text)
        metadata: dict[str, object] = {
            "parser_id": "parser.csv",
            "status": status,
            "encoding": "utf-8",
            "extension": path.suffix.lower(),
            "line_count": len(raw_text.splitlines()),
            "char_count": len(extracted_text),
            "byte_count": len(raw_bytes),
            "row_count": row_count,
            "col_count": col_count,
            "text_summary": summary,
            "redaction_count": redactions,
        }
        if parse_error:
            metadata["degraded_reason"] = "CSV parse error; falling back to raw text"
            metadata["csv_parse_error"] = parse_error
        return ParseResult(
            extracted_text=extracted_text,
            content_hash=hashlib.sha256(raw_bytes).hexdigest(),
            mime_type=self.mime_type,
            parser_name=self.parser_name,
            metadata=metadata,
        )
