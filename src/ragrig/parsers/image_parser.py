"""Image parser — extracts text from raster images via Tesseract OCR."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ragrig.parsers.base import ParseResult, TextFileParser
from ragrig.parsers.sanitizer import sanitize_text_summary


class ImageParser(TextFileParser):
    parser_name = "image"
    mime_type = "image/png"

    def parse(self, path: Path) -> ParseResult:
        try:
            import pytesseract
            from PIL import Image
        except ImportError as exc:
            raise ImportError(
                "Install pytesseract and Pillow for image OCR: pip install pytesseract Pillow"
            ) from exc

        img = Image.open(path)
        text = pytesseract.image_to_string(img)
        text = text.strip()
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        return ParseResult(
            text=text,
            content_hash=content_hash,
            mime_type=f"image/{path.suffix.lstrip('.').lower()}",
            summary=sanitize_text_summary(text[:300]),
            metadata={"file_name": path.name, "ocr": True},
            parser_name=self.parser_name,
        )
