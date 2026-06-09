from __future__ import annotations

from pathlib import Path
from typing import Any

from ragrig.parsers.advanced.metadata import capability_metadata, package_version
from ragrig.parsers.advanced.models import AdvancedParseResult, DegradedReason, ParserStatus

_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"})


class OcrFallbackHandler:
    """Run an optional local Tesseract OCR pass for empty parser output."""

    def __init__(self, enabled: bool = False) -> None:
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    def needs_ocr(self, result: AdvancedParseResult) -> bool:
        return (
            result.status in {ParserStatus.HEALTHY, ParserStatus.DEGRADED}
            and result.text_length == 0
            and not result.extracted_text.strip()
        )

    def apply_ocr_fallback(
        self, path: Path, primary_result: AdvancedParseResult
    ) -> AdvancedParseResult:
        if not self.needs_ocr(primary_result):
            return self._with_ocr_metadata(primary_result)
        if not self._enabled:
            return self._degraded_result(
                primary_result,
                degraded_reason=DegradedReason.OCR_DISABLED.value,
                failure_reason=DegradedReason.OCR_DISABLED.value,
            )
        if path.suffix.lower() not in {".pdf", *_IMAGE_EXTENSIONS}:
            return self._degraded_result(
                primary_result,
                degraded_reason=DegradedReason.OCR_UNSUPPORTED_FORMAT.value,
                failure_reason=DegradedReason.OCR_UNSUPPORTED_FORMAT.value,
            )

        try:
            import pytesseract
            from PIL import Image
        except ImportError as exc:
            return self._degraded_result(
                primary_result,
                degraded_reason=DegradedReason.OCR_MISSING_DEPENDENCY.value,
                failure_reason=DegradedReason.OCR_MISSING_DEPENDENCY.value,
                error=str(exc),
            )

        try:
            images = _render_images(path, image_module=Image)
            page_text: list[str] = []
            for page_number, image in enumerate(images, start=1):
                try:
                    text = pytesseract.image_to_string(image).strip()
                finally:
                    close = getattr(image, "close", None)
                    if close is not None:
                        close()
                if text:
                    page_text.append(f"<!-- page {page_number}; source=ocr -->\n\n{text}")
            extracted_text = "\n\n".join(page_text)
        except Exception as exc:
            return self._degraded_result(
                primary_result,
                degraded_reason=DegradedReason.OCR_FAILED.value,
                failure_reason=DegradedReason.OCR_FAILED.value,
                error=f"{type(exc).__name__}: {exc}",
            )

        if not extracted_text:
            return self._degraded_result(
                primary_result,
                degraded_reason=DegradedReason.OCR_EMPTY_OUTPUT.value,
                failure_reason=DegradedReason.OCR_EMPTY_OUTPUT.value,
                ocr_applied=True,
            )

        metadata = {
            **primary_result.metadata,
            **capability_metadata(
                parser_name=f"{primary_result.parser}+advanced.ocr",
                parser_version=primary_result.metadata.get("parser_version"),
                page_count=max(primary_result.page_or_slide_count, len(images)),
                table_count=primary_result.table_count,
                image_count=primary_result.metadata.get("image_count", 0),
                chart_count=primary_result.metadata.get("chart_count", 0),
                formula_count=primary_result.metadata.get("formula_count", 0),
                image_degraded_reason=primary_result.metadata.get("image_degraded_reason"),
                chart_degraded_reason=primary_result.metadata.get("chart_degraded_reason"),
                formula_degraded_reason=primary_result.metadata.get("formula_degraded_reason"),
                ocr_enabled=True,
                ocr_applied=True,
                layout_aware=False,
                layout_source="tesseract",
                layout_degraded_reason="ocr_text_only",
                primary_parser=primary_result.parser,
                ocr_engine="tesseract",
                ocr_engine_version=package_version("pytesseract"),
            ),
        }
        return AdvancedParseResult(
            format=primary_result.format,
            fixture_id=primary_result.fixture_id,
            parser=f"{primary_result.parser}+advanced.ocr",
            status=ParserStatus.DEGRADED,
            text_length=len(extracted_text),
            table_count=primary_result.table_count,
            page_or_slide_count=max(primary_result.page_or_slide_count, len(images)),
            degraded_reason=DegradedReason.OCR_FALLBACK.value,
            extracted_text=extracted_text,
            metadata=metadata,
        )

    def mark_ocr_fallback(self, result: AdvancedParseResult) -> AdvancedParseResult:
        if result.degraded_reason == DegradedReason.OCR_FALLBACK.value:
            return result
        return AdvancedParseResult(
            format=result.format,
            fixture_id=result.fixture_id,
            parser=result.parser,
            status=ParserStatus.DEGRADED,
            text_length=result.text_length,
            table_count=result.table_count,
            page_or_slide_count=result.page_or_slide_count,
            degraded_reason=DegradedReason.OCR_FALLBACK.value,
            extracted_text=result.extracted_text,
            metadata={**result.metadata, "ocr_fallback_marked": True},
        )

    def _with_ocr_metadata(self, result: AdvancedParseResult) -> AdvancedParseResult:
        metadata = {
            **capability_metadata(
                parser_name=result.parser,
                parser_version=result.metadata.get("parser_version"),
                page_count=result.page_or_slide_count,
                table_count=result.table_count,
                image_count=result.metadata.get("image_count", 0),
                chart_count=result.metadata.get("chart_count", 0),
                formula_count=result.metadata.get("formula_count", 0),
                image_degraded_reason=result.metadata.get("image_degraded_reason"),
                chart_degraded_reason=result.metadata.get("chart_degraded_reason"),
                formula_degraded_reason=result.metadata.get("formula_degraded_reason"),
                ocr_enabled=self._enabled or bool(result.metadata.get("ocr_enabled")),
                ocr_applied=bool(result.metadata.get("ocr_applied")),
                ocr_failure_reason=result.metadata.get("ocr_failure_reason"),
                layout_aware=bool(result.metadata.get("layout_aware")),
                layout_source=result.metadata.get("layout_source"),
                layout_degraded_reason=result.metadata.get("layout_degraded_reason"),
            ),
            **result.metadata,
        }
        return AdvancedParseResult(
            format=result.format,
            fixture_id=result.fixture_id,
            parser=result.parser,
            status=result.status,
            text_length=result.text_length,
            table_count=result.table_count,
            page_or_slide_count=result.page_or_slide_count,
            degraded_reason=result.degraded_reason,
            extracted_text=result.extracted_text,
            metadata=metadata,
        )

    def _degraded_result(
        self,
        primary_result: AdvancedParseResult,
        *,
        degraded_reason: str,
        failure_reason: str,
        ocr_applied: bool = False,
        error: str | None = None,
    ) -> AdvancedParseResult:
        metadata = {
            **primary_result.metadata,
            **capability_metadata(
                parser_name=primary_result.parser,
                parser_version=primary_result.metadata.get("parser_version"),
                page_count=primary_result.page_or_slide_count,
                table_count=primary_result.table_count,
                image_count=primary_result.metadata.get("image_count", 0),
                chart_count=primary_result.metadata.get("chart_count", 0),
                formula_count=primary_result.metadata.get("formula_count", 0),
                image_degraded_reason=primary_result.metadata.get("image_degraded_reason"),
                chart_degraded_reason=primary_result.metadata.get("chart_degraded_reason"),
                formula_degraded_reason=primary_result.metadata.get("formula_degraded_reason"),
                ocr_enabled=self._enabled,
                ocr_applied=ocr_applied,
                ocr_failure_reason=failure_reason,
                layout_aware=False,
                layout_source=primary_result.metadata.get("layout_source"),
                layout_degraded_reason="empty_output",
                primary_parser=primary_result.parser,
                ocr_engine="tesseract",
                ocr_engine_version=package_version("pytesseract"),
                **({"ocr_error": error} if error else {}),
            ),
        }
        return AdvancedParseResult(
            format=primary_result.format,
            fixture_id=primary_result.fixture_id,
            parser=primary_result.parser,
            status=ParserStatus.DEGRADED,
            text_length=primary_result.text_length,
            table_count=primary_result.table_count,
            page_or_slide_count=primary_result.page_or_slide_count,
            degraded_reason=degraded_reason,
            extracted_text=primary_result.extracted_text,
            metadata=metadata,
        )


def _render_images(path: Path, *, image_module: Any) -> list[Any]:
    if path.suffix.lower() in _IMAGE_EXTENSIONS:
        return [image_module.open(path)]

    try:
        import pypdfium2
    except ImportError as exc:
        raise RuntimeError("pypdfium2 is required to render PDF pages for OCR") from exc

    pdf = pypdfium2.PdfDocument(path)
    try:
        return [page.render(scale=2).to_pil() for page in pdf]
    finally:
        close = getattr(pdf, "close", None)
        if close is not None:
            close()
