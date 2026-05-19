from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ragrig.parsers.base import ParseResult, TextFileParser
from ragrig.parsers.sanitizer import sanitize_text_summary


def _flatten(obj: Any, prefix: str = "") -> list[str]:
    lines: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            lines.extend(_flatten(v, key))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            lines.extend(_flatten(v, f"{prefix}[{i}]" if prefix else f"[{i}]"))
    elif obj is not None:
        label = f"{prefix}: " if prefix else ""
        lines.append(f"{label}{obj}")
    return lines


class JsonParser(TextFileParser):
    parser_name = "json"
    mime_type = "application/json"

    def parse(self, path: Path) -> ParseResult:
        raw_bytes = path.read_bytes()
        content_hash = hashlib.sha256(raw_bytes).hexdigest()

        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            summary, redactions = sanitize_text_summary("")
            return ParseResult(
                extracted_text="",
                content_hash=content_hash,
                mime_type=self.mime_type,
                parser_name=self.parser_name,
                metadata={
                    "parser_id": "parser.json",
                    "status": "error",
                    "error": str(exc),
                    "extension": path.suffix.lower(),
                    "text_summary": summary,
                    "redaction_count": redactions,
                },
            )

        top_type = (
            "object" if isinstance(data, dict) else "array" if isinstance(data, list) else "scalar"
        )
        lines = _flatten(data)
        extracted_text = "\n".join(lines)
        summary, redactions = sanitize_text_summary(extracted_text)

        return ParseResult(
            extracted_text=extracted_text,
            content_hash=content_hash,
            mime_type=self.mime_type,
            parser_name=self.parser_name,
            metadata={
                "parser_id": "parser.json",
                "status": "success",
                "extension": path.suffix.lower(),
                "top_level_type": top_type,
                "top_level_keys": len(data) if isinstance(data, (dict, list)) else 1,
                "char_count": len(extracted_text),
                "byte_count": len(raw_bytes),
                "text_summary": summary,
                "redaction_count": redactions,
            },
        )
