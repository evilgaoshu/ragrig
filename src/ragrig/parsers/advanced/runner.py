from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ragrig.parsers.advanced.adapter import AdvancedParserAdapter
from ragrig.parsers.advanced.docling import DoclingAdapter
from ragrig.parsers.advanced.mineru import MinerUAdapter
from ragrig.parsers.advanced.models import (
    AdvancedParseResult,
    ArtifactEntry,
    ArtifactSchema,
    CorpusSummary,
    DegradedReason,
    ParserStatus,
)
from ragrig.parsers.advanced.ocr import OcrFallbackHandler
from ragrig.parsers.advanced.unstructured import UnstructuredAdapter


class AdvancedParserRunner:
    """Orchestrates advanced document parsing across multiple adapters.

    Discovers fixture files, dispatches to the appropriate adapter,
    applies OCR fallback when needed, and produces a corpus summary.
    """

    def __init__(
        self,
        fixtures_dir: Path,
        ocr_enabled: bool = False,
        adapters: list[AdvancedParserAdapter] | None = None,
    ) -> None:
        self._fixtures_dir = fixtures_dir
        self._ocr = OcrFallbackHandler(enabled=ocr_enabled)
        self._adapters = adapters or [
            DoclingAdapter(),
            MinerUAdapter(),
            UnstructuredAdapter(),
        ]

    def discover_fixtures(self) -> list[dict[str, Any]]:
        if not self._fixtures_dir.exists():
            return []
        fixtures: list[dict[str, Any]] = []
        for path in sorted(self._fixtures_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in {
                ".pdf",
                ".docx",
                ".pptx",
                ".xlsx",
            }:
                fixtures.append(
                    {
                        "path": path,
                        "fixture_id": path.stem,
                        "format": path.suffix.lower().lstrip("."),
                    }
                )
        return fixtures

    def run_all(self) -> CorpusSummary:
        fixtures = self.discover_fixtures()
        results: list[AdvancedParseResult] = []

        for fixture in fixtures:
            path: Path = fixture["path"]
            result = self._run_single(path)
            results.append(result)

        summary = CorpusSummary(
            generated_at=datetime.now(timezone.utc).isoformat(),
            total_fixtures=len(fixtures),
            healthy=sum(1 for r in results if r.status == ParserStatus.HEALTHY),
            degraded=sum(1 for r in results if r.status == ParserStatus.DEGRADED),
            skipped=sum(1 for r in results if r.status == ParserStatus.SKIP),
            failed=sum(1 for r in results if r.status == ParserStatus.FAILURE),
            results=sorted(results, key=lambda r: (r.format, r.fixture_id)),
        )
        return summary

    def _run_single(self, path: Path) -> AdvancedParseResult:
        ext = path.suffix.lower()

        if not path.exists():
            return AdvancedParseResult(
                format=ext.lstrip("."),
                fixture_id=path.stem,
                parser="none",
                status=ParserStatus.FAILURE,
                degraded_reason=DegradedReason.CORRUPT_ARTIFACT.value,
                metadata={"error": "file not found"},
            )

        try:
            raw_bytes = path.read_bytes()
            __import__("hashlib").sha256(raw_bytes).hexdigest()
        except Exception as exc:
            return AdvancedParseResult(
                format=ext.lstrip("."),
                fixture_id=path.stem,
                parser="none",
                status=ParserStatus.FAILURE,
                degraded_reason=DegradedReason.CORRUPT_ARTIFACT.value,
                metadata={"error": f"cannot read file: {exc}"},
            )

        if len(raw_bytes) == 0:
            return AdvancedParseResult(
                format=ext.lstrip("."),
                fixture_id=path.stem,
                parser="none",
                status=ParserStatus.DEGRADED,
                degraded_reason=DegradedReason.CORRUPT_ARTIFACT.value,
                metadata={"error": "empty file"},
            )

        matched_adapters = [a for a in self._adapters if a.can_parse(path)]
        if not matched_adapters:
            return AdvancedParseResult(
                format=ext.lstrip("."),
                fixture_id=path.stem,
                parser="none",
                status=ParserStatus.SKIP,
                degraded_reason=DegradedReason.UNSUPPORTED_FORMAT.value,
                metadata={"extension": ext},
            )

        errors: list[str] = []
        for adapter in matched_adapters:
            if not adapter.check_dependencies():
                continue
            try:
                result = adapter.parse(path)
                ocr_result = self._ocr.apply_ocr_fallback(path, result)
                return ocr_result
            except Exception as exc:
                errors.append(f"{adapter.parser_name}: {exc}")
                continue

        for adapter in matched_adapters:
            if not adapter.check_dependencies():
                return AdvancedParseResult(
                    format=ext.lstrip("."),
                    fixture_id=path.stem,
                    parser=adapter.parser_name,
                    status=ParserStatus.SKIP,
                    degraded_reason=DegradedReason.MISSING_DEPENDENCY.value,
                    metadata={"library": adapter.parser_name, "available": False},
                )
        return AdvancedParseResult(
            format=ext.lstrip("."),
            fixture_id=path.stem,
            parser="|".join(a.parser_name for a in matched_adapters),
            status=ParserStatus.FAILURE,
            degraded_reason=DegradedReason.PARSER_ERROR.value,
            metadata={"errors": errors},
        )

    def generate_artifact_schema(self, summary: CorpusSummary) -> ArtifactSchema:
        artifacts: list[ArtifactEntry] = []
        for fixture in self.discover_fixtures():
            path: Path = fixture["path"]
            raw_bytes = path.read_bytes()
            artifacts.append(
                ArtifactEntry(
                    fixture_id=fixture["fixture_id"],
                    format=fixture["format"],
                    path=str(path),
                    content_hash=__import__("hashlib").sha256(raw_bytes).hexdigest(),
                    size_bytes=len(raw_bytes),
                    created_at=datetime.fromtimestamp(
                        path.stat().st_mtime, tz=timezone.utc
                    ).isoformat(),
                )
            )
        return ArtifactSchema(
            version="1.0.0",
            artifacts=artifacts,
            generated_at=summary.generated_at,
        )

    def summary_to_json(self, summary: CorpusSummary) -> str:
        data = {
            "generated_at": summary.generated_at,
            "total_fixtures": summary.total_fixtures,
            "healthy": summary.healthy,
            "degraded": summary.degraded,
            "skipped": summary.skipped,
            "failed": summary.failed,
            "results": [
                {
                    "format": r.format,
                    "fixture_id": r.fixture_id,
                    "parser": r.parser,
                    "status": r.status.value,
                    "text_length": r.text_length,
                    "table_count": r.table_count,
                    "page_or_slide_count": r.page_or_slide_count,
                    "degraded_reason": r.degraded_reason,
                }
                for r in summary.results
            ],
            "report_path": summary.report_path,
        }
        return json.dumps(data, indent=2, ensure_ascii=False)

    def summary_to_markdown(self, summary: CorpusSummary) -> str:
        lines: list[str] = [
            "# Advanced Parser Corpus Status",
            "",
            f"- **Generated at**: {summary.generated_at}",
            f"- **Total fixtures**: {summary.total_fixtures}",
            f"- **Healthy**: {summary.healthy}",
            f"- **Degraded**: {summary.degraded}",
            f"- **Skipped**: {summary.skipped}",
            f"- **Failed**: {summary.failed}",
            "",
            "## Results",
            "",
            "| Fmt | Fixture ID | Parser | Status | TxtLen | Tbl | Pg | Degraded Reason |",
            "|-----|-----------|--------|--------|--------|-----|----|-----------------|",
        ]
        for r in summary.results:
            lines.append(
                f"| {r.format} | {r.fixture_id} | {r.parser} | {r.status.value} "
                f"| {r.text_length} | {r.table_count} | {r.page_or_slide_count} "
                f"| {r.degraded_reason or ''} |"
            )
        lines.append("")
        return "\n".join(lines)
