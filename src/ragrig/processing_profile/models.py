from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from ragrig.processing_profile.sanitizer import (
    SanitizationSummary,
    remove_metadata,
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
        # Always include the structured summary for cross-layer contract
        # consistency.  The summary is safe to return even when zero because
        # it never contains raw secret values, full original text, or large
        # field values.
        result["_sanitization_summary"] = summary.to_dict()
        return result


_DEFAULT_MAX_DEPTH = 100


def _sanitize_metadata(
    metadata: dict[str, object],
    max_depth: int = _DEFAULT_MAX_DEPTH,
    current_depth: int = 0,
) -> tuple[dict[str, object], SanitizationSummary]:
    """Recursively remove sensitive keys/values from metadata for API responses.

    Thin wrapper around the shared ``remove_metadata`` helper to prevent
    thin-wrapper drift between the model layer and the canonical sanitizer.

    Returns ``(sanitized_dict, summary)``.
    """
    # current_depth is accepted for backward compatibility with any internal
    # callers that might pass it, but the shared implementation tracks depth
    # internally.  We ignore current_depth here because remove_metadata starts
    # fresh at depth 0, which is the correct behaviour for top-level API
    # sanitization.
    del current_depth
    return remove_metadata(metadata, max_depth=max_depth)


__all__ = [
    "ProcessingKind",
    "ProcessingProfile",
    "ProfileSource",
    "ProfileStatus",
    "TaskType",
]
