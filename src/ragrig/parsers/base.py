from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from ragrig.parsers.sanitizer import sanitize_text_summary


@dataclass(frozen=True)
class ParseResult:
    extracted_text: str
    content_hash: str
    mime_type: str
    parser_name: str
    metadata: dict[str, Any]


class ParserTimeoutError(TimeoutError):
    """Raised when a parser exceeds its allowed execution time."""


class TextFileParser:
    parser_name = "text"
    mime_type = "text/plain"

    def parse(self, path: Path) -> ParseResult:
        raw_bytes = path.read_bytes()
        text = raw_bytes.decode("utf-8")
        line_count = len(text.splitlines())
        if text == "":
            line_count = 0
        summary, redactions = sanitize_text_summary(text)
        return ParseResult(
            extracted_text=text,
            content_hash=sha256(raw_bytes).hexdigest(),
            mime_type=self.mime_type,
            parser_name=self.parser_name,
            metadata={
                "parser_id": f"parser.{self.parser_name}",
                "status": "success",
                "encoding": "utf-8",
                "extension": path.suffix.lower(),
                "line_count": line_count,
                "char_count": len(text),
                "byte_count": len(raw_bytes),
                "text_summary": summary,
                "redaction_count": redactions,
            },
        )


def parse_with_timeout(parser, path: Path, timeout_seconds: float = 30.0) -> ParseResult:
    """Run parser.parse(path) with a timeout to avoid hung parsers."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(parser.parse, path)
        try:
            return future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError as exc:
            raise ParserTimeoutError(
                f"Parser '{parser.parser_name}' timed out after {timeout_seconds}s for {path.name}"
            ) from exc
