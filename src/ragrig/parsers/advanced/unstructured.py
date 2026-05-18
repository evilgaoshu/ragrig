from __future__ import annotations

from pathlib import Path

from ragrig.parsers.advanced.adapter import AdvancedParserAdapter
from ragrig.parsers.advanced.models import AdvancedParseResult, ParserStatus


class UnstructuredAdapter(AdvancedParserAdapter):
    """Unstructured-IO based document parser with OCR support.

    Handles PDF (including scanned/mixed), DOCX, PPTX, XLSX with layout
    analysis. Falls back to SKIP status when the library is not installed.
    Install: pip install "unstructured[pdf,docx,pptx,xlsx]"
    """

    parser_name = "advanced.unstructured"
    SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".pptx", ".xlsx"})

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def check_dependencies(self) -> bool:
        try:
            import unstructured  # noqa: F401

            return True
        except ImportError:
            return False

    def parse(self, path: Path) -> AdvancedParseResult:
        if not self.check_dependencies():
            return AdvancedParseResult(
                format=path.suffix.lstrip(".").lower(),
                fixture_id=path.stem,
                parser=self.parser_name,
                status=ParserStatus.SKIP,
                degraded_reason="missing_dependency",
                metadata={"library": "unstructured", "available": False},
            )

        try:
            from unstructured.partition.auto import partition

            elements = partition(str(path))
        except Exception as exc:
            return AdvancedParseResult(
                format=path.suffix.lstrip(".").lower(),
                fixture_id=path.stem,
                parser=self.parser_name,
                status=ParserStatus.FAILURE,
                degraded_reason="parser_error",
                metadata={"library": "unstructured", "available": True, "error": str(exc)},
            )

        text_parts: list[str] = []
        table_count = 0
        page_count = 0
        seen_pages: set[int] = set()

        for element in elements:
            element_text = str(element).strip()
            if not element_text:
                continue

            element_type = type(element).__name__

            # Track table elements
            if "Table" in element_type:
                table_count += 1

            # Track page numbers if available
            metadata = getattr(element, "metadata", None)
            if metadata is not None:
                page_num = getattr(metadata, "page_number", None)
                if page_num is not None:
                    seen_pages.add(page_num)

            text_parts.append(element_text)

        page_count = len(seen_pages) if seen_pages else 0
        extracted_text = "\n\n".join(text_parts)

        status = ParserStatus.HEALTHY
        degraded_reason = None
        if not extracted_text.strip():
            status = ParserStatus.DEGRADED
            degraded_reason = "parser_error"

        return AdvancedParseResult(
            format=path.suffix.lstrip(".").lower(),
            fixture_id=path.stem,
            parser=self.parser_name,
            status=status,
            extracted_text=extracted_text,
            text_length=len(extracted_text),
            table_count=table_count,
            page_or_slide_count=page_count,
            degraded_reason=degraded_reason,
            metadata={
                "library": "unstructured",
                "available": True,
                "element_count": len(elements),
            },
        )
