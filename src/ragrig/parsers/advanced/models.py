from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ParserStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    SKIP = "skip"
    FAILURE = "failure"


class DegradedReason(str, Enum):
    MISSING_DEPENDENCY = "missing_dependency"
    CORRUPT_ARTIFACT = "corrupt_artifact"
    STALE_ARTIFACT = "stale_artifact"
    PARSER_TIMEOUT = "parser_timeout"
    PARSER_ERROR = "parser_error"
    OCR_FALLBACK = "ocr_fallback"
    UNSUPPORTED_FORMAT = "unsupported_format"


@dataclass(frozen=True)
class AdvancedParseResult:
    format: str
    fixture_id: str
    parser: str
    status: ParserStatus
    text_length: int = 0
    table_count: int = 0
    page_or_slide_count: int = 0
    degraded_reason: str | None = None
    extracted_text: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactEntry:
    fixture_id: str
    format: str
    path: str
    content_hash: str
    size_bytes: int
    created_at: str


@dataclass(frozen=True)
class ArtifactSchema:
    version: str = "1.0.0"
    artifacts: list[ArtifactEntry] = field(default_factory=list)
    generated_at: str = ""


@dataclass(frozen=True)
class CorpusSummary:
    generated_at: str
    total_fixtures: int
    healthy: int
    degraded: int
    skipped: int
    failed: int
    results: list[AdvancedParseResult] = field(default_factory=list)
    report_path: str | None = None
