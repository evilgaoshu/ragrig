from __future__ import annotations

from pathlib import Path

from ragrig.parsers.advanced.adapter import AdvancedParserAdapter
from ragrig.parsers.advanced.models import AdvancedParseResult, ParserStatus


class DoclingAdapter(AdvancedParserAdapter):
    """Adapter stub for Docling-based document parsing.

    Docling (https://github.com/DS4SD/docling) provides PDF, DOCX, PPTX, XLSX
    parsing with OCR support. This stub checks for dependency availability and
    returns skip/degraded status when the library is not installed.
    """

    parser_name = "advanced.docling"
    SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".pptx", ".xlsx"})

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def check_dependencies(self) -> bool:
        try:
            import docling  # noqa: F401

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
                metadata={"library": "docling", "available": False},
            )
        try:
            # TODO: implement real Docling parsing
            # from docling.document import Document
            # doc = Document(path)
            # text = doc.text
            # tables = doc.tables
            # pages = doc.pages
            raise NotImplementedError("Docling adapter not yet implemented")
        except Exception as exc:
            return AdvancedParseResult(
                format=self.get_format(),
                fixture_id=path.stem,
                parser=self.parser_name,
                status=ParserStatus.FAILURE,
                degraded_reason="parser_error",
                metadata={"library": "docling", "available": True, "error": str(exc)},
            )
