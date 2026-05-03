from __future__ import annotations

from ragrig.parsers.base import TextFileParser


class MarkdownParser(TextFileParser):
    parser_name = "markdown"
    mime_type = "text/markdown"
