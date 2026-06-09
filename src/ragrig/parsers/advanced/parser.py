from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from ragrig.parsers.advanced.adapter import AdvancedParserAdapter
from ragrig.parsers.advanced.docling import DoclingAdapter
from ragrig.parsers.advanced.metadata import capability_metadata, result_audit_metadata
from ragrig.parsers.advanced.mineru import MinerUAdapter
from ragrig.parsers.advanced.models import AdvancedParseResult, DegradedReason, ParserStatus
from ragrig.parsers.advanced.ocr import OcrFallbackHandler
from ragrig.parsers.base import ParseResult
from ragrig.parsers.sanitizer import sanitize_text_summary

_MIME_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class AdvancedParserBridge:
    """Expose advanced adapters through the standard ingestion parser interface."""

    parser_name = "advanced"

    def __init__(
        self,
        *,
        strategy: str = "auto",
        adapters: list[AdvancedParserAdapter] | None = None,
        fallback_parser=None,
        ocr_enabled: bool = True,
        ocr_handler: OcrFallbackHandler | None = None,
    ) -> None:
        self.strategy = strategy
        self.fallback_parser = fallback_parser
        self.adapters = adapters if adapters is not None else _adapters_for_strategy(strategy)
        self.ocr = ocr_handler or OcrFallbackHandler(enabled=ocr_enabled)

    def parse(self, path: Path) -> ParseResult:
        attempts: list[dict[str, object]] = []
        best_degraded: AdvancedParseResult | None = None
        for adapter in self.adapters:
            try:
                can_parse = adapter.can_parse(path)
            except Exception as exc:
                attempts.append(
                    _failed_attempt(
                        adapter.parser_name,
                        DegradedReason.PARSER_ERROR.value,
                        ocr_enabled=self.ocr.enabled,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            if not can_parse:
                continue
            try:
                dependency_ready = adapter.check_dependencies()
            except Exception as exc:
                attempts.append(
                    _failed_attempt(
                        adapter.parser_name,
                        DegradedReason.MISSING_DEPENDENCY.value,
                        ocr_enabled=self.ocr.enabled,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            if not dependency_ready:
                attempts.append(
                    _failed_attempt(
                        adapter.parser_name,
                        DegradedReason.MISSING_DEPENDENCY.value,
                        status=ParserStatus.SKIP,
                        ocr_enabled=self.ocr.enabled,
                    )
                )
                continue
            try:
                result = adapter.parse(path)
            except Exception as exc:
                attempts.append(
                    _failed_attempt(
                        adapter.parser_name,
                        DegradedReason.PARSER_ERROR.value,
                        ocr_enabled=self.ocr.enabled,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            if result.status in {ParserStatus.HEALTHY, ParserStatus.DEGRADED}:
                result = self.ocr.apply_ocr_fallback(path, result)
            attempts.append(_advanced_attempt(result))
            if result.status in {ParserStatus.HEALTHY, ParserStatus.DEGRADED}:
                if result.extracted_text.strip():
                    return _to_parse_result(path, result, attempts, self.strategy)
                best_degraded = result
                attempts[-1]["degraded_reason"] = (
                    result.degraded_reason or DegradedReason.EMPTY_OUTPUT.value
                )

        if self.fallback_parser is not None:
            try:
                fallback = self.fallback_parser.parse(path)
            except Exception as exc:
                fallback_error = f"{type(exc).__name__}: {exc}"
                attempts.append(
                    _failed_attempt(
                        self.fallback_parser.parser_name,
                        DegradedReason.FALLBACK_PARSER_ERROR.value,
                        error=fallback_error,
                    )
                )
                result = best_degraded or self._direct_ocr_attempt(path, attempts)
                result = result or _unavailable_result(path, self.ocr.enabled)
                return _to_parse_result(
                    path,
                    result,
                    attempts,
                    self.strategy,
                    fallback_attempted=True,
                    fallback_parser=self.fallback_parser.parser_name,
                    fallback_error=fallback_error,
                )
            return ParseResult(
                extracted_text=fallback.extracted_text,
                content_hash=fallback.content_hash,
                mime_type=fallback.mime_type,
                parser_name=fallback.parser_name,
                metadata={
                    **fallback.metadata,
                    "advanced_parser": _advanced_parser_metadata(
                        strategy=self.strategy,
                        attempts=attempts,
                        selected_parser=fallback.parser_name,
                        fallback_used=True,
                        fallback_attempted=True,
                        fallback_parser=fallback.parser_name,
                        degraded_reason=(
                            best_degraded.degraded_reason
                            if best_degraded is not None
                            else DegradedReason.ADVANCED_PARSER_UNAVAILABLE.value
                        ),
                        result=best_degraded,
                    ),
                },
            )
        result = best_degraded or self._direct_ocr_attempt(path, attempts)
        result = result or _unavailable_result(path, self.ocr.enabled)
        return _to_parse_result(path, result, attempts, self.strategy)

    def _direct_ocr_attempt(
        self, path: Path, attempts: list[dict[str, object]]
    ) -> AdvancedParseResult | None:
        if not self.ocr.enabled or path.suffix.lower() != ".pdf":
            return None
        result = self.ocr.apply_ocr_fallback(
            path,
            _unavailable_result(path, self.ocr.enabled),
        )
        attempts.append(_advanced_attempt(result))
        return result


def _adapters_for_strategy(strategy: str) -> list[AdvancedParserAdapter]:
    normalized = strategy.casefold().replace("_", "-")
    if normalized == "docling":
        return [DoclingAdapter()]
    if normalized == "mineru":
        return [MinerUAdapter()]
    if normalized == "auto":
        return [DoclingAdapter(), MinerUAdapter()]
    raise ValueError("advanced_parser must be one of: auto, docling, mineru")


def _advanced_attempt(result: AdvancedParseResult) -> dict[str, object]:
    return {
        "parser": result.parser,
        "status": result.status.value,
        "degraded_reason": result.degraded_reason,
        "text_length": result.text_length,
        "page_or_slide_count": result.page_or_slide_count,
        **result_audit_metadata(result),
    }


def _failed_attempt(
    parser: str,
    degraded_reason: str,
    *,
    status: ParserStatus = ParserStatus.FAILURE,
    ocr_enabled: bool = False,
    error: str | None = None,
) -> dict[str, object]:
    return {
        "parser": parser,
        "status": status.value,
        "degraded_reason": degraded_reason,
        "text_length": 0,
        "page_or_slide_count": 0,
        **capability_metadata(
            parser_name=parser,
            parser_version=None,
            ocr_enabled=ocr_enabled,
        ),
        **({"error": error} if error else {}),
    }


def _unavailable_result(path: Path, ocr_enabled: bool) -> AdvancedParseResult:
    return AdvancedParseResult(
        format=path.suffix.lstrip(".").lower(),
        fixture_id=path.stem,
        parser="advanced.none",
        status=ParserStatus.DEGRADED,
        degraded_reason=DegradedReason.ADVANCED_PARSER_UNAVAILABLE.value,
        metadata=capability_metadata(
            parser_name="advanced.none",
            parser_version=None,
            ocr_enabled=ocr_enabled,
            ocr_failure_reason=DegradedReason.ADVANCED_PARSER_UNAVAILABLE.value,
            layout_degraded_reason=DegradedReason.ADVANCED_PARSER_UNAVAILABLE.value,
        ),
    )


def _to_parse_result(
    path: Path,
    result: AdvancedParseResult,
    attempts: list[dict[str, object]],
    strategy: str,
    *,
    fallback_attempted: bool = False,
    fallback_parser: str | None = None,
    fallback_error: str | None = None,
) -> ParseResult:
    raw_bytes = path.read_bytes()
    summary, redactions = sanitize_text_summary(result.extracted_text)
    status = "success" if result.status == ParserStatus.HEALTHY else "degraded"
    audit_metadata = result_audit_metadata(result)
    return ParseResult(
        extracted_text=result.extracted_text,
        content_hash=sha256(raw_bytes).hexdigest(),
        mime_type=_MIME_TYPES.get(path.suffix.lower(), "application/octet-stream"),
        parser_name=result.parser,
        metadata={
            "parser_id": f"parser.{result.parser}",
            "status": status,
            "extension": path.suffix.lower(),
            "char_count": len(result.extracted_text),
            "byte_count": len(raw_bytes),
            "text_summary": summary,
            "redaction_count": redactions,
            **audit_metadata,
            "page_or_slide_count": result.page_or_slide_count,
            "degraded_reason": result.degraded_reason,
            "advanced_parser": _advanced_parser_metadata(
                strategy=strategy,
                attempts=attempts,
                selected_parser=result.parser,
                fallback_used=False,
                fallback_attempted=fallback_attempted,
                fallback_parser=fallback_parser,
                fallback_error=fallback_error,
                degraded_reason=result.degraded_reason,
                result=result,
            ),
        },
    )


def _advanced_parser_metadata(
    *,
    strategy: str,
    attempts: list[dict[str, object]],
    selected_parser: str,
    fallback_used: bool,
    fallback_attempted: bool,
    degraded_reason: str | None,
    fallback_parser: str | None = None,
    fallback_error: str | None = None,
    result: AdvancedParseResult | None = None,
) -> dict[str, object]:
    audit_metadata = (
        result_audit_metadata(result)
        if result is not None
        else capability_metadata(parser_name=selected_parser, parser_version=None)
    )
    if result is None and attempts:
        audit_metadata.update(
            {
                "page_count": max(int(item.get("page_count", 0)) for item in attempts),
                "table_count": max(int(item.get("table_count", 0)) for item in attempts),
                "image_count": max(int(item.get("image_count", 0)) for item in attempts),
                "chart_count": max(int(item.get("chart_count", 0)) for item in attempts),
                "formula_count": max(int(item.get("formula_count", 0)) for item in attempts),
                "image_degraded_reason": _latest_attempt_value(attempts, "image_degraded_reason"),
                "chart_degraded_reason": _latest_attempt_value(attempts, "chart_degraded_reason"),
                "formula_degraded_reason": _latest_attempt_value(
                    attempts, "formula_degraded_reason"
                ),
                "ocr_enabled": any(bool(item.get("ocr_enabled")) for item in attempts),
                "ocr_applied": any(bool(item.get("ocr_applied")) for item in attempts),
                "ocr_failure_reason": _latest_attempt_value(attempts, "ocr_failure_reason"),
                "layout_aware": any(bool(item.get("layout_aware")) for item in attempts),
                "layout_source": _latest_attempt_value(attempts, "layout_source"),
                "layout_degraded_reason": _latest_attempt_value(attempts, "layout_degraded_reason"),
            }
        )
    if not audit_metadata["layout_aware"] and not audit_metadata["layout_degraded_reason"]:
        audit_metadata["layout_degraded_reason"] = degraded_reason or "layout_unavailable"
    return {
        "strategy": strategy,
        "selected_parser": selected_parser,
        "fallback_used": fallback_used,
        "fallback_attempted": fallback_attempted,
        "fallback_parser": fallback_parser,
        "fallback_error": fallback_error,
        "degraded_reason": degraded_reason,
        "attempts": attempts,
        **audit_metadata,
        "metadata": result.metadata if result is not None else {},
    }


def _latest_attempt_value(attempts: list[dict[str, object]], key: str) -> object | None:
    return next(
        (item.get(key) for item in reversed(attempts) if item.get(key)),
        None,
    )
