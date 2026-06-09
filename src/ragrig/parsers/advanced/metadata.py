from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

from ragrig.parsers.advanced.models import AdvancedParseResult


def package_version(*distribution_names: str) -> str | None:
    for distribution_name in distribution_names:
        try:
            return version(distribution_name)
        except PackageNotFoundError:
            continue
    return None


def capability_metadata(
    *,
    parser_name: str,
    parser_version: str | None,
    page_count: int = 0,
    table_count: int = 0,
    image_count: int = 0,
    chart_count: int = 0,
    formula_count: int = 0,
    image_degraded_reason: str | None = None,
    chart_degraded_reason: str | None = None,
    formula_degraded_reason: str | None = None,
    ocr_enabled: bool = False,
    ocr_applied: bool = False,
    ocr_failure_reason: str | None = None,
    layout_aware: bool = False,
    layout_source: str | None = None,
    layout_degraded_reason: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "parser_name": parser_name,
        "parser_version": parser_version,
        "page_count": page_count,
        "table_count": table_count,
        "image_count": image_count,
        "chart_count": chart_count,
        "formula_count": formula_count,
        "image_degraded_reason": image_degraded_reason,
        "chart_degraded_reason": chart_degraded_reason,
        "formula_degraded_reason": formula_degraded_reason,
        "ocr_enabled": ocr_enabled,
        "ocr_applied": ocr_applied,
        "ocr_failure_reason": ocr_failure_reason,
        "layout_aware": layout_aware,
        "layout_source": layout_source,
        "layout_degraded_reason": layout_degraded_reason,
        **extra,
    }


def result_audit_metadata(result: AdvancedParseResult) -> dict[str, Any]:
    metadata = result.metadata
    return {
        "parser_name": metadata.get("parser_name", result.parser),
        "parser_version": metadata.get("parser_version"),
        "page_count": metadata.get("page_count", result.page_or_slide_count),
        "table_count": metadata.get("table_count", result.table_count),
        "image_count": metadata.get("image_count", 0),
        "chart_count": metadata.get("chart_count", 0),
        "formula_count": metadata.get("formula_count", 0),
        "image_degraded_reason": metadata.get("image_degraded_reason"),
        "chart_degraded_reason": metadata.get("chart_degraded_reason"),
        "formula_degraded_reason": metadata.get("formula_degraded_reason"),
        "ocr_enabled": metadata.get("ocr_enabled", False),
        "ocr_applied": metadata.get("ocr_applied", False),
        "ocr_failure_reason": metadata.get("ocr_failure_reason"),
        "layout_aware": metadata.get("layout_aware", False),
        "layout_source": metadata.get("layout_source"),
        "layout_degraded_reason": metadata.get("layout_degraded_reason"),
    }
