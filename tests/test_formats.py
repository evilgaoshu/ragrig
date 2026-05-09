from __future__ import annotations

from ragrig.formats.model import FormatStatus, SupportedFormat
from ragrig.formats.registry import SupportedFormatRegistry


def test_registry_with_explicit_format_list() -> None:
    """Test creating a registry with explicit format list."""
    formats = [
        SupportedFormat(
            extension=".test",
            mime_type="application/x-test",
            display_name="Test Format (.test)",
            parser_id="parser.test",
            status=FormatStatus.SUPPORTED,
        ),
        SupportedFormat(
            extension=".plan",
            mime_type="application/x-plan",
            display_name="Plan Format (.plan)",
            parser_id="parser.plan",
            status=FormatStatus.PLANNED,
            limitations="Not ready yet.",
        ),
        SupportedFormat(
            extension=".prev",
            mime_type="application/x-prev",
            display_name="Prev Format (.prev)",
            parser_id="parser.prev",
            status=FormatStatus.PREVIEW,
            limitations="May be unstable.",
        ),
    ]
    registry = SupportedFormatRegistry(formats=formats)

    # list all
    all_formats = registry.list()
    assert len(all_formats) == 3
    assert all_formats[0].status == FormatStatus.SUPPORTED
    assert all_formats[1].status == FormatStatus.PREVIEW
    assert all_formats[2].status == FormatStatus.PLANNED

    # list by status
    supported = registry.list(status=FormatStatus.SUPPORTED)
    assert len(supported) == 1
    assert supported[0].extension == ".test"

    planned = registry.list(status=FormatStatus.PLANNED)
    assert len(planned) == 1
    assert planned[0].extension == ".plan"

    preview = registry.list(status=FormatStatus.PREVIEW)
    assert len(preview) == 1
    assert preview[0].extension == ".prev"

    # list by extension
    by_ext = registry.list(extension=".test")
    assert len(by_ext) == 1
    assert by_ext[0].parser_id == "parser.test"

    # list by extension without dot
    by_ext = registry.list(extension="plan")
    assert len(by_ext) == 1
    assert by_ext[0].extension == ".plan"

    # lookup
    assert registry.lookup(".test") is not None
    assert registry.lookup(".test").display_name == "Test Format (.test)"
    assert registry.lookup(".missing") is None
    assert registry.lookup("test") is not None  # without dot

    # check — supported
    result = registry.check(".test")
    assert result["supported"] is True
    assert result["status"] == "supported"

    # check — planned
    result = registry.check(".plan")
    assert result["supported"] is True
    assert result["status"] == "planned"
    assert "Not ready yet" in str(result["message"])

    # check — preview
    result = registry.check(".prev")
    assert result["supported"] is True
    assert result["status"] == "preview"
    assert "May be unstable" in str(result["message"])

    # check — unknown
    result = registry.check(".unknown")
    assert result["supported"] is False
    assert result["status"] == "unsupported"
    assert result["parser_id"] is None

    # check without dot prefix
    result = registry.check("test")
    assert result["supported"] is True
    assert result["extension"] == ".test"

    # list with extension filter on unknown
    empty_list = registry.list(extension=".unknown")
    assert len(empty_list) == 0


def test_default_registry_loads_from_yaml() -> None:
    """Test the default registry singleton loads from the YAML fixture."""
    from ragrig.formats.registry import get_format_registry

    registry = get_format_registry()
    formats = registry.list()
    assert len(formats) >= 4

    # Check that all statuses are present
    statuses = {fmt.status for fmt in formats}
    assert FormatStatus.SUPPORTED in statuses
    assert FormatStatus.PREVIEW in statuses
    assert FormatStatus.PLANNED in statuses

    # Test check on a planned format through the default registry
    result = registry.check(".docx")
    assert result["supported"] is True
    assert result["status"] == "planned"


def test_registry_check_planned_format_status_message() -> None:
    """Test that planned formats return the correct status message."""
    fmt = SupportedFormat(
        extension=".planned",
        mime_type="application/x-planned",
        display_name="Planned Format",
        parser_id="parser.planned",
        status=FormatStatus.PLANNED,
        limitations=None,
    )
    registry = SupportedFormatRegistry(formats=[fmt])
    result = registry.check(".planned")
    assert result["status"] == "planned"
    assert "planned" in str(result["message"]).lower()


def test_load_builtin_formats_falls_back_when_file_missing(monkeypatch) -> None:
    """When the YAML fixture file does not exist, _load_builtin_formats returns defaults."""
    from pathlib import Path

    from ragrig.formats.registry import _load_builtin_formats

    # Pretend the file doesn't exist
    fake_path = Path("/nonexistent/supported_formats.yaml")
    monkeypatch.setattr("ragrig.formats.registry._BUILTIN_FORMATS_PATH", fake_path)

    result = _load_builtin_formats()
    # Should return the _DEFAULT_FORMATS since file doesn't exist
    assert isinstance(result, list)
    assert len(result) >= 4
    extensions = {entry["extension"] for entry in result}
    assert ".md" in extensions
    assert ".txt" in extensions


def test_load_builtin_formats_handles_dict_with_formats_key(monkeypatch, tmp_path) -> None:
    """When the YAML file is a dict with 'formats' key, extract formats from that key."""
    import yaml

    from ragrig.formats.registry import _load_builtin_formats

    fixture_file = tmp_path / "supported_formats.yaml"
    fixture_file.write_text(
        yaml.dump(
            {
                "formats": [
                    {
                        "extension": ".custom",
                        "mime_type": "application/x-custom",
                        "display_name": "Custom",
                        "parser_id": "parser.custom",
                        "status": "supported",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("ragrig.formats.registry._BUILTIN_FORMATS_PATH", fixture_file)

    result = _load_builtin_formats()
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["extension"] == ".custom"


def test_load_builtin_formats_falls_back_on_malformed_yaml(monkeypatch, tmp_path) -> None:
    """When the YAML file is neither a list nor a dict with 'formats', fall back to defaults."""
    from ragrig.formats.registry import _load_builtin_formats

    fixture_file = tmp_path / "supported_formats.yaml"
    fixture_file.write_text("just_a_string: 42\n", encoding="utf-8")

    monkeypatch.setattr("ragrig.formats.registry._BUILTIN_FORMATS_PATH", fixture_file)

    result = _load_builtin_formats()
    assert isinstance(result, list)
    assert len(result) >= 4  # falls back to defaults
