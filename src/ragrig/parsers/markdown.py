from __future__ import annotations

from pathlib import Path

from ragrig.parsers.base import ParseResult, TextFileParser


class MarkdownParser(TextFileParser):
    parser_name = "markdown"
    mime_type = "text/markdown"

    def parse(self, path: Path) -> ParseResult:
        result = super().parse(path)
        return ParseResult(
            extracted_text=result.extracted_text,
            content_hash=result.content_hash,
            mime_type=result.mime_type,
            parser_name=result.parser_name,
            metadata={
                **result.metadata,
                "parser_id": "parser.markdown",
                "status": "success",
            },
        )
