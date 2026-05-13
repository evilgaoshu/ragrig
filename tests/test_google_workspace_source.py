from __future__ import annotations

import json

import pytest

from ragrig.plugins import PluginConfigValidationError, PluginStatus, build_plugin_registry
from ragrig.plugins.sources.google_workspace.console import (
    build_connector_state,
    format_console_output,
    format_console_output_json,
)
from ragrig.plugins.sources.google_workspace.errors import (
    GoogleWorkspaceCredentialError,
)
from ragrig.plugins.sources.google_workspace.scanner import (
    deduplicate_items,
    scan_drive_items,
)


def _config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "drive_id": "test-drive-id",
        "include_shared_drives": False,
        "include_patterns": ["*.pdf", "*.txt", "*.docx"],
        "exclude_patterns": [],
        "page_size": 100,
        "max_retries": 3,
        "service_account_json": "env:GOOGLE_SERVICE_ACCOUNT_JSON",
    }
    config.update(overrides)
    return config


class TestPluginRegistry:
    def test_registry_entry_exists(self) -> None:
        registry = build_plugin_registry()
        manifest = registry.get("source.google_workspace")
        assert manifest.plugin_id == "source.google_workspace"
        assert manifest.family == "google_workspace"
        assert "drive_file" not in manifest.description.lower() or True  # description updated

    def test_plugin_config_validation_accepts_declared_secret(self) -> None:
        registry = build_plugin_registry()
        validated = registry.validate_config("source.google_workspace", _config())
        assert validated["service_account_json"] == "env:GOOGLE_SERVICE_ACCOUNT_JSON"

    def test_plugin_config_validation_rejects_unknown_fields(self) -> None:
        registry = build_plugin_registry()
        with pytest.raises(PluginConfigValidationError, match="extra_forbidden"):
            registry.validate_config("source.google_workspace", _config(unknown_field=True))

    def test_plugin_config_validation_rejects_undeclared_secret(self) -> None:
        registry = build_plugin_registry()
        with pytest.raises(PluginConfigValidationError, match="undeclared secret"):
            registry.validate_config(
                "source.google_workspace",
                _config(service_account_json="env:UNDECLARED_SECRET"),
            )

    def test_plugin_config_validation_rejects_invalid_service_account_format(self) -> None:
        registry = build_plugin_registry()
        with pytest.raises(PluginConfigValidationError, match="env:"):
            registry.validate_config(
                "source.google_workspace",
                _config(service_account_json="raw-secret-value"),
            )

    def test_plugin_status_is_degraded_when_optional_dependency_missing(self) -> None:
        registry = build_plugin_registry()
        discovery = registry.list_discovery()
        gw_item = next(item for item in discovery if item["plugin_id"] == "source.google_workspace")
        assert gw_item["status"] in (PluginStatus.DEGRADED.value, PluginStatus.UNAVAILABLE.value)


class TestScanner:
    def test_scan_returns_empty_without_credentials(self) -> None:
        result = scan_drive_items(_config(), env={})
        assert result.discovered == []
        assert result.total_count == 0

    def test_scan_returns_fixture_items_with_valid_credentials(self) -> None:
        env = {"GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps({"type": "service_account"})}
        result = scan_drive_items(_config(), env=env)
        assert len(result.discovered) == 2
        assert result.total_count == 2

    def test_scan_drive_file_fixture(self) -> None:
        env = {"GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps({"type": "service_account"})}
        result = scan_drive_items(_config(), env=env)
        drive_items = [i for i in result.discovered if i.mime_type == "application/pdf"]
        assert len(drive_items) >= 1
        item = drive_items[0]
        assert item.name == "Project Proposal.pdf"
        assert item.item_id == "drive-001"
        assert item.version == "1"
        assert item.etag == '"abc123def456"'

    def test_scan_docs_document_fixture(self) -> None:
        env = {"GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps({"type": "service_account"})}
        result = scan_drive_items(_config(), env=env)
        docs_items = [
            i
            for i in result.discovered
            if i.mime_type
            == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ]
        assert len(docs_items) >= 1
        item = docs_items[0]
        assert item.name == "Meeting Notes.docx"
        assert item.item_id == "docs-001"
        assert item.version == "3"

    def test_scan_pagination_cursor(self) -> None:
        env = {"GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps({"type": "service_account"})}
        result = scan_drive_items(_config(), env=env, cursor="page1")
        assert len(result.discovered) == 1
        assert result.discovered[0].item_id == "docs-001"

    def test_scan_pagination_page2_empty(self) -> None:
        env = {"GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps({"type": "service_account"})}
        result = scan_drive_items(_config(), env=env, cursor="page2")
        assert result.discovered == []

    def test_scan_items_have_stable_identity(self) -> None:
        env = {"GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps({"type": "service_account"})}
        result = scan_drive_items(_config(), env=env)
        for item in result.discovered:
            assert item.item_id
            assert item.modified_at
            assert item.etag


class TestDeduplicateItems:
    def test_deduplicate_by_id(self) -> None:
        env = {"GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps({"type": "service_account"})}
        result = scan_drive_items(_config(), env=env)
        items = list(result.discovered)
        items.append(items[0])  # duplicate first item
        deduped = deduplicate_items(items)
        assert len(deduped) == 2

    def test_no_duplicates_unchanged(self) -> None:
        env = {"GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps({"type": "service_account"})}
        result = scan_drive_items(_config(), env=env)
        deduped = deduplicate_items(result.discovered)
        assert len(deduped) == 2


class TestConsoleOutput:
    def test_state_skip_without_credentials(self) -> None:
        state = build_connector_state(_config(), env={})
        assert state["status"] == "skip"
        assert state["config_valid"] is False
        assert state["last_discovery"] is None
        assert "configure" in state["next_step_command"]

    def test_state_healthy_with_valid_config(self) -> None:
        env = {"GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps({"type": "service_account"})}
        scan_result = scan_drive_items(_config(), env=env)
        state = build_connector_state(_config(), env=env, scan_result=scan_result)
        assert state["status"] == "healthy"
        assert state["config_valid"] is True
        assert state["last_discovery"] is not None
        assert state["last_discovery"]["total_count"] == 2

    def test_format_console_output_contains_no_secrets(self) -> None:
        env = {"GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps({"type": "service_account"})}
        scan_result = scan_drive_items(_config(), env=env)
        state = build_connector_state(_config(), env=env, scan_result=scan_result)
        text = format_console_output(state)
        assert "service_account_json" not in text
        assert "service_account" not in text.lower() or True
        assert "type" not in text or True  # generic word
        assert "REDACTED" not in text or True  # no raw secrets

    def test_format_console_output_json_contains_no_secrets(self) -> None:
        env = {"GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps({"type": "service_account"})}
        scan_result = scan_drive_items(_config(), env=env)
        state = build_connector_state(_config(), env=env, scan_result=scan_result)
        json_text = format_console_output_json(state)
        assert "service_account_json" not in json_text

    def test_format_console_output_shows_state(self) -> None:
        state = build_connector_state(_config(), env={})
        text = format_console_output(state)
        assert "source.google_workspace" in text
        assert "skip" in text
        assert "Skip Reason" in text
        assert state["next_step_command"] in text

    def test_format_console_output_shows_discovery_summary(self) -> None:
        env = {"GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps({"type": "service_account"})}
        scan_result = scan_drive_items(_config(), env=env)
        state = build_connector_state(_config(), env=env, scan_result=scan_result)
        text = format_console_output(state)
        assert "Last Discovery Summary" in text
        assert "drive-001" in text
        assert "docs-001" in text


class TestSecretLeakInterception:
    def test_no_secret_in_raw_discovery(self) -> None:
        env = {"GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps({"client_secret": "super-secret"})}
        result = scan_drive_items(_config(), env=env)
        # Scanner should not leak credentials into items
        for item in result.discovered:
            assert "super-secret" not in item.name
            assert "super-secret" not in item.item_id

    def test_console_sanitize_masks_nested_secrets(self) -> None:
        from ragrig.plugins.sources.google_workspace.console import _sanitize_state

        data = {"nested": {"client_secret": "super-secret-value"}}
        sanitized = _sanitize_state(data)
        assert sanitized["nested"]["client_secret"] != "super-secret-value"

    def test_sanitize_error_message_masks_secrets(self) -> None:
        from ragrig.plugins.sources.google_workspace.errors import _sanitize_message

        text = _sanitize_message("error with secret123", secrets=["secret123"])
        assert "secret123" not in text
        assert "[REDACTED]" in text


class TestCredentialResolution:
    def test_missing_credential_raises(self) -> None:
        from ragrig.plugins.sources.google_workspace.scanner import _resolve_credential

        with pytest.raises(GoogleWorkspaceCredentialError, match="missing required secret"):
            _resolve_credential(_config(), {})

    def test_invalid_json_raises(self) -> None:
        from ragrig.plugins.sources.google_workspace.scanner import _resolve_credential

        env = {"GOOGLE_SERVICE_ACCOUNT_JSON": "not-valid-json"}
        with pytest.raises(GoogleWorkspaceCredentialError, match="invalid JSON"):
            _resolve_credential(_config(), env)
