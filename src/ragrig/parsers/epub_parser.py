from __future__ import annotations

import hashlib
import html
import re
from pathlib import Path

from ragrig.parsers.base import ParseResult, TextFileParser
from ragrig.parsers.sanitizer import sanitize_text_summary


def _strip_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"\s+", " ", text)
    return html.unescape(text).strip()


class EpubParser(TextFileParser):
    parser_name = "epub"
    mime_type = "application/epub+zip"

    def parse(self, path: Path) -> ParseResult:
        raw_bytes = path.read_bytes()
        content_hash = hashlib.sha256(raw_bytes).hexdigest()

        try:
            import ebooklib  # type: ignore[import-untyped]
            from ebooklib import epub
        except ImportError as exc:
            summary, redactions = sanitize_text_summary("")
            return ParseResult(
                extracted_text="",
                content_hash=content_hash,
                mime_type=self.mime_type,
                parser_name=self.parser_name,
                metadata={
                    "parser_id": "parser.epub",
                    "status": "error",
                    "error": f"ebooklib not installed: {exc}",
                    "extension": path.suffix.lower(),
                    "text_summary": summary,
                    "redaction_count": redactions,
                },
            )

        try:
            book = epub.read_epub(str(path), options={"ignore_ncx": True})
        except Exception as exc:
            summary, redactions = sanitize_text_summary("")
            return ParseResult(
                extracted_text="",
                content_hash=content_hash,
                mime_type=self.mime_type,
                parser_name=self.parser_name,
                metadata={
                    "parser_id": "parser.epub",
                    "status": "error",
                    "error": str(exc),
                    "extension": path.suffix.lower(),
                    "text_summary": summary,
                    "redaction_count": redactions,
                },
            )

        title = book.title or path.stem
        chapter_texts: list[str] = []
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            raw_html = item.get_content().decode("utf-8", errors="replace")
            text = _strip_html(raw_html)
            if text:
                chapter_texts.append(text)

        extracted_text = f"Title: {title}\n\n" + "\n\n".join(chapter_texts)
        summary, redactions = sanitize_text_summary(extracted_text)

        return ParseResult(
            extracted_text=extracted_text,
            content_hash=content_hash,
            mime_type=self.mime_type,
            parser_name=self.parser_name,
            metadata={
                "parser_id": "parser.epub",
                "status": "success",
                "extension": path.suffix.lower(),
                "title": title,
                "chapter_count": len(chapter_texts),
                "char_count": len(extracted_text),
                "byte_count": len(raw_bytes),
                "text_summary": summary,
                "redaction_count": redactions,
            },
        )
