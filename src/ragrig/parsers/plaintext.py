from __future__ import annotations

from ragrig.parsers.base import TextFileParser


class PlainTextParser(TextFileParser):
    parser_name = "plaintext"
    mime_type = "text/plain"
