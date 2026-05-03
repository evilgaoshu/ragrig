from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ParseResult:
    extracted_text: str
    content_hash: str
    mime_type: str
    parser_name: str
    metadata: dict[str, Any]


class TextFileParser:
    parser_name = "text"
    mime_type = "text/plain"

    def parse(self, path: Path) -> ParseResult:
        raw_bytes = path.read_bytes()
        text = raw_bytes.decode("utf-8")
        line_count = len(text.splitlines())
        if text == "":
            line_count = 0
        return ParseResult(
            extracted_text=text,
            content_hash=sha256(raw_bytes).hexdigest(),
            mime_type=self.mime_type,
            parser_name=self.parser_name,
            metadata={
                "encoding": "utf-8",
                "extension": path.suffix.lower(),
                "line_count": line_count,
                "char_count": len(text),
            },
        )
