from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from ragrig.parsers.advanced.adapter import AdvancedParserAdapter
from ragrig.parsers.advanced.metadata import capability_metadata, package_version
from ragrig.parsers.advanced.models import AdvancedParseResult, DegradedReason, ParserStatus
from ragrig.parsers.advanced.service_client import parse_with_service


class MinerUAdapter(AdvancedParserAdapter):
    """Adapter for MinerU-based document parsing.

    MinerU (https://github.com/opendatalab/MinerU) provides PDF parsing with
    advanced layout analysis and OCR. This adapter checks for dependency
    availability and returns skip/degraded status when the library is not
    installed.
    """

    parser_name = "advanced.mineru"
    SUPPORTED_EXTENSIONS = frozenset({".pdf"})

    def __init__(
        self,
        *,
        service_url: str | None = None,
        service_timeout_seconds: float = 30.0,
    ) -> None:
        self.service_url = service_url or os.getenv("RAGRIG_MINERU_SERVICE_URL")
        self.service_timeout_seconds = service_timeout_seconds

    def can_parse(self, path: Path) -> bool:
        return path.suffix.lower() in self.SUPPORTED_EXTENSIONS

    def check_dependencies(self) -> bool:
        if self.service_url:
            return True
        try:
            import magic_pdf  # noqa: F401

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
                layout_source="mineru-service",
            )
        fmt = path.suffix.lstrip(".").lower()
        parser_version = package_version("magic-pdf", "mineru")
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
                    ocr_enabled=True,
                    layout_source="mineru",
                    library="magic_pdf",
                    available=False,
                ),
            )

        try:
            from magic_pdf.data.data_reader_writer import FileBasedDataWriter
            from magic_pdf.data.dataset import PymuDocDataset
            from magic_pdf.model.doc_analyze_by_custom_model import doc_analyze

            pdf_bytes = path.read_bytes()
            dataset = PymuDocDataset(pdf_bytes)
            extracted_text = _run_mineru_pass(
                dataset=dataset,
                doc_analyze=doc_analyze,
                writer_class=FileBasedDataWriter,
                ocr=False,
            )
            ocr_applied = False
            ocr_failure_reason: str | None = None
            ocr_error: str | None = None
            if not extracted_text.strip():
                try:
                    extracted_text = _run_mineru_pass(
                        dataset=dataset,
                        doc_analyze=doc_analyze,
                        writer_class=FileBasedDataWriter,
                        ocr=True,
                    )
                    ocr_applied = True
                except Exception as exc:
                    ocr_failure_reason = DegradedReason.OCR_FAILED.value
                    ocr_error = f"{type(exc).__name__}: {exc}"

            # Count approximate table structures (separator rows that contain |---|)
            table_count = sum(
                1
                for line in extracted_text.splitlines()
                if line.strip().startswith("|") and "---" in line
            )

            # Count pages via embedded page markers (<!-- page N ... -->)
            page_markers = re.findall(r"<!-- page\s+\d+", extracted_text, re.IGNORECASE)
            page_count = len(page_markers) if page_markers else 0
            image_count = len(re.findall(r"!\[[^\]]*]\([^)]*\)", extracted_text))
            formula_count = len(re.findall(r"\$\$.*?\$\$", extracted_text, re.DOTALL))

            if not extracted_text.strip():
                status = ParserStatus.DEGRADED
                degraded_reason: str | None = (
                    ocr_failure_reason or DegradedReason.OCR_EMPTY_OUTPUT.value
                )
                if ocr_failure_reason is None:
                    ocr_failure_reason = DegradedReason.OCR_EMPTY_OUTPUT.value
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
                metadata=capability_metadata(
                    parser_name=self.parser_name,
                    parser_version=parser_version,
                    page_count=page_count,
                    table_count=table_count,
                    image_count=image_count,
                    formula_count=formula_count,
                    image_degraded_reason=("artifacts_not_persisted" if image_count else None),
                    formula_degraded_reason=(
                        "semantic_interpretation_not_supported" if formula_count else None
                    ),
                    ocr_enabled=True,
                    ocr_applied=ocr_applied,
                    ocr_failure_reason=ocr_failure_reason,
                    layout_aware=True,
                    layout_source="mineru",
                    library="magic_pdf",
                    available=True,
                    ocr_error=ocr_error,
                    image_artifacts_persisted=False,
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
                    ocr_enabled=True,
                    ocr_failure_reason=DegradedReason.PARSER_ERROR.value,
                    layout_source="mineru",
                    layout_degraded_reason=DegradedReason.PARSER_ERROR.value,
                    library="magic_pdf",
                    available=True,
                    error=f"{type(exc).__name__}: {exc}",
                ),
            )


def _run_mineru_pass(*, dataset, doc_analyze, writer_class, ocr: bool) -> str:
    infer_result = doc_analyze(dataset=dataset, ocr=ocr)
    with tempfile.TemporaryDirectory() as tmp_dir:
        writer = writer_class(tmp_dir)
        pipe_method = getattr(infer_result, "pipe_ocr_mode", None) if ocr else None
        if pipe_method is None:
            pipe_method = infer_result.pipe_txt_mode
        pipe_result = pipe_method(image_writer=writer)
        return pipe_result.get_markdown(img_dir_str="images")
