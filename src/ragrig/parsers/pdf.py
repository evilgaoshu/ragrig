from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from ragrig.parsers.base import ParseResult
from ragrig.parsers.sanitizer import sanitize_text_summary


class PdfParserError(ValueError):
    """Raised when a PDF cannot be parsed by the Local Pilot parser."""


class PdfParser:
    parser_name = "pdf"
    mime_type = "application/pdf"

    def parse(self, path: Path) -> ParseResult:
        raw_bytes = path.read_bytes()
        try:
            reader = PdfReader(path)
        except PdfReadError as exc:
            raise PdfParserError(f"PDF could not be read: {path.name}") from exc

        if reader.is_encrypted:
            raise PdfParserError(f"PDF is encrypted and cannot be parsed: {path.name}")

        page_texts: list[str] = []
        degraded_pages: list[int] = []
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                page_text = page.extract_text() or ""
            except Exception:
                page_text = ""
            page_text = page_text.strip()
            if page_text:
                page_texts.append(page_text)
            else:
                degraded_pages.append(page_number)

        extracted_text = "\n\n".join(page_texts)
        if not extracted_text.strip():
            raise PdfParserError(f"PDF has no extractable text: {path.name}")

        summary, redactions = sanitize_text_summary(extracted_text)
        metadata = {
            "parser_id": "parser.pdf",
            "status": "success",
            "extension": path.suffix.lower(),
            "page_count": len(reader.pages),
            "char_count": len(extracted_text),
            "byte_count": len(raw_bytes),
            "text_summary": summary,
            "redaction_count": redactions,
        }
        if degraded_pages:
            metadata.update(
                {
                    "status": "degraded",
                    "degraded_pages": degraded_pages,
                    "degraded_reason": "Some PDF pages had no extractable text.",
                }
            )

        return ParseResult(
            extracted_text=extracted_text,
            content_hash=sha256(raw_bytes).hexdigest(),
            mime_type=self.mime_type,
            parser_name=self.parser_name,
            metadata=metadata,
        )
