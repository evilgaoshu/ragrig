from __future__ import annotations

from pathlib import Path

from ragrig.parsers.advanced.adapter import AdvancedParserAdapter
from ragrig.parsers.advanced.models import AdvancedParseResult, ParserStatus


class DoclingAdapter(AdvancedParserAdapter):
    """Docling-based document parser with layout analysis and table extraction.

    Supports PDF, DOCX, PPTX, XLSX with OCR, table-to-Markdown conversion,
    and multi-column layout handling.  Install: pip install docling
    """

    parser_name = "advanced.docling"
    SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".pptx", ".xlsx"})

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def check_dependencies(self) -> bool:
        try:
            from docling.document_converter import DocumentConverter  # noqa: F401

            return True
        except ImportError:
            return False

    def parse(self, path: Path) -> AdvancedParseResult:
        fmt = path.suffix.lstrip(".").lower()
        if not self.check_dependencies():
            return AdvancedParseResult(
                format=fmt,
                fixture_id=path.stem,
                parser=self.parser_name,
                status=ParserStatus.SKIP,
                degraded_reason="missing_dependency",
                metadata={"library": "docling", "available": False},
            )

        try:
            from docling.datamodel.document import ConversionStatus
            from docling.document_converter import DocumentConverter

            converter = DocumentConverter()
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
                    degraded_reason="parser_error",
                    metadata={
                        "library": "docling",
                        "available": True,
                        "conversion_status": result.status.value,
                        "errors": [str(e) for e in result.errors],
                    },
                )

            doc = result.document
            # export_to_markdown renders tables as GFM Markdown tables
            extracted_text = doc.export_to_markdown(
                strict_text=False,
                escape_underscores=False,
            )
            table_count = len(doc.tables) if doc.tables else 0
            page_count = doc.num_pages if hasattr(doc, "num_pages") else 0

            status = (
                ParserStatus.DEGRADED
                if result.status == ConversionStatus.PARTIAL_SUCCESS
                else ParserStatus.HEALTHY
            )
            degraded_reason = (
                "partial_success" if result.status == ConversionStatus.PARTIAL_SUCCESS else None
            )

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
                metadata={
                    "library": "docling",
                    "available": True,
                    "conversion_status": result.status.value,
                    "table_count": table_count,
                    "page_count": page_count,
                },
            )

        except Exception as exc:
            return AdvancedParseResult(
                format=fmt,
                fixture_id=path.stem,
                parser=self.parser_name,
                status=ParserStatus.FAILURE,
                degraded_reason="parser_error",
                metadata={"library": "docling", "available": True, "error": str(exc)},
            )
