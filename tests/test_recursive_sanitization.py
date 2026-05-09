"""Unit tests for recursive metadata_json sanitization."""

from __future__ import annotations

import pytest

from ragrig.processing_profile.models import _sanitize_metadata
from ragrig.repositories.processing_profile import (
    REDACTED,
    _compute_changed_paths,
    _is_sensitive_key,
    _is_sensitive_value,
    _sanitize_metadata_json,
    _sanitize_state,
)

pytestmark = pytest.mark.unit


# ── _is_sensitive_key ──


def test_sensitive_key_matches_substring() -> None:
    assert _is_sensitive_key("api_key") is True
    assert _is_sensitive_key("my_api_key") is True
    assert _is_sensitive_key("API_KEY_PROD") is True
    assert _is_sensitive_key("password") is True
    assert _is_sensitive_key("admin_password_hash") is True
    assert _is_sensitive_key("token") is True
    assert _is_sensitive_key("access_token") is True
    assert _is_sensitive_key("secret") is True
    assert _is_sensitive_key("client_secret") is True
    assert _is_sensitive_key("private_key") is True
    assert _is_sensitive_key("credential") is True
    assert _is_sensitive_key("dsn") is True
    assert _is_sensitive_key("service_account") is True
    assert _is_sensitive_key("session_token") is True


def test_non_sensitive_keys_not_matched() -> None:
    assert _is_sensitive_key("name") is False
    assert _is_sensitive_key("display_name") is False
    assert _is_sensitive_key("version") is False
    assert _is_sensitive_key("provider") is False
    assert _is_sensitive_key("model_id") is False
    assert _is_sensitive_key("task_type") is False
    assert _is_sensitive_key("") is False


# ── _is_sensitive_value ──


def test_bearer_token_detected() -> None:
    assert _is_sensitive_value("Bearer abc123") is True
    assert _is_sensitive_value("bearer xyz-999") is True
    assert _is_sensitive_value("BEARER TOKEN") is True


def test_pem_private_key_detected() -> None:
    assert _is_sensitive_value("-----BEGIN PRIVATE KEY-----") is True
    assert _is_sensitive_value("-----begin rsa private key-----") is True
    assert _is_sensitive_value("some\n-----BEGIN EC PRIVATE KEY-----\ndata") is True


def test_non_sensitive_values_not_matched() -> None:
    assert _is_sensitive_value("hello world") is False
    assert _is_sensitive_value("BearerToken") is False  # no space after "bearer"
    assert _is_sensitive_value(123) is False
    assert _is_sensitive_value(None) is False
    assert _is_sensitive_value(True) is False
    assert _is_sensitive_value([]) is False


# ── _sanitize_metadata_json ──


def test_top_level_sensitive_key_redacted() -> None:
    meta = {"api_key": "sk-12345", "normal": "visible"}
    sanitized, count, paths = _sanitize_metadata_json(meta)
    assert sanitized["api_key"] == REDACTED
    assert sanitized["normal"] == "visible"
    assert count == 1
    assert paths == ["metadata_json.api_key"]


def test_nested_dict_sensitive_key_redacted() -> None:
    meta = {
        "auth": {
            "token": "top-secret-token",
            "user": "admin",
        }
    }
    sanitized, count, paths = _sanitize_metadata_json(meta)
    assert sanitized["auth"]["token"] == REDACTED
    assert sanitized["auth"]["user"] == "admin"
    assert count == 1
    assert paths == ["metadata_json.auth.token"]


def test_deeply_nested_dict() -> None:
    meta = {
        "level1": {
            "level2": {
                "level3": {
                    "api_key": "deep-secret",
                    "name": "leaf",
                }
            }
        }
    }
    sanitized, count, paths = _sanitize_metadata_json(meta)
    assert sanitized["level1"]["level2"]["level3"]["api_key"] == REDACTED
    assert sanitized["level1"]["level2"]["level3"]["name"] == "leaf"
    assert count == 1
    assert "metadata_json.level1.level2.level3.api_key" in paths


def test_list_of_dicts() -> None:
    meta = {
        "providers": [
            {"name": "a", "api_key": "key-a"},
            {"name": "b", "password": "pass-b"},
            {"name": "c", "normal": "c-val"},
        ]
    }
    sanitized, count, paths = _sanitize_metadata_json(meta)
    assert sanitized["providers"][0]["api_key"] == REDACTED
    assert sanitized["providers"][0]["name"] == "a"
    assert sanitized["providers"][1]["password"] == REDACTED
    assert sanitized["providers"][1]["name"] == "b"
    assert sanitized["providers"][2]["normal"] == "c-val"
    assert count == 2
    assert "metadata_json.providers[0].api_key" in paths
    assert "metadata_json.providers[1].password" in paths


def test_nested_list_inside_dict_inside_list() -> None:
    meta = {
        "clusters": [
            {
                "id": "c1",
                "nodes": [
                    {"secret": "s1"},
                    {"secret": "s2"},
                ],
            }
        ]
    }
    sanitized, count, paths = _sanitize_metadata_json(meta)
    assert sanitized["clusters"][0]["nodes"][0]["secret"] == REDACTED
    assert sanitized["clusters"][0]["nodes"][1]["secret"] == REDACTED
    assert sanitized["clusters"][0]["id"] == "c1"
    assert count == 2


def test_list_of_lists() -> None:
    meta = {
        "matrix": [
            ["a", "b"],
            ["c", "d"],
        ]
    }
    sanitized, count, paths = _sanitize_metadata_json(meta)
    assert sanitized["matrix"] == [["a", "b"], ["c", "d"]]
    assert count == 0
    assert paths == []


def test_bearer_token_value_redacted() -> None:
    meta = {"headers": {"Authorization": "Bearer secret-token-123"}}
    sanitized, count, paths = _sanitize_metadata_json(meta)
    assert sanitized["headers"]["Authorization"] == REDACTED
    assert count == 1
    assert "metadata_json.headers.Authorization" in paths


def test_pem_key_value_redacted() -> None:
    meta = {
        "certs": {
            "key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpA...\n-----END RSA PRIVATE KEY-----"
        }
    }
    sanitized, count, paths = _sanitize_metadata_json(meta)
    assert sanitized["certs"]["key"] == REDACTED
    assert count == 1


def test_non_sensitive_nested_preserved() -> None:
    meta = {
        "config": {
            "timeout": 30,
            "retries": 3,
            "urls": ["https://a.com", "https://b.com"],
            "enabled": True,
        }
    }
    sanitized, count, paths = _sanitize_metadata_json(meta)
    assert sanitized == meta
    assert count == 0
    assert paths == []


def test_null_and_empty_handled() -> None:
    meta = {
        "null_field": None,
        "empty_dict": {},
        "empty_list": [],
        "scalar": 42,
        "bool_val": False,
    }
    sanitized, count, paths = _sanitize_metadata_json(meta)
    assert sanitized["null_field"] is None
    assert sanitized["empty_dict"] == {}
    assert sanitized["empty_list"] == []
    assert sanitized["scalar"] == 42
    assert sanitized["bool_val"] is False
    assert count == 0


def test_multiple_sensitive_across_levels() -> None:
    meta = {
        "api_key": "top",
        "nested": {
            "token": "nested-token",
            "deep": {"password": "deep-pass"},
        },
        "list": [
            {"secret": "s1"},
            {"normal": "ok"},
        ],
        "ok": "fine",
    }
    sanitized, count, paths = _sanitize_metadata_json(meta)
    assert sanitized["api_key"] == REDACTED
    assert sanitized["nested"]["token"] == REDACTED
    assert sanitized["nested"]["deep"]["password"] == REDACTED
    assert sanitized["list"][0]["secret"] == REDACTED
    assert sanitized["list"][1]["normal"] == "ok"
    assert sanitized["ok"] == "fine"
    assert count == 4
    assert len(paths) == 4


# ── _sanitize_state ──


def test_sanitize_state_includes_redaction_meta() -> None:
    state = {
        "display_name": "Test",
        "metadata_json": {"api_key": "secret-val", "version": 2},
        "provider": "ollama",
    }
    sanitized = _sanitize_state(state)
    assert "_redaction" in sanitized
    assert sanitized["_redaction"]["count"] == 1
    assert "metadata_json.api_key" in sanitized["_redaction"]["paths"]
    assert sanitized["metadata_json"]["api_key"] == REDACTED
    assert sanitized["metadata_json"]["version"] == 2


def test_sanitize_state_top_level_sensitive_key() -> None:
    state = {
        "api_key": "top-secret",
        "display_name": "Test",
    }
    sanitized = _sanitize_state(state)
    assert sanitized["api_key"] == REDACTED
    assert sanitized["display_name"] == "Test"
    assert sanitized["_redaction"]["count"] == 1
    assert "api_key" in sanitized["_redaction"]["paths"]


def test_sanitize_state_no_redaction_meta_when_nothing_redacted() -> None:
    state = {
        "display_name": "Test",
        "provider": "ollama",
        "metadata_json": {"version": 2},
    }
    sanitized = _sanitize_state(state)
    assert "_redaction" not in sanitized


# ── _compute_changed_paths ──


def test_compute_changed_paths_top_level() -> None:
    old = {"a": 1, "b": 2, "c": 3}
    new = {"a": 1, "b": 99, "c": 3}
    changed = _compute_changed_paths(old, new)
    assert changed == ["b"]


def test_compute_changed_paths_stable_order() -> None:
    old = {"z": 1, "a": 2}
    new = {"z": 1, "a": 99}
    changed = _compute_changed_paths(old, new)
    assert changed == sorted(changed)
    assert changed == ["a"]


def test_compute_changed_paths_nested_metadata_json() -> None:
    old = {
        "display_name": "Old",
        "metadata_json": {"api_key": "old", "version": 1},
    }
    new = {
        "display_name": "Old",
        "metadata_json": {"api_key": "new", "version": 2},
    }
    changed = _compute_changed_paths(old, new)
    assert "metadata_json.api_key" in changed
    assert "metadata_json.version" in changed
    assert "display_name" not in changed


def test_compute_changed_paths_nested_dict() -> None:
    old = {"config": {"timeout": 30}}
    new = {"config": {"timeout": 60}}
    changed = _compute_changed_paths(old, new)
    assert changed == ["config.timeout"]


def test_compute_changed_paths_list_changed() -> None:
    old = {"tags": ["a", "b"]}
    new = {"tags": ["c", "d"]}
    changed = _compute_changed_paths(old, new)
    # Both lists same length, elements differ
    assert "tags[0]" in changed
    assert "tags[1]" in changed


def test_compute_changed_paths_list_length_differs() -> None:
    old = {"tags": ["a"]}
    new = {"tags": ["a", "b"]}
    changed = _compute_changed_paths(old, new)
    assert "tags" in changed


def test_compute_changed_paths_no_changes() -> None:
    old = {"a": 1, "b": {"c": 2}}
    new = {"a": 1, "b": {"c": 2}}
    changed = _compute_changed_paths(old, new)
    assert changed == []


# ── models._sanitize_metadata (API layer) ──


def test_api_sanitize_metadata_removes_sensitive_keys() -> None:
    meta = {"api_key": "sk-abc", "version": 1}
    result = _sanitize_metadata(meta)
    assert "api_key" not in result
    assert result["version"] == 1


def test_api_sanitize_metadata_recursive() -> None:
    meta = {
        "config": {
            "api_key": "nested-secret",
            "visible": "ok",
        }
    }
    result = _sanitize_metadata(meta)
    assert "api_key" not in result["config"]
    assert result["config"]["visible"] == "ok"


def test_api_sanitize_metadata_list_recursive() -> None:
    meta = {
        "items": [
            {"token": "t1", "name": "a"},
            {"token": "t2", "name": "b"},
        ]
    }
    result = _sanitize_metadata(meta)
    assert "token" not in result["items"][0]
    assert result["items"][0]["name"] == "a"
    assert "token" not in result["items"][1]
    assert result["items"][1]["name"] == "b"


def test_api_sanitize_metadata_bearer_token_removed() -> None:
    meta = {"headers": {"auth": "Bearer xyz123"}}
    result = _sanitize_metadata(meta)
    assert "auth" not in result["headers"]


def test_api_sanitize_metadata_pem_removed() -> None:
    meta = {"key": "-----BEGIN PRIVATE KEY-----\nxxx"}
    result = _sanitize_metadata(meta)
    assert "key" not in result


def test_api_sanitize_metadata_preserves_non_sensitive() -> None:
    meta = {
        "version": 2,
        "tags": ["a", "b"],
        "config": {"timeout": 30},
        "nil": None,
        "empty_list": [],
    }
    result = _sanitize_metadata(meta)
    assert result["version"] == 2
    assert result["tags"] == ["a", "b"]
    assert result["config"] == {"timeout": 30}
    assert result["nil"] is None
    assert result["empty_list"] == []


# ── Edge cases ──


def test_empty_metadata() -> None:
    sanitized, count, paths = _sanitize_metadata_json({})
    assert sanitized == {}
    assert count == 0
    assert paths == []


def test_only_sensitive_top_level() -> None:
    meta = {"api_key": "val", "password": "val2"}
    sanitized, count, paths = _sanitize_metadata_json(meta)
    assert sanitized == {"api_key": REDACTED, "password": REDACTED}
    assert count == 2


def test_sensitive_in_deep_list_with_bearer_value() -> None:
    meta = {
        "webhooks": [
            {"url": "https://x.com", "headers": {"Authorization": "Bearer secret-abc"}},
        ]
    }
    sanitized, count, paths = _sanitize_metadata_json(meta)
    assert sanitized["webhooks"][0]["headers"]["Authorization"] == REDACTED
    assert count == 1
    assert "metadata_json.webhooks[0].headers.Authorization" in paths


def test_non_dict_metadata_not_called_in_state() -> None:
    """_sanitize_state should only recurse metadata_json when it's a dict."""
    state = {
        "metadata_json": "not-a-dict",
        "display_name": "ok",
    }
    sanitized = _sanitize_state(state)
    assert sanitized["metadata_json"] == "not-a-dict"
    assert "_redaction" not in sanitized
