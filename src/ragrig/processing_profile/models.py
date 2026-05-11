from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


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
        return {
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
            "metadata": _sanitize_metadata(self.metadata),
            "created_by": self.created_by,
            "updated_at": self.updated_at.isoformat() if self.updated_at is not None else None,
        }


_SECRET_KEY_PARTS = (
    "api_key",
    "access_key",
    "secret",
    "session_token",
    "token",
    "password",
    "private_key",
    "credential",
    "dsn",
    "service_account",
)

_SENSITIVE_VALUE_PREFIXES: tuple[str, ...] = (
    "bearer ",
    "-----begin",
)

_DEFAULT_MAX_DEPTH = 100


def _is_sensitive_key(key: object) -> bool:
    """Return True if *key* contains any known sensitive key part.

    Non-string keys are treated as non-sensitive to avoid ``AttributeError``.
    """
    if not isinstance(key, str):
        return False
    key_lower = key.lower()
    return any(part in key_lower for part in _SECRET_KEY_PARTS)


def _is_sensitive_value(value: object) -> bool:
    if not isinstance(value, str):
        return False
    value_lower = value.lower()
    return any(pattern in value_lower for pattern in _SENSITIVE_VALUE_PREFIXES)


def _sanitize_metadata(
    metadata: dict[str, object],
    max_depth: int = _DEFAULT_MAX_DEPTH,
    current_depth: int = 0,
) -> dict[str, object]:
    """Recursively redact sensitive keys/values from metadata for API responses."""
    if current_depth >= max_depth:
        return {}

    sanitized: dict[str, object] = {}
    next_depth = current_depth + 1

    for key, value in metadata.items():
        if _is_sensitive_key(key):
            continue
        if isinstance(value, dict):
            sanitized[key] = _sanitize_metadata(
                value, max_depth=max_depth, current_depth=next_depth
            )
        elif isinstance(value, list):
            sanitized[key] = _sanitize_metadata_list(
                value, max_depth=max_depth, current_depth=next_depth
            )
        elif _is_sensitive_value(value):
            continue
        else:
            sanitized[key] = value
    return sanitized


def _sanitize_metadata_list(
    items: list[object],
    max_depth: int = _DEFAULT_MAX_DEPTH,
    current_depth: int = 0,
) -> list[object]:
    if current_depth >= max_depth:
        return []

    sanitized: list[object] = []
    next_depth = current_depth + 1

    for item in items:
        if isinstance(item, dict):
            sanitized.append(
                _sanitize_metadata(item, max_depth=max_depth, current_depth=next_depth)
            )
        elif isinstance(item, list):
            sanitized.append(
                _sanitize_metadata_list(item, max_depth=max_depth, current_depth=next_depth)
            )
        elif _is_sensitive_value(item):
            continue
        else:
            sanitized.append(item)
    return sanitized


__all__ = [
    "ProcessingKind",
    "ProcessingProfile",
    "ProfileSource",
    "ProfileStatus",
    "TaskType",
]
