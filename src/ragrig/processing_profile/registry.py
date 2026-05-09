from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ragrig.processing_profile.models import (
    ProcessingKind,
    ProcessingProfile,
    ProfileSource,
    ProfileStatus,
    TaskType,
)


def _build_default_profiles() -> list[ProcessingProfile]:
    base_tags = ["default", "wildcard"]
    profiles: list[ProcessingProfile] = []

    profiles.append(
        ProcessingProfile(
            profile_id="*.correct.default",
            extension="*",
            task_type=TaskType.CORRECT,
            display_name="Default Correct (no-op)",
            description="Passes content through unchanged (deterministic no-op).",
            provider="deterministic-local",
            status=ProfileStatus.ACTIVE,
            kind=ProcessingKind.DETERMINISTIC,
            source=ProfileSource.DEFAULT,
            tags=base_tags + ["no-op"],
        )
    )

    profiles.append(
        ProcessingProfile(
            profile_id="*.clean.default",
            extension="*",
            task_type=TaskType.CLEAN,
            display_name="Default Clean (deterministic)",
            description="Normalize whitespace and strip trailing blank lines.",
            provider="deterministic-local",
            status=ProfileStatus.ACTIVE,
            kind=ProcessingKind.DETERMINISTIC,
            source=ProfileSource.DEFAULT,
            tags=base_tags + ["no-op"],
        )
    )

    profiles.append(
        ProcessingProfile(
            profile_id="*.chunk.default",
            extension="*",
            task_type=TaskType.CHUNK,
            display_name="Default Chunk (character-window)",
            description="Character-window chunking with configurable size and overlap.",
            provider="deterministic-local",
            status=ProfileStatus.ACTIVE,
            kind=ProcessingKind.DETERMINISTIC,
            source=ProfileSource.DEFAULT,
            tags=base_tags + ["char-window"],
        )
    )

    profiles.append(
        ProcessingProfile(
            profile_id="*.summarize.default",
            extension="*",
            task_type=TaskType.SUMMARIZE,
            display_name="Default Summarize (LLM-assisted)",
            description="LLM-assisted summarization (requires available LLM provider).",
            provider="model.ollama",
            status=ProfileStatus.ACTIVE,
            kind=ProcessingKind.LLM_ASSISTED,
            source=ProfileSource.DEFAULT,
            tags=base_tags + ["llm-required"],
        )
    )

    profiles.append(
        ProcessingProfile(
            profile_id="*.understand.default",
            extension="*",
            task_type=TaskType.UNDERSTAND,
            display_name="Default Understand (LLM-assisted)",
            description="LLM-assisted document understanding (requires available LLM provider).",
            provider="model.ollama",
            status=ProfileStatus.ACTIVE,
            kind=ProcessingKind.LLM_ASSISTED,
            source=ProfileSource.DEFAULT,
            tags=base_tags + ["llm-required"],
        )
    )

    profiles.append(
        ProcessingProfile(
            profile_id="*.embed.default",
            extension="*",
            task_type=TaskType.EMBED,
            display_name="Default Embed (deterministic)",
            description="Deterministic hash-based embedding for smoke/CI.",
            provider="deterministic-local",
            model_id="hash-8d",
            status=ProfileStatus.ACTIVE,
            kind=ProcessingKind.DETERMINISTIC,
            source=ProfileSource.DEFAULT,
            tags=base_tags,
        )
    )

    return profiles


def _unique_profile_map(profiles: list[ProcessingProfile]) -> dict[str, ProcessingProfile]:
    seen: dict[str, ProcessingProfile] = {}
    for profile in profiles:
        seen[profile.profile_id] = profile
    return seen


DEFAULT_PROFILES: list[ProcessingProfile] = _build_default_profiles()

_DEFAULT_MAP: dict[str, ProcessingProfile] = _unique_profile_map(DEFAULT_PROFILES)

# In-memory override store (no DB persistence in MVP)
_OVERRIDE_STORE: dict[str, ProcessingProfile] = {}


def get_default_profiles() -> list[ProcessingProfile]:
    return DEFAULT_PROFILES


def list_overrides() -> list[ProcessingProfile]:
    """Return all stored override profiles."""
    return list(_OVERRIDE_STORE.values())


def get_override(profile_id: str) -> ProcessingProfile | None:
    """Return a single override profile by ID."""
    return _OVERRIDE_STORE.get(profile_id)


def create_override(
    *,
    profile_id: str,
    extension: str,
    task_type: TaskType,
    display_name: str,
    description: str,
    provider: str,
    model_id: str | None = None,
    kind: ProcessingKind = ProcessingKind.DETERMINISTIC,
    tags: list[str] | None = None,
    metadata: dict[str, object] | None = None,
    created_by: str | None = None,
) -> ProcessingProfile:
    """Create and store an override profile."""
    if profile_id in _OVERRIDE_STORE:
        raise ValueError(f"override profile '{profile_id}' already exists")
    if profile_id in _DEFAULT_MAP:
        raise ValueError(f"cannot override default profile '{profile_id}'")
    now = datetime.now(timezone.utc)
    profile = ProcessingProfile(
        profile_id=profile_id,
        extension=extension,
        task_type=task_type,
        display_name=display_name,
        description=description,
        provider=provider,
        model_id=model_id,
        status=ProfileStatus.ACTIVE,
        kind=kind,
        source=ProfileSource.OVERRIDE,
        tags=tags or [],
        metadata=metadata or {},
        created_by=created_by,
        updated_at=now,
    )
    _OVERRIDE_STORE[profile_id] = profile
    return profile


def update_override(
    profile_id: str,
    *,
    status: ProfileStatus | None = None,
    display_name: str | None = None,
    description: str | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    kind: ProcessingKind | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, object] | None = None,
) -> ProcessingProfile:
    """Patch an existing override profile."""
    existing = _OVERRIDE_STORE.get(profile_id)
    if existing is None:
        raise ValueError(f"override profile '{profile_id}' not found")
    now = datetime.now(timezone.utc)
    profile = ProcessingProfile(
        profile_id=existing.profile_id,
        extension=existing.extension,
        task_type=existing.task_type,
        display_name=display_name if display_name is not None else existing.display_name,
        description=description if description is not None else existing.description,
        provider=provider if provider is not None else existing.provider,
        model_id=model_id if model_id is not None else existing.model_id,
        status=status if status is not None else existing.status,
        kind=kind if kind is not None else existing.kind,
        source=ProfileSource.OVERRIDE,
        tags=tags if tags is not None else existing.tags,
        metadata=metadata if metadata is not None else existing.metadata,
        created_by=existing.created_by,
        updated_at=now,
    )
    _OVERRIDE_STORE[profile_id] = profile
    return profile


def delete_override(profile_id: str) -> bool:
    """Delete an override profile. Returns True if deleted, False if not found."""
    if profile_id in _OVERRIDE_STORE:
        del _OVERRIDE_STORE[profile_id]
        return True
    return False


def clear_overrides() -> None:
    """Clear all override profiles. Intended for tests."""
    _OVERRIDE_STORE.clear()


def resolve_profile(
    extension: str,
    task_type: TaskType,
    *,
    overrides: list[ProcessingProfile] | None = None,
) -> ProcessingProfile:
    """Resolve a processing profile for (extension, task_type).

    Resolution strategy:
    1. Exact match: {extension}.{task_type} from overrides.
    2. Wildcard match: *.{task_type} from defaults.
    3. Safe fallback: a no-op deterministic profile.
    """
    active_overrides = overrides if overrides is not None else list_overrides()
    for profile in active_overrides:
        if (
            profile.extension == extension
            and profile.task_type == task_type
            and profile.status != ProfileStatus.DISABLED
        ):
            return profile
    wildcard_key = f"*.{task_type.value}.default"
    wildcard = _DEFAULT_MAP.get(wildcard_key)
    if wildcard is not None:
        return wildcard
    # Safe fallback for defense-in-depth; covered via contract validation, not unit test
    return ProcessingProfile(  # pragma: no cover
        profile_id=f"*.{task_type.value}.fallback",
        extension="*",
        task_type=task_type,
        display_name=f"Fallback {task_type.value} (no-op)",
        description=f"Safe no-op fallback for {task_type.value}.",
        provider="deterministic-local",
        status=ProfileStatus.ACTIVE,
        kind=ProcessingKind.DETERMINISTIC,
        source=ProfileSource.DEFAULT,
        tags=["fallback", "no-op"],
    )


def resolve_provider_availability(provider_name: str) -> bool:
    """Check whether a provider is available at the registry level.

    Returns True if the provider appears ready, False otherwise.
    Providers that are name-only stubs (cloud) are NOT considered available.
    """
    if provider_name == "deterministic-local":
        return True
    try:
        from ragrig.plugins import get_plugin_registry  # pragma: no cover - branch body

        discovery_by_id = {  # pragma: no cover - branch body
            item["plugin_id"]: item for item in get_plugin_registry().list_discovery()
        }
        entry = discovery_by_id.get(provider_name)
        if entry is None:
            return False
        return entry.get("status") == "ready"
    except ImportError:  # pragma: no cover - defense-in-depth for missing plugin deps
        return False  # pragma: no cover


def get_registered_extensions() -> list[str]:
    """Return the canonical set of extensions for matrix display."""
    return [".md", ".txt", ".pdf", ".docx", ".xlsx", "*"]


def get_matrix_task_types() -> list[TaskType]:
    """Return the task types for matrix display."""
    return [
        TaskType.CORRECT,
        TaskType.CLEAN,
        TaskType.CHUNK,
        TaskType.SUMMARIZE,
        TaskType.UNDERSTAND,
        TaskType.EMBED,
    ]


def build_matrix(
    overrides: list[ProcessingProfile] | None = None,
) -> dict[str, Any]:
    """Build a processing profile matrix for API/console rendering.

    Returns a dict with extensions, task_types, and cells keyed by 'extension.task_type'.
    """
    extensions = get_registered_extensions()
    task_types = get_matrix_task_types()
    active_overrides = overrides if overrides is not None else list_overrides()
    cells: dict[str, dict[str, object]] = {}
    for ext in extensions:
        for tt in task_types:
            profile = resolve_profile(ext, tt, overrides=active_overrides)
            is_default = profile.source == ProfileSource.DEFAULT
            provider_available = resolve_provider_availability(profile.provider)
            cells[f"{ext}.{tt.value}"] = {
                "profile_id": profile.profile_id,
                "extension": ext,
                "task_type": tt.value,
                "display_name": profile.display_name,
                "description": profile.description,
                "provider": profile.provider,
                "model_id": profile.model_id,
                "status": profile.status.value,
                "kind": profile.kind.value,
                "source": profile.source.value,
                "is_default": is_default,
                "provider_available": provider_available,
            }
    return {
        "extensions": extensions,
        "task_types": [tt.value for tt in task_types],
        "cells": cells,
    }


def build_api_profile_list(
    overrides: list[ProcessingProfile] | None = None,
) -> list[dict[str, object]]:
    """Build the API representation of all profiles (defaults + overrides)."""
    profiles: dict[str, ProcessingProfile] = dict(_DEFAULT_MAP)
    active_overrides = overrides if overrides is not None else list_overrides()
    for profile in active_overrides:
        profiles[profile.profile_id] = profile

    result: list[dict[str, object]] = []
    for profile_id in sorted(profiles):
        profile = profiles[profile_id]
        available = resolve_provider_availability(profile.provider)
        entry = profile.to_api_dict()
        entry["provider_available"] = available
        result.append(entry)
    return result


__all__ = [
    "DEFAULT_PROFILES",
    "build_api_profile_list",
    "build_matrix",
    "clear_overrides",
    "create_override",
    "delete_override",
    "get_default_profiles",
    "get_matrix_task_types",
    "get_override",
    "get_registered_extensions",
    "list_overrides",
    "resolve_profile",
    "resolve_provider_availability",
    "update_override",
]
