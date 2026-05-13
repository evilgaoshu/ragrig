from __future__ import annotations

from pathlib import Path

from ragrig.parsers.advanced.models import AdvancedParseResult, ParserStatus


class OcrFallbackHandler:
    """Handles OCR fallback for advanced document parsers.

    When a primary parser is available but produces degraded results (e.g.
    scanned PDF with no extractable text), this handler can attempt OCR
    as a secondary pass. Actual OCR engines (Tesseract, cloud APIs) are
    not invoked here — this module manages the fallback metadata and
    orchestration logic only.
    """

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    def needs_ocr(self, result: AdvancedParseResult) -> bool:
        return result.status == ParserStatus.HEALTHY and result.text_length == 0

    def apply_ocr_fallback(
        self, path: Path, primary_result: AdvancedParseResult
    ) -> AdvancedParseResult:
        if not self._enabled:
            return primary_result
        if primary_result.text_length > 0:
            return primary_result
        try:
            import pytesseract  # noqa: F401
            from PIL import Image  # noqa: F401
        except ImportError:
            pass
        return AdvancedParseResult(
            format=primary_result.format,
            fixture_id=primary_result.fixture_id,
            parser=f"{primary_result.parser}+ocr(unavailable)",
            status=ParserStatus.DEGRADED,
            text_length=0,
            table_count=primary_result.table_count,
            page_or_slide_count=primary_result.page_or_slide_count,
            degraded_reason="ocr_fallback",
            metadata={
                "primary_parser": primary_result.parser,
                "ocr_available": False,
                "ocr_applied": False,
                **primary_result.metadata,
            },
        )

    def mark_ocr_fallback(self, result: AdvancedParseResult) -> AdvancedParseResult:
        if result.degraded_reason == "ocr_fallback":
            return result
        return AdvancedParseResult(
            format=result.format,
            fixture_id=result.fixture_id,
            parser=result.parser,
            status=ParserStatus.DEGRADED,
            text_length=result.text_length,
            table_count=result.table_count,
            page_or_slide_count=result.page_or_slide_count,
            degraded_reason="ocr_fallback",
            extracted_text=result.extracted_text,
            metadata={**result.metadata, "ocr_fallback_marked": True},
        )
