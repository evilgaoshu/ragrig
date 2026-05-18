from __future__ import annotations

import re
import tempfile
from pathlib import Path

from ragrig.parsers.advanced.adapter import AdvancedParserAdapter
from ragrig.parsers.advanced.models import AdvancedParseResult, ParserStatus


class MinerUAdapter(AdvancedParserAdapter):
    """Adapter for MinerU-based document parsing.

    MinerU (https://github.com/opendatalab/MinerU) provides PDF parsing with
    advanced layout analysis and OCR. This adapter checks for dependency
    availability and returns skip/degraded status when the library is not
    installed.
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
        fmt = path.suffix.lstrip(".").lower()
        if not self.check_dependencies():
            return AdvancedParseResult(
                format=fmt,
                fixture_id=path.stem,
                parser=self.parser_name,
                status=ParserStatus.SKIP,
                degraded_reason="missing_dependency",
                metadata={"library": "magic_pdf", "available": False},
            )

        try:
            from magic_pdf.data.data_reader_writer import FileBasedDataWriter
            from magic_pdf.data.dataset import PymuDocDataset
            from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze

            pdf_bytes = path.read_bytes()
            dataset = PymuDocDataset(pdf_bytes)
            infer_result = doc_analyze(dataset=dataset, ocr=False)

            with tempfile.TemporaryDirectory() as tmp_dir:
                writer = FileBasedDataWriter(tmp_dir)
                pipe_result = infer_result.pipe_txt_mode(image_writer=writer)
                extracted_text = pipe_result.get_markdown(img_dir_str=tmp_dir)

            # Count approximate table structures (separator rows that contain |---|)
            table_count = sum(
                1
                for line in extracted_text.splitlines()
                if line.strip().startswith("|") and "---" in line
            )

            # Count pages via embedded page markers (<!-- page N ... -->)
            page_markers = re.findall(r"<!-- page\s+\d+", extracted_text, re.IGNORECASE)
            page_count = len(page_markers) if page_markers else 0

            if not extracted_text.strip():
                status = ParserStatus.DEGRADED
                degraded_reason: str | None = "empty_output"
            else:
                status = ParserStatus.HEALTHY
                degraded_reason = None

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
                    "library": "magic_pdf",
                    "available": True,
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
                metadata={
                    "library": "magic_pdf",
                    "available": True,
                    "error": str(exc),
                },
            )
