from __future__ import annotations

import hashlib
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
from ragrig.parsers.sanitizer import sanitize_text_summary

_KNOWN_FIXTURES: list[dict[str, str]] = [
    {"fixture_id": "sample", "format": "pdf", "filename": "sample.pdf"},
    {"fixture_id": "sample", "format": "docx", "filename": "sample.docx"},
    {"fixture_id": "sample", "format": "pptx", "filename": "sample.pptx"},
    {"fixture_id": "sample", "format": "xlsx", "filename": "sample.xlsx"},
]


def _sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        if isinstance(value, str) and key != "text_summary":
            safe[key] = value
        elif isinstance(value, str) and key == "text_summary":
            safe[key], _ = sanitize_text_summary(value)
        elif isinstance(value, list):
            safe[key] = [v for v in value if not isinstance(v, str) or not _is_secret_like(v)]
        else:
            safe[key] = value
    return safe


def _is_secret_like(text: str) -> bool:
    lowered = text.lower()
    triggers = ["api_key", "password", "secret", "token", "credential", "sk-", "ghp_", "bearer "]
    return any(t in lowered for t in triggers)


class AdvancedParserRunner:
    def __init__(
        self,
        fixtures_dir: Path,
        ocr_enabled: bool = False,
        adapters: list[AdvancedParserAdapter] | None = None,
        known_fixtures: list[dict[str, str]] | None = None,
    ) -> None:
        self._fixtures_dir = fixtures_dir
        self._ocr = OcrFallbackHandler(enabled=ocr_enabled)
        self._adapters = adapters or [
            DoclingAdapter(),
            MinerUAdapter(),
            UnstructuredAdapter(),
        ]
        self._known_fixtures = known_fixtures

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

        if self._known_fixtures is not None:
            found_ids = {(f["fixture_id"], f["format"]) for f in fixtures}
            for known in self._known_fixtures:
                key = (known["fixture_id"], known["format"])
                if key not in found_ids:
                    results.append(
                        AdvancedParseResult(
                            format=known["format"],
                            fixture_id=known["fixture_id"],
                            parser="none",
                            status=ParserStatus.FAILURE,
                            degraded_reason=DegradedReason.CORRUPT_ARTIFACT.value,
                            metadata={"error": f"missing expected fixture: {known['filename']}"},
                        )
                    )
                    continue
                match = [f for f in fixtures if (f["fixture_id"], f["format"]) == key]
                if match:
                    result = self._run_single(match[0]["path"])
                    results.append(result)

        for fixture in fixtures:
            key = (fixture["fixture_id"], fixture["format"])
            if self._known_fixtures is not None:
                known_keys = {(k["fixture_id"], k["format"]) for k in self._known_fixtures}
                if key in known_keys:
                    continue
            result = self._run_single(fixture["path"])
            results.append(result)

        summary = CorpusSummary(
            generated_at=datetime.now(timezone.utc).isoformat(),
            total_fixtures=max(len(results), len(fixtures)),
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
            hashlib.sha256(raw_bytes).hexdigest()
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
                sanitized = self._sanitize_result(result)
                ocr_result = self._ocr.apply_ocr_fallback(path, sanitized)
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

    def _sanitize_result(self, result: AdvancedParseResult) -> AdvancedParseResult:
        safe_meta: dict[str, Any] = {}
        total_redactions = 0

        raw_text_summary = result.metadata.get("text_summary", "")
        if raw_text_summary:
            safe_summary, summary_redactions = sanitize_text_summary(raw_text_summary)
            total_redactions += summary_redactions
        elif result.extracted_text:
            safe_summary, summary_redactions = sanitize_text_summary(result.extracted_text[:500])
            total_redactions += summary_redactions
        else:
            safe_summary = ""

        for key, value in result.metadata.items():
            if key == "text_summary":
                continue
            if isinstance(value, str):
                _, v_redactions = sanitize_text_summary(value)
                total_redactions += v_redactions
            safe_meta[key] = value

        safe_meta["redaction_count"] = total_redactions
        safe_meta["text_summary"] = safe_summary

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
            metadata=safe_meta,
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
                    content_hash=hashlib.sha256(raw_bytes).hexdigest(),
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
