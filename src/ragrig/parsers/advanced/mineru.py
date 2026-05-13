from __future__ import annotations

from pathlib import Path

from ragrig.parsers.advanced.adapter import AdvancedParserAdapter
from ragrig.parsers.advanced.models import AdvancedParseResult, ParserStatus


class MinerUAdapter(AdvancedParserAdapter):
    """Adapter stub for MinerU-based document parsing.

    MinerU (https://github.com/opendatalab/MinerU) provides PDF parsing with
    advanced layout analysis and OCR. This stub checks for dependency availability
    and returns skip/degraded status when the library is not installed.
    """

    parser_name = "advanced.mineru"
    SUPPORTED_EXTENSIONS = frozenset({".pdf", ".docx", ".pptx", ".xlsx"})

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def check_dependencies(self) -> bool:
        try:
            import magic_pdf  # noqa: F401

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
                metadata={"library": "magic_pdf", "available": False},
            )
        try:
            # TODO: implement real MinerU parsing
            # from magic_pdf.pipe import Pipeline
            # pipe = Pipeline(path)
            # result = pipe.execute()
            raise NotImplementedError("MinerU adapter not yet implemented")
        except Exception as exc:
            return AdvancedParseResult(
                format=self.get_format(),
                fixture_id=path.stem,
                parser=self.parser_name,
                status=ParserStatus.FAILURE,
                degraded_reason="parser_error",
                metadata={"library": "magic_pdf", "available": True, "error": str(exc)},
            )
