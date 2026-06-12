from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from ragrig.parsers.advanced.metadata import capability_metadata
from ragrig.parsers.advanced.models import AdvancedParseResult, DegradedReason, ParserStatus

_SAFE_SERVICE_METADATA_KEYS = {
    "request_id",
    "model",
    "pipeline",
    "duration_ms",
    "image_count",
    "chart_count",
    "formula_count",
    "image_degraded_reason",
    "chart_degraded_reason",
    "formula_degraded_reason",
    "ocr_failure_reason",
    "layout_degraded_reason",
}


def parse_with_service(
    *,
    parser_name: str,
    service_url: str,
    timeout_seconds: float,
    path: Path,
    layout_source: str,
) -> AdvancedParseResult:
    fmt = path.suffix.lstrip(".").lower()
    try:
        with path.open("rb") as handle:
            response = httpx.post(
                service_url,
                files={"file": (path.name, handle, "application/octet-stream")},
                timeout=timeout_seconds,
            )
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        return _failure(
            path,
            parser_name=parser_name,
            reason=DegradedReason.SERVICE_TIMEOUT.value,
            layout_source=layout_source,
            error=f"{type(exc).__name__}: {exc}",
        )
    except httpx.HTTPStatusError as exc:
        return _failure(
            path,
            parser_name=parser_name,
            reason=DegradedReason.SERVICE_HTTP_ERROR.value,
            layout_source=layout_source,
            error=f"HTTP {exc.response.status_code}",
        )
    except (httpx.HTTPError, OSError) as exc:
        return _failure(
            path,
            parser_name=parser_name,
            reason=DegradedReason.SERVICE_UNAVAILABLE.value,
            layout_source=layout_source,
            error=f"{type(exc).__name__}: {exc}",
            status=ParserStatus.SKIP,
        )
    except Exception as exc:
        return _failure(
            path,
            parser_name=parser_name,
            reason=DegradedReason.SERVICE_UNAVAILABLE.value,
            layout_source=layout_source,
            error=f"{type(exc).__name__}: {exc}",
        )

    try:
        payload = response.json()
    except ValueError as exc:
        return _failure(
            path,
            parser_name=parser_name,
            reason=DegradedReason.SERVICE_MALFORMED_RESPONSE.value,
            layout_source=layout_source,
            error=f"{type(exc).__name__}: {exc}",
        )
    if not isinstance(payload, dict) or not isinstance(payload.get("extracted_text"), str):
        return _failure(
            path,
            parser_name=parser_name,
            reason=DegradedReason.SERVICE_MALFORMED_RESPONSE.value,
            layout_source=layout_source,
            error="response must be an object with string extracted_text",
        )

    extracted_text = payload["extracted_text"]
    page_count = _nonnegative_int(payload.get("page_count"))
    table_count = _nonnegative_int(payload.get("table_count"))
    raw_metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    safe_metadata = {
        key: value
        for key, value in raw_metadata.items()
        if key in _SAFE_SERVICE_METADATA_KEYS and _safe_scalar(value)
    }
    status = _service_status(payload.get("status"), extracted_text)
    degraded_reason = payload.get("degraded_reason")
    if not isinstance(degraded_reason, str) or not degraded_reason:
        if not extracted_text.strip():
            degraded_reason = DegradedReason.EMPTY_OUTPUT.value
        elif status == ParserStatus.DEGRADED:
            degraded_reason = DegradedReason.PARTIAL_SUCCESS.value
        elif status in {ParserStatus.FAILURE, ParserStatus.SKIP}:
            degraded_reason = DegradedReason.PARSER_ERROR.value
        else:
            degraded_reason = None
    if status == ParserStatus.HEALTHY:
        degraded_reason = None

    return AdvancedParseResult(
        format=fmt,
        fixture_id=path.stem,
        parser=parser_name,
        status=status,
        text_length=len(extracted_text),
        table_count=table_count,
        page_or_slide_count=page_count,
        degraded_reason=degraded_reason,
        extracted_text=extracted_text,
        metadata=capability_metadata(
            parser_name=parser_name,
            parser_version=_optional_string(payload.get("parser_version")),
            page_count=page_count,
            table_count=table_count,
            image_count=_nonnegative_int(payload.get("image_count")),
            chart_count=_nonnegative_int(payload.get("chart_count")),
            formula_count=_nonnegative_int(payload.get("formula_count")),
            ocr_enabled=bool(payload.get("ocr_enabled", fmt == "pdf")),
            ocr_applied=bool(payload.get("ocr_applied")),
            ocr_failure_reason=_optional_string(payload.get("ocr_failure_reason")),
            layout_aware=bool(payload.get("layout_aware")),
            layout_source=_optional_string(payload.get("layout_source")) or layout_source,
            layout_degraded_reason=_optional_string(payload.get("layout_degraded_reason")),
            service_mode=True,
            available=True,
            service_metadata=safe_metadata,
        ),
    )


def _failure(
    path: Path,
    *,
    parser_name: str,
    reason: str,
    layout_source: str,
    error: str,
    status: ParserStatus = ParserStatus.FAILURE,
) -> AdvancedParseResult:
    return AdvancedParseResult(
        format=path.suffix.lstrip(".").lower(),
        fixture_id=path.stem,
        parser=parser_name,
        status=status,
        degraded_reason=reason,
        metadata=capability_metadata(
            parser_name=parser_name,
            parser_version=None,
            ocr_enabled=path.suffix.lower() == ".pdf",
            ocr_failure_reason=reason,
            layout_source=layout_source,
            layout_degraded_reason=reason,
            service_mode=True,
            available=False,
            error=error,
        ),
    )


def _service_status(value: Any, extracted_text: str) -> ParserStatus:
    try:
        status = ParserStatus(str(value))
    except ValueError:
        return ParserStatus.HEALTHY if extracted_text.strip() else ParserStatus.DEGRADED
    if status == ParserStatus.HEALTHY and not extracted_text.strip():
        return ParserStatus.DEGRADED
    return status


def _nonnegative_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _safe_scalar(value: Any) -> bool:
    return value is None or isinstance(value, str | int | float | bool)
