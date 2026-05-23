from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from ragrig.parsers.advanced.adapter import AdvancedParserAdapter
from ragrig.parsers.advanced.docling import DoclingAdapter
from ragrig.parsers.advanced.mineru import MinerUAdapter
from ragrig.parsers.advanced.models import AdvancedParseResult, ParserStatus
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
    ) -> None:
        self.strategy = strategy
        self.fallback_parser = fallback_parser
        self.adapters = adapters if adapters is not None else _adapters_for_strategy(strategy)

    def parse(self, path: Path) -> ParseResult:
        attempts: list[dict[str, object]] = []
        for adapter in self.adapters:
            if not adapter.can_parse(path):
                continue
            dependency_ready = adapter.check_dependencies()
            if not dependency_ready:
                attempts.append(
                    {
                        "parser": adapter.parser_name,
                        "status": ParserStatus.SKIP.value,
                        "degraded_reason": "missing_dependency",
                    }
                )
                continue
            result = adapter.parse(path)
            attempts.append(_advanced_attempt(result))
            if result.status in {ParserStatus.HEALTHY, ParserStatus.DEGRADED}:
                if result.extracted_text.strip():
                    return _to_parse_result(path, result, attempts, self.strategy)
                attempts[-1]["degraded_reason"] = result.degraded_reason or "empty_output"
                continue

        if self.fallback_parser is not None:
            fallback = self.fallback_parser.parse(path)
            return ParseResult(
                extracted_text=fallback.extracted_text,
                content_hash=fallback.content_hash,
                mime_type=fallback.mime_type,
                parser_name=fallback.parser_name,
                metadata={
                    **fallback.metadata,
                    "advanced_parser": {
                        "strategy": self.strategy,
                        "fallback_used": True,
                        "attempts": attempts,
                    },
                },
            )
        attempted = ", ".join(str(item["parser"]) for item in attempts) or self.strategy
        raise ValueError(f"advanced parser unavailable for {path.name}: {attempted}")


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
        "table_count": result.table_count,
        "page_or_slide_count": result.page_or_slide_count,
    }


def _to_parse_result(
    path: Path,
    result: AdvancedParseResult,
    attempts: list[dict[str, object]],
    strategy: str,
) -> ParseResult:
    raw_bytes = path.read_bytes()
    summary, redactions = sanitize_text_summary(result.extracted_text)
    status = "success" if result.status == ParserStatus.HEALTHY else "degraded"
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
            "table_count": result.table_count,
            "page_or_slide_count": result.page_or_slide_count,
            "degraded_reason": result.degraded_reason,
            "advanced_parser": {
                "strategy": strategy,
                "fallback_used": False,
                "attempts": attempts,
                "metadata": result.metadata,
            },
        },
    )
