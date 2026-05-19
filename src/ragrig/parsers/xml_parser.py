from __future__ import annotations

import hashlib
from pathlib import Path
from xml.etree import ElementTree as ET

from ragrig.parsers.base import ParseResult, TextFileParser
from ragrig.parsers.sanitizer import sanitize_text_summary


def _iter_text(element: ET.Element) -> list[str]:
    parts: list[str] = []
    if element.text and element.text.strip():
        parts.append(element.text.strip())
    for child in element:
        parts.extend(_iter_text(child))
        if child.tail and child.tail.strip():
            parts.append(child.tail.strip())
    return parts


class XmlParser(TextFileParser):
    parser_name = "xml"
    mime_type = "application/xml"

    def parse(self, path: Path) -> ParseResult:
        raw_bytes = path.read_bytes()
        content_hash = hashlib.sha256(raw_bytes).hexdigest()

        try:
            root = ET.fromstring(raw_bytes)
        except ET.ParseError as exc:
            summary, redactions = sanitize_text_summary("")
            return ParseResult(
                extracted_text="",
                content_hash=content_hash,
                mime_type=self.mime_type,
                parser_name=self.parser_name,
                metadata={
                    "parser_id": "parser.xml",
                    "status": "error",
                    "error": str(exc),
                    "extension": path.suffix.lower(),
                    "text_summary": summary,
                    "redaction_count": redactions,
                },
            )

        text_parts = _iter_text(root)
        extracted_text = "\n".join(text_parts)
        summary, redactions = sanitize_text_summary(extracted_text)

        return ParseResult(
            extracted_text=extracted_text,
            content_hash=content_hash,
            mime_type=self.mime_type,
            parser_name=self.parser_name,
            metadata={
                "parser_id": "parser.xml",
                "status": "success",
                "extension": path.suffix.lower(),
                "root_tag": root.tag,
                "element_count": sum(1 for _ in root.iter()),
                "char_count": len(extracted_text),
                "byte_count": len(raw_bytes),
                "text_summary": summary,
                "redaction_count": redactions,
            },
        )
