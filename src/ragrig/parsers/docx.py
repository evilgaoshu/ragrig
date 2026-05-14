from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from docx import Document

from ragrig.parsers.base import ParseResult
from ragrig.parsers.sanitizer import sanitize_text_summary


class DocxParserError(ValueError):
    """Raised when a DOCX cannot be parsed by the Local Pilot parser."""


class DocxParser:
    parser_name = "docx"
    mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    limitations = (
        "Local Pilot extracts paragraph, heading, and list body text only; tables, images, "
        "headers, footers, comments, and tracked changes are not structurally preserved."
    )

    def parse(self, path: Path) -> ParseResult:
        raw_bytes = path.read_bytes()
        try:
            document = Document(path)
        except Exception as exc:
            raise DocxParserError(f"DOCX could not be read: {path.name}") from exc

        paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs]
        body_texts = [text for text in paragraphs if text]
        extracted_text = "\n".join(body_texts)
        if not extracted_text.strip():
            raise DocxParserError(f"DOCX has no extractable body text: {path.name}")

        summary, redactions = sanitize_text_summary(extracted_text)
        return ParseResult(
            extracted_text=extracted_text,
            content_hash=sha256(raw_bytes).hexdigest(),
            mime_type=self.mime_type,
            parser_name=self.parser_name,
            metadata={
                "parser_id": "parser.docx",
                "status": "success",
                "extension": path.suffix.lower(),
                "paragraph_count": len(body_texts),
                "char_count": len(extracted_text),
                "byte_count": len(raw_bytes),
                "text_summary": summary,
                "redaction_count": redactions,
                "limitations": self.limitations,
            },
        )
