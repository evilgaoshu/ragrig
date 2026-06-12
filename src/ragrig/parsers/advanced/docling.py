from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ragrig.parsers.advanced.adapter import AdvancedParserAdapter
from ragrig.parsers.advanced.metadata import capability_metadata, package_version
from ragrig.parsers.advanced.models import AdvancedParseResult, DegradedReason, ParserStatus
from ragrig.parsers.advanced.service_client import parse_with_service


class DoclingAdapter(AdvancedParserAdapter):
    """Docling-based document parser with layout analysis and table extraction.

    Supports PDF, DOCX, PPTX, XLSX with OCR, table-to-Markdown conversion,
    and multi-column layout handling.  Install: pip install docling
    """

    parser_name = "advanced.docling"
    SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".pptx", ".xlsx"})

    def __init__(
        self,
        *,
        service_url: str | None = None,
        service_timeout_seconds: float = 30.0,
    ) -> None:
        self.service_url = service_url or os.getenv("RAGRIG_DOCLING_SERVICE_URL")
        self.service_timeout_seconds = service_timeout_seconds

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def check_dependencies(self) -> bool:
        if self.service_url:
            return True
        try:
            from docling.document_converter import DocumentConverter  # noqa: F401

            return True
        except ImportError:
            return False

    def parse(self, path: Path) -> AdvancedParseResult:
        if self.service_url:
            return parse_with_service(
                parser_name=self.parser_name,
                service_url=self.service_url,
                timeout_seconds=self.service_timeout_seconds,
                path=path,
                layout_source="docling-service",
            )
        fmt = path.suffix.lstrip(".").lower()
        parser_version = package_version("docling")
        if not self.check_dependencies():
            return AdvancedParseResult(
                format=fmt,
                fixture_id=path.stem,
                parser=self.parser_name,
                status=ParserStatus.SKIP,
                degraded_reason=DegradedReason.MISSING_DEPENDENCY.value,
                metadata=capability_metadata(
                    parser_name=self.parser_name,
                    parser_version=parser_version,
                    ocr_enabled=fmt == "pdf",
                    layout_source="docling",
                    library="docling",
                    available=False,
                ),
            )

        try:
            from docling.datamodel.document import ConversionStatus

            converter = _document_converter(fmt)
            result = converter.convert(path, raises_on_error=False)

            if result.status not in (
                ConversionStatus.SUCCESS,
                ConversionStatus.PARTIAL_SUCCESS,
            ):
                return AdvancedParseResult(
                    format=fmt,
                    fixture_id=path.stem,
                    parser=self.parser_name,
                    status=ParserStatus.FAILURE,
                    degraded_reason=DegradedReason.PARSER_ERROR.value,
                    metadata=capability_metadata(
                        parser_name=self.parser_name,
                        parser_version=parser_version,
                        ocr_enabled=fmt == "pdf",
                        ocr_failure_reason=(
                            DegradedReason.PARSER_ERROR.value if fmt == "pdf" else None
                        ),
                        layout_source="docling",
                        layout_degraded_reason=DegradedReason.PARSER_ERROR.value,
                        library="docling",
                        available=True,
                        conversion_status=result.status.value,
                        errors=[str(e) for e in (getattr(result, "errors", None) or [])],
                    ),
                )

            doc = result.document
            # export_to_markdown renders tables as GFM Markdown tables
            extracted_text = doc.export_to_markdown(
                strict_text=False,
                escape_underscores=False,
            )
            table_count = len(getattr(doc, "tables", None) or [])
            page_count = _page_count(result, doc)
            image_count, chart_count = _picture_counts(doc)
            formula_count = _formula_count(doc)

            status = ParserStatus.HEALTHY
            degraded_reason = None
            if result.status == ConversionStatus.PARTIAL_SUCCESS:
                status = ParserStatus.DEGRADED
                degraded_reason = DegradedReason.PARTIAL_SUCCESS.value
            if not extracted_text.strip():
                status = ParserStatus.DEGRADED
                degraded_reason = DegradedReason.EMPTY_OUTPUT.value

            return AdvancedParseResult(
                format=fmt,
                fixture_id=path.stem,
                parser=self.parser_name,
                status=status,
                extracted_text=extracted_text,
                text_length=len(extracted_text),
                table_count=table_count,
                page_or_slide_count=page_count,
                degraded_reason=degraded_reason,
                metadata=capability_metadata(
                    parser_name=self.parser_name,
                    parser_version=parser_version,
                    page_count=page_count,
                    table_count=table_count,
                    image_count=image_count,
                    chart_count=chart_count,
                    formula_count=formula_count,
                    image_degraded_reason=("artifacts_not_persisted" if image_count else None),
                    chart_degraded_reason=(
                        "semantic_interpretation_not_supported" if chart_count else None
                    ),
                    formula_degraded_reason=(
                        "semantic_interpretation_not_supported" if formula_count else None
                    ),
                    ocr_enabled=fmt == "pdf",
                    ocr_applied=fmt == "pdf" and bool(page_count),
                    layout_aware=True,
                    layout_source="docling",
                    library="docling",
                    available=True,
                    conversion_status=result.status.value,
                    errors=[str(e) for e in (getattr(result, "errors", None) or [])],
                ),
            )

        except Exception as exc:
            return AdvancedParseResult(
                format=fmt,
                fixture_id=path.stem,
                parser=self.parser_name,
                status=ParserStatus.FAILURE,
                degraded_reason=DegradedReason.PARSER_ERROR.value,
                metadata=capability_metadata(
                    parser_name=self.parser_name,
                    parser_version=parser_version,
                    ocr_enabled=fmt == "pdf",
                    ocr_failure_reason=(
                        DegradedReason.PARSER_ERROR.value if fmt == "pdf" else None
                    ),
                    layout_source="docling",
                    layout_degraded_reason=DegradedReason.PARSER_ERROR.value,
                    library="docling",
                    available=True,
                    error=f"{type(exc).__name__}: {exc}",
                ),
            )


def _document_converter(fmt: str):
    from docling.document_converter import DocumentConverter

    if fmt != "pdf":
        return DocumentConverter()

    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import PdfFormatOption

    pipeline_options = PdfPipelineOptions(do_ocr=True, do_table_structure=True)
    return DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        }
    )


def _page_count(result: Any, doc: Any) -> int:
    pages = getattr(result, "pages", None)
    if pages is not None:
        try:
            return len(pages)
        except TypeError:
            pass
    value = getattr(doc, "num_pages", 0)
    return value if isinstance(value, int) else 0


def _picture_counts(doc: Any) -> tuple[int, int]:
    pictures = list(getattr(doc, "pictures", None) or [])
    chart_count = 0
    for picture in pictures:
        classification = str(getattr(picture, "classification", "")).casefold()
        if "chart" in classification:
            chart_count += 1
    return len(pictures), chart_count


def _formula_count(doc: Any) -> int:
    formulas = getattr(doc, "formulas", None)
    if formulas is not None:
        try:
            return len(formulas)
        except TypeError:
            pass
    return sum(
        1
        for item in (getattr(doc, "texts", None) or [])
        if "formula" in str(getattr(item, "label", "")).casefold()
    )
