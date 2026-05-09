from __future__ import annotations

import re
from pathlib import Path

from ragrig.parsers.base import ParseResult, TextFileParser


class HtmlParser(TextFileParser):
    parser_name = "html"
    mime_type = "text/html"

    def parse(self, path: Path) -> ParseResult:
        raw_bytes = path.read_bytes()
        text = raw_bytes.decode("utf-8")
        line_count = len(text.splitlines())
        if text == "":
            line_count = 0

        # Best-effort: strip tags and collapse whitespace
        stripped = re.sub(r"<[^>]+>", "", text)
        stripped = re.sub(r"\s+", " ", stripped).strip()

        return ParseResult(
            extracted_text=stripped,
            content_hash=__import__("hashlib").sha256(raw_bytes).hexdigest(),
            mime_type=self.mime_type,
            parser_name=self.parser_name,
            metadata={
                "encoding": "utf-8",
                "extension": path.suffix.lower(),
                "line_count": line_count,
                "char_count": len(text),
                "stripped_char_count": len(stripped),
                "degraded_reason": ("HTML tags stripped; structure and links are lost."),
            },
        )
