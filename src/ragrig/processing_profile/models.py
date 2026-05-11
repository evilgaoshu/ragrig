from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from ragrig.processing_profile.sanitizer import (
    SanitizationSummary,
    is_sensitive_key,
    is_sensitive_value,
)


class TaskType(StrEnum):
    CORRECT = "correct"
    CLEAN = "clean"
    CHUNK = "chunk"
    SUMMARIZE = "summarize"
    UNDERSTAND = "understand"
    EMBED = "embed"
    ANSWER = "answer"


class ProfileStatus(StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    EXPERIMENTAL = "experimental"
    DISABLED = "disabled"


class ProfileSource(StrEnum):
    DEFAULT = "default"
    OVERRIDE = "override"


class ProcessingKind(StrEnum):
    DETERMINISTIC = "deterministic"
    LLM_ASSISTED = "LLM-assisted"


@dataclass(frozen=True)
class ProcessingProfile:
    profile_id: str
    extension: str
    task_type: TaskType
    display_name: str
    description: str
    provider: str
    model_id: str | None = None
    status: ProfileStatus = ProfileStatus.ACTIVE
    kind: ProcessingKind = ProcessingKind.DETERMINISTIC
    source: ProfileSource = ProfileSource.DEFAULT
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)
    created_by: str | None = None
    updated_at: datetime | None = None

    def to_api_dict(self) -> dict[str, object]:
        metadata_sanitized, summary = _sanitize_metadata(self.metadata)
        result: dict[str, object] = {
            "profile_id": self.profile_id,
            "extension": self.extension,
            "task_type": self.task_type.value,
            "display_name": self.display_name,
            "description": self.description,
            "provider": self.provider,
            "model_id": self.model_id,
            "status": self.status.value,
            "kind": self.kind.value,
            "source": self.source.value,
            "tags": self.tags,
            "metadata": metadata_sanitized,
            "created_by": self.created_by,
            "updated_at": self.updated_at.isoformat() if self.updated_at is not None else None,
        }
        # Include summary when there is any degradation to avoid false positives
        # for clean metadata while providing observability for actual issues.
        if (
            summary.redacted_count
            or summary.removed_count
            or summary.degraded_count
            or summary.non_string_key_count
            or summary.max_depth_exceeded
        ):
            result["_sanitization_summary"] = summary.to_dict()
        return result


_DEFAULT_MAX_DEPTH = 100


def _sanitize_metadata(
    metadata: dict[str, object],
    max_depth: int = _DEFAULT_MAX_DEPTH,
    current_depth: int = 0,
) -> tuple[dict[str, object], SanitizationSummary]:
    """Recursively remove sensitive keys/values from metadata for API responses.

    Returns ``(sanitized_dict, summary)``.
    """
    summary = SanitizationSummary()
    if current_depth >= max_depth:
        return {}, summary

    sanitized: dict[str, object] = {}
    next_depth = current_depth + 1

    for key, value in metadata.items():
        if not isinstance(key, str):
            summary = SanitizationSummary(
                schema_version=summary.schema_version,
                redacted_count=summary.redacted_count,
                removed_count=summary.removed_count,
                degraded_count=summary.degraded_count,
                non_string_key_count=summary.non_string_key_count + 1,
                max_depth_exceeded=summary.max_depth_exceeded,
            )
        if is_sensitive_key(key):
            summary = SanitizationSummary(
                schema_version=summary.schema_version,
                redacted_count=summary.redacted_count,
                removed_count=summary.removed_count + 1,
                degraded_count=summary.degraded_count,
                non_string_key_count=summary.non_string_key_count,
                max_depth_exceeded=summary.max_depth_exceeded,
            )
            continue
        if isinstance(value, dict):
            sub, sub_summary = _sanitize_metadata(
                value, max_depth=max_depth, current_depth=next_depth
            )
            sanitized[key] = sub
            summary = _merge_summary(summary, sub_summary)
        elif isinstance(value, list):
            sub, sub_summary = _sanitize_metadata_list(
                value, max_depth=max_depth, current_depth=next_depth
            )
            sanitized[key] = sub
            summary = _merge_summary(summary, sub_summary)
        elif is_sensitive_value(value):
            summary = SanitizationSummary(
                schema_version=summary.schema_version,
                redacted_count=summary.redacted_count,
                removed_count=summary.removed_count + 1,
                degraded_count=summary.degraded_count,
                non_string_key_count=summary.non_string_key_count,
                max_depth_exceeded=summary.max_depth_exceeded,
            )
            continue
        else:
            sanitized[key] = value
    return sanitized, summary


def _sanitize_metadata_list(
    items: list[object],
    max_depth: int = _DEFAULT_MAX_DEPTH,
    current_depth: int = 0,
) -> tuple[list[object], SanitizationSummary]:
    summary = SanitizationSummary()
    if current_depth >= max_depth:
        return [], summary

    sanitized: list[object] = []
    next_depth = current_depth + 1

    for item in items:
        if isinstance(item, dict):
            sub, sub_summary = _sanitize_metadata(
                item, max_depth=max_depth, current_depth=next_depth
            )
            sanitized.append(sub)
            summary = _merge_summary(summary, sub_summary)
        elif isinstance(item, list):
            sub, sub_summary = _sanitize_metadata_list(
                item, max_depth=max_depth, current_depth=next_depth
            )
            sanitized.append(sub)
            summary = _merge_summary(summary, sub_summary)
        elif is_sensitive_value(item):
            summary = SanitizationSummary(
                schema_version=summary.schema_version,
                redacted_count=summary.redacted_count,
                removed_count=summary.removed_count + 1,
                degraded_count=summary.degraded_count,
                non_string_key_count=summary.non_string_key_count,
                max_depth_exceeded=summary.max_depth_exceeded,
            )
            continue
        else:
            sanitized.append(item)
    return sanitized, summary


def _merge_summary(a: SanitizationSummary, b: SanitizationSummary) -> SanitizationSummary:
    return SanitizationSummary(
        schema_version=a.schema_version,
        redacted_count=a.redacted_count + b.redacted_count,
        removed_count=a.removed_count + b.removed_count,
        degraded_count=a.degraded_count + b.degraded_count,
        non_string_key_count=a.non_string_key_count + b.non_string_key_count,
        max_depth_exceeded=a.max_depth_exceeded or b.max_depth_exceeded,
    )


__all__ = [
    "ProcessingKind",
    "ProcessingProfile",
    "ProfileSource",
    "ProfileStatus",
    "TaskType",
]
