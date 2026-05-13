from __future__ import annotations

from pathlib import Path

from ragrig.parsers.advanced.adapter import AdvancedParserAdapter
from ragrig.parsers.advanced.models import AdvancedParseResult, ParserStatus


class UnstructuredAdapter(AdvancedParserAdapter):
    """Adapter stub for Unstructured-IO based document parsing.

    Unstructured (https://github.com/Unstructured-IO/unstructured) provides
    parsing for PDF, DOCX, PPTX, XLSX and many other formats with OCR support.
    This stub checks for dependency availability and returns skip/degraded
    status when the library is not installed.
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
                format=self.get_format(),
                fixture_id=path.stem,
                parser=self.parser_name,
                status=ParserStatus.SKIP,
                degraded_reason="missing_dependency",
                metadata={"library": "unstructured", "available": False},
            )
        try:
            # TODO: implement real Unstructured parsing
            # from unstructured.partition.auto import partition
            # elements = partition(str(path))
            # text = "\\n".join(str(e) for e in elements)
            # tables = [e for e in elements if 'Table' in type(e).__name__]
            raise NotImplementedError("Unstructured adapter not yet implemented")
        except Exception as exc:
            return AdvancedParseResult(
                format=self.get_format(),
                fixture_id=path.stem,
                parser=self.parser_name,
                status=ParserStatus.FAILURE,
                degraded_reason="parser_error",
                metadata={"library": "unstructured", "available": True, "error": str(exc)},
            )
