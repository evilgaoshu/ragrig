from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class TaskType(StrEnum):
    CORRECT = "correct"
    CLEAN = "clean"
    CHUNK = "chunk"
    SUMMARIZE = "summarize"
    UNDERSTAND = "understand"
    EMBED = "embed"


class ProfileStatus(StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    EXPERIMENTAL = "experimental"


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
            "metadata": self.metadata,
        }


__all__ = [
    "ProcessingKind",
    "ProcessingProfile",
    "ProfileSource",
    "ProfileStatus",
    "TaskType",
]
