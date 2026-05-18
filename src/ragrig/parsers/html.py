from __future__ import annotations

import hashlib
import re
from pathlib import Path

from ragrig.parsers.base import ParseResult, TextFileParser
from ragrig.parsers.sanitizer import sanitize_text_summary

# Tags whose text content we always drop (scripts, styles, etc.)
_SKIP_TAGS = frozenset({"script", "style", "noscript", "head", "meta", "link", "iframe", "svg"})
# Block-level tags that should become newline separators
_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "main",
        "header",
        "footer",
        "aside",
        "nav",
        "blockquote",
        "pre",
        "li",
        "dt",
        "dd",
        "td",
        "th",
        "caption",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "tr",
    }
)


def _lxml_extract(raw: str) -> tuple[str, str]:
    """Return (extracted_text, backend) using lxml; fall back to regex."""
    try:
        from lxml import html as lxml_html

        tree = lxml_html.fromstring(raw)
        parts: list[str] = []

        def _walk(el: object) -> None:
            tag = getattr(el, "tag", None)
            if not isinstance(tag, str):
                return
            tag_lower = tag.lower().split("}")[-1]
            if tag_lower in _SKIP_TAGS:
                return
            prefix = "\n" if tag_lower in _BLOCK_TAGS else ""
            text = (getattr(el, "text", None) or "").strip()
            if text:
                parts.append(prefix + text)
            for child in el:
                _walk(child)
            tail = (getattr(el, "tail", None) or "").strip()
            if tail:
                parts.append(tail)

        _walk(tree)
        extracted = re.sub(r"\n{3,}", "\n\n", "\n".join(p for p in parts if p)).strip()
        return extracted, "lxml"
    except Exception:
        stripped = re.sub(r"<[^>]+>", "", raw)
        stripped = re.sub(r"\s+", " ", stripped).strip()
        return stripped, "regex_fallback"


class HtmlParser(TextFileParser):
    parser_name = "html"
    mime_type = "text/html"

    def parse(self, path: Path) -> ParseResult:
        raw_bytes = path.read_bytes()
        raw_text = raw_bytes.decode("utf-8")

        extracted_text, backend = _lxml_extract(raw_text)

        summary, redactions = sanitize_text_summary(extracted_text)
        return ParseResult(
            extracted_text=extracted_text,
            content_hash=hashlib.sha256(raw_bytes).hexdigest(),
            mime_type=self.mime_type,
            parser_name=self.parser_name,
            metadata={
                "parser_id": "parser.html",
                "status": "success",
                "backend": backend,
                "encoding": "utf-8",
                "extension": path.suffix.lower(),
                "line_count": len(raw_text.splitlines()),
                "char_count": len(extracted_text),
                "byte_count": len(raw_bytes),
                "text_summary": summary,
                "redaction_count": redactions,
            },
        )
