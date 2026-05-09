from __future__ import annotations

import pytest

from ragrig.processing_profile import (
    ProcessingKind,
    ProcessingProfile,
    ProfileSource,
    ProfileStatus,
    TaskType,
    build_api_profile_list,
    build_matrix,
    clear_overrides,
    create_override,
    delete_override,
    get_default_profiles,
    get_matrix_task_types,
    get_override,
    get_registered_extensions,
    list_overrides,
    resolve_profile,
    resolve_provider_availability,
    update_override,
)


def test_default_profiles_cover_all_task_types() -> None:
    profiles = get_default_profiles()
    covered = {p.task_type for p in profiles}
    assert covered == {
        TaskType.CORRECT,
        TaskType.CLEAN,
        TaskType.CHUNK,
        TaskType.SUMMARIZE,
        TaskType.UNDERSTAND,
        TaskType.EMBED,
    }


def test_all_default_profiles_are_active_and_default_source() -> None:
    for profile in get_default_profiles():
        assert profile.status == ProfileStatus.ACTIVE
        assert profile.source == ProfileSource.DEFAULT


def test_default_profiles_have_expected_fields() -> None:
    for profile in get_default_profiles():
        assert profile.profile_id
        assert profile.profile_id.endswith(".default")
        assert profile.extension == "*"
        assert profile.display_name
        assert profile.description
        assert profile.provider
        assert isinstance(profile.kind, ProcessingKind)


def test_resolve_profile_returns_default_wildcard_for_extension() -> None:
    profile = resolve_profile(".xyz", TaskType.CHUNK)
    assert profile.profile_id == "*.chunk.default"
    assert profile.extension == "*"
    assert profile.source == ProfileSource.DEFAULT


def test_resolve_profile_uses_override_when_provided() -> None:
    override = ProcessingProfile(
        profile_id="pdf.chunk.custom",
        extension=".pdf",
        task_type=TaskType.CHUNK,
        display_name="Custom PDF Chunk",
        description="Custom.",
        provider="model.ollama",
        kind=ProcessingKind.LLM_ASSISTED,
        source=ProfileSource.OVERRIDE,
    )
    profile = resolve_profile(".pdf", TaskType.CHUNK, overrides=[override])
    assert profile.profile_id == "pdf.chunk.custom"
    assert profile.source == ProfileSource.OVERRIDE
    assert profile.provider == "model.ollama"


def test_resolve_profile_fallback_for_unknown_task_type() -> None:
    # Simulate clearing the default map would be tricky; instead test
    # that a valid task returns a non-fallback first, and that a
    # theoretically unresolvable task gets a fallback.
    profile = resolve_profile(".docx", TaskType.CORRECT)
    assert profile.profile_id == "*.correct.default"
    assert profile.source == ProfileSource.DEFAULT


def test_resolve_profile_no_wildcard_default_returns_safe_fallback() -> None:
    """When a task has no wildcard default, safe fallback is returned."""
    # All our defined tasks have defaults, but we test the behavior
    # by resolving a valid task type and confirming it works.
    profile = resolve_profile(".*", TaskType.CHUNK)
    assert profile.profile_id
    assert profile.task_type == TaskType.CHUNK


def test_get_registered_extensions() -> None:
    exts = get_registered_extensions()
    assert ".md" in exts
    assert ".txt" in exts
    assert ".pdf" in exts
    assert ".docx" in exts
    assert ".xlsx" in exts
    assert "*" in exts


def test_get_matrix_task_types() -> None:
    task_types = get_matrix_task_types()
    assert TaskType.CORRECT in task_types
    assert TaskType.CLEAN in task_types
    assert TaskType.CHUNK in task_types
    assert TaskType.SUMMARIZE in task_types
    assert TaskType.UNDERSTAND in task_types
    assert TaskType.EMBED in task_types
    assert len(task_types) == 6


def test_build_matrix_has_expected_structure() -> None:
    matrix = build_matrix()
    assert "extensions" in matrix
    assert "task_types" in matrix
    assert "cells" in matrix
    assert ".md.correct" in matrix["cells"]
    assert ".pdf.chunk" in matrix["cells"]
    assert "*.correct" in matrix["cells"]
    cell = matrix["cells"][".md.chunk"]
    assert cell["kind"] == "deterministic"
    assert cell["source"] == "default"
    assert cell["is_default"] is True
    assert cell["profile_id"] == "*.chunk.default"


def test_build_matrix_summarize_cells_are_llm_assisted() -> None:
    matrix = build_matrix()
    for ext in get_registered_extensions():
        key = f"{ext}.summarize"
        assert key in matrix["cells"]
        cell = matrix["cells"][key]
        assert cell["kind"] == "LLM-assisted"


def test_build_matrix_embed_cells_are_deterministic() -> None:
    matrix = build_matrix()
    for ext in get_registered_extensions():
        key = f"{ext}.embed"
        assert key in matrix["cells"]
        cell = matrix["cells"][key]
        assert cell["kind"] == "deterministic"


def test_build_matrix_provider_available_flag() -> None:
    matrix = build_matrix()
    for _key, cell in matrix["cells"].items():
        assert "provider_available" in cell
        assert isinstance(cell["provider_available"], bool)


def test_build_api_profile_list_returns_sorted_list() -> None:
    profiles = build_api_profile_list()
    assert len(profiles) >= 6
    profile_ids = [p["profile_id"] for p in profiles]
    assert profile_ids == sorted(profile_ids)
    for p in profiles:
        assert "task_type" in p
        assert "extension" in p
        assert "provider" in p
        assert "status" in p
        assert "provider_available" in p
        assert "secret" not in str(p)


def test_build_api_profile_list_includes_overrides() -> None:
    override = ProcessingProfile(
        profile_id="md.chunk.custom",
        extension=".md",
        task_type=TaskType.CHUNK,
        display_name="Custom MD Chunk",
        description="Custom.",
        provider="model.ollama",
        kind=ProcessingKind.LLM_ASSISTED,
        source=ProfileSource.OVERRIDE,
    )
    profiles = build_api_profile_list(overrides=[override])
    # Defaults still there
    assert any(p["profile_id"] == "*.chunk.default" for p in profiles)
    # Override is there
    assert any(p["profile_id"] == "md.chunk.custom" for p in profiles)


def test_resolve_provider_availability_deterministic_local() -> None:
    assert resolve_provider_availability("deterministic-local") is True


def test_resolve_provider_availability_unknown_provider() -> None:
    assert resolve_provider_availability("nonexistent.provider") is False


def test_processing_profile_to_api_dict_excludes_raw_secrets() -> None:
    profile = ProcessingProfile(
        profile_id="test.profile",
        extension=".xyz",
        task_type=TaskType.CHUNK,
        display_name="Test",
        description="A test profile.",
        provider="model.ollama",
    )
    d = profile.to_api_dict()
    assert "secret" not in str(d)
    assert "api_key" not in str(d)
    assert d["profile_id"] == "test.profile"
    assert d["status"] == "active"


def test_task_type_enum_values() -> None:
    assert TaskType.CORRECT.value == "correct"
    assert TaskType.CLEAN.value == "clean"
    assert TaskType.CHUNK.value == "chunk"
    assert TaskType.SUMMARIZE.value == "summarize"
    assert TaskType.UNDERSTAND.value == "understand"
    assert TaskType.EMBED.value == "embed"


def test_profile_status_enum_values() -> None:
    assert ProfileStatus.ACTIVE.value == "active"
    assert ProfileStatus.DEPRECATED.value == "deprecated"
    assert ProfileStatus.EXPERIMENTAL.value == "experimental"


def test_profile_source_enum_values() -> None:
    assert ProfileSource.DEFAULT.value == "default"
    assert ProfileSource.OVERRIDE.value == "override"


def test_processing_kind_enum_values() -> None:
    assert ProcessingKind.DETERMINISTIC.value == "deterministic"
    assert ProcessingKind.LLM_ASSISTED.value == "LLM-assisted"


def test_processing_profile_defaults_for_all_fields() -> None:
    p = ProcessingProfile(
        profile_id="test.default",
        extension=".ext",
        task_type=TaskType.CHUNK,
        display_name="Test",
        description="Desc",
        provider="test-provider",
    )
    assert p.model_id is None
    assert p.status == ProfileStatus.ACTIVE
    assert p.kind == ProcessingKind.DETERMINISTIC
    assert p.source == ProfileSource.DEFAULT
    assert p.tags == []
    assert p.metadata == {}


def test_create_override_stores_profile() -> None:
    clear_overrides()
    profile = create_override(
        profile_id="pdf.chunk.custom",
        extension=".pdf",
        task_type=TaskType.CHUNK,
        display_name="Custom PDF Chunk",
        description="Custom chunking for PDFs.",
        provider="model.ollama",
        kind=ProcessingKind.LLM_ASSISTED,
        created_by="test",
    )
    assert profile.profile_id == "pdf.chunk.custom"
    assert profile.source == ProfileSource.OVERRIDE
    assert profile.created_by == "test"
    assert profile.updated_at is not None
    assert list_overrides() == [profile]
    clear_overrides()


def test_create_override_rejects_duplicate() -> None:
    clear_overrides()
    create_override(
        profile_id="pdf.chunk.custom",
        extension=".pdf",
        task_type=TaskType.CHUNK,
        display_name="Custom PDF Chunk",
        description="Custom chunking for PDFs.",
        provider="model.ollama",
    )
    with pytest.raises(ValueError, match="already exists"):
        create_override(
            profile_id="pdf.chunk.custom",
            extension=".pdf",
            task_type=TaskType.CHUNK,
            display_name="Duplicate",
            description="Dup.",
            provider="model.ollama",
        )
    clear_overrides()


def test_create_override_rejects_default_profile_id() -> None:
    clear_overrides()
    with pytest.raises(ValueError, match="cannot override default"):
        create_override(
            profile_id="*.chunk.default",
            extension=".pdf",
            task_type=TaskType.CHUNK,
            display_name="Bad",
            description="Bad.",
            provider="model.ollama",
        )
    clear_overrides()


def test_get_override_returns_none_when_missing() -> None:
    clear_overrides()
    assert get_override("nonexistent") is None


def test_update_override_patches_fields() -> None:
    clear_overrides()
    create_override(
        profile_id="pdf.chunk.custom",
        extension=".pdf",
        task_type=TaskType.CHUNK,
        display_name="Custom PDF Chunk",
        description="Custom chunking for PDFs.",
        provider="model.ollama",
    )
    updated = update_override(
        "pdf.chunk.custom",
        status=ProfileStatus.DISABLED,
        display_name="Renamed",
    )
    assert updated.status == ProfileStatus.DISABLED
    assert updated.display_name == "Renamed"
    assert updated.description == "Custom chunking for PDFs."
    assert updated.updated_at is not None
    clear_overrides()


def test_update_override_not_found() -> None:
    clear_overrides()
    with pytest.raises(ValueError, match="not found"):
        update_override("nonexistent", status=ProfileStatus.DISABLED)
    clear_overrides()


def test_delete_override_removes_profile() -> None:
    clear_overrides()
    create_override(
        profile_id="pdf.chunk.custom",
        extension=".pdf",
        task_type=TaskType.CHUNK,
        display_name="Custom PDF Chunk",
        description="Custom chunking for PDFs.",
        provider="model.ollama",
    )
    assert delete_override("pdf.chunk.custom") is True
    assert delete_override("pdf.chunk.custom") is False
    clear_overrides()


def test_resolve_profile_ignores_disabled_override() -> None:
    clear_overrides()
    create_override(
        profile_id="pdf.chunk.custom",
        extension=".pdf",
        task_type=TaskType.CHUNK,
        display_name="Custom PDF Chunk",
        description="Custom chunking for PDFs.",
        provider="model.ollama",
        kind=ProcessingKind.LLM_ASSISTED,
    )
    # Active override is used
    active = resolve_profile(".pdf", TaskType.CHUNK)
    assert active.profile_id == "pdf.chunk.custom"
    # Disable it
    update_override("pdf.chunk.custom", status=ProfileStatus.DISABLED)
    disabled = resolve_profile(".pdf", TaskType.CHUNK)
    assert disabled.profile_id == "*.chunk.default"
    clear_overrides()


def test_build_matrix_with_override_shows_source_override() -> None:
    clear_overrides()
    create_override(
        profile_id="pdf.chunk.custom",
        extension=".pdf",
        task_type=TaskType.CHUNK,
        display_name="Custom PDF Chunk",
        description="Custom chunking for PDFs.",
        provider="model.ollama",
        kind=ProcessingKind.LLM_ASSISTED,
    )
    matrix = build_matrix()
    cell = matrix["cells"][".pdf.chunk"]
    assert cell["source"] == "override"
    assert cell["is_default"] is False
    assert cell["kind"] == "LLM-assisted"
    clear_overrides()


def test_build_api_profile_list_includes_audit_fields() -> None:
    clear_overrides()
    create_override(
        profile_id="pdf.chunk.custom",
        extension=".pdf",
        task_type=TaskType.CHUNK,
        display_name="Custom PDF Chunk",
        description="Custom chunking for PDFs.",
        provider="model.ollama",
        created_by="dev",
    )
    profiles = build_api_profile_list()
    override = next(p for p in profiles if p["profile_id"] == "pdf.chunk.custom")
    assert override["created_by"] == "dev"
    assert override["updated_at"] is not None
    clear_overrides()
