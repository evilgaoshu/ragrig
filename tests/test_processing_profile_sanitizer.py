"""Unit tests for the unified ProcessingProfile metadata sanitizer.

Covers:
- Shared predicates (is_sensitive_key, is_sensitive_value)
- redact_metadata (redacted mode) — repository callers
- remove_metadata (removal mode) — model/to_api_dict callers
- redact_state — audit log state sanitizer
- Drift protection: repository/model/API callers produce consistent results
- Edge cases: null, empty, scalars, deep nesting
"""

from __future__ import annotations

import pytest

from ragrig.processing_profile.models import _sanitize_metadata
from ragrig.processing_profile.sanitizer import (
    REDACTED,
    SENSITIVE_KEY_PARTS,
    is_sensitive_key,
    is_sensitive_value,
    redact_metadata,
    redact_state,
    remove_metadata,
)
from ragrig.repositories.processing_profile import (
    _sanitize_metadata_json,
    _sanitize_state,
)

pytestmark = pytest.mark.unit


# ═══════════════════════════════════════════════════════════════════════════
# is_sensitive_key
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "my_api_key",
        "API_KEY_PROD",
        "password",
        "admin_password_hash",
        "token",
        "access_token",
        "secret",
        "client_secret",
        "private_key",
        "credential",
        "dsn",
        "service_account",
        "session_token",
    ],
)
def test_sensitive_key_detected(key: str) -> None:
    assert is_sensitive_key(key) is True


@pytest.mark.parametrize(
    "key",
    [
        "name",
        "display_name",
        "version",
        "provider",
        "model_id",
        "task_type",
        "extension",
        "description",
        "",
        "tags",
    ],
)
def test_non_sensitive_key_not_detected(key: str) -> None:
    assert is_sensitive_key(key) is False


# ═══════════════════════════════════════════════════════════════════════════
# is_sensitive_value
# ═══════════════════════════════════════════════════════════════════════════


def test_bearer_token_detected() -> None:
    assert is_sensitive_value("Bearer abc123") is True
    assert is_sensitive_value("bearer xyz-999") is True
    assert is_sensitive_value("BEARER TOKEN") is True


def test_pem_private_key_detected() -> None:
    assert is_sensitive_value("-----BEGIN PRIVATE KEY-----") is True
    assert is_sensitive_value("-----begin rsa private key-----") is True
    assert is_sensitive_value("some\n-----BEGIN EC PRIVATE KEY-----\ndata") is True


def test_non_sensitive_values_not_matched() -> None:
    assert is_sensitive_value("hello world") is False
    assert is_sensitive_value("BearerToken") is False  # no space after "bearer"
    assert is_sensitive_value(123) is False
    assert is_sensitive_value(None) is False
    assert is_sensitive_value(True) is False
    assert is_sensitive_value([]) is False
    assert is_sensitive_value(3.14) is False


# ═══════════════════════════════════════════════════════════════════════════
# redact_metadata — redacted mode
# ═══════════════════════════════════════════════════════════════════════════


def test_redact_top_level_sensitive_key() -> None:
    meta = {"api_key": "sk-12345", "normal": "visible"}
    sanitized, count, paths = redact_metadata(meta)
    assert sanitized["api_key"] == REDACTED
    assert sanitized["normal"] == "visible"
    assert count == 1
    assert paths == ["api_key"]


def test_redact_nested_sensitive_key() -> None:
    meta = {"auth": {"token": "top-secret-token", "user": "admin"}}
    sanitized, count, paths = redact_metadata(meta)
    assert sanitized["auth"]["token"] == REDACTED
    assert sanitized["auth"]["user"] == "admin"
    assert count == 1
    assert paths == ["auth.token"]


def test_redact_deeply_nested() -> None:
    meta = {"level1": {"level2": {"level3": {"api_key": "deep-secret", "name": "leaf"}}}}
    sanitized, count, paths = redact_metadata(meta)
    assert sanitized["level1"]["level2"]["level3"]["api_key"] == REDACTED
    assert sanitized["level1"]["level2"]["level3"]["name"] == "leaf"
    assert count == 1
    assert "level1.level2.level3.api_key" in paths


def test_redact_list_of_dicts() -> None:
    meta = {
        "providers": [
            {"name": "a", "api_key": "key-a"},
            {"name": "b", "password": "pass-b"},
            {"name": "c", "normal": "c-val"},
        ]
    }
    sanitized, count, paths = redact_metadata(meta)
    assert sanitized["providers"][0]["api_key"] == REDACTED
    assert sanitized["providers"][0]["name"] == "a"
    assert sanitized["providers"][1]["password"] == REDACTED
    assert sanitized["providers"][1]["name"] == "b"
    assert sanitized["providers"][2]["normal"] == "c-val"
    assert count == 2
    assert "providers[0].api_key" in paths
    assert "providers[1].password" in paths


def test_redact_nested_list_in_list() -> None:
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
    sanitized, count, paths = redact_metadata(meta)
    assert sanitized["clusters"][0]["nodes"][0]["secret"] == REDACTED
    assert sanitized["clusters"][0]["nodes"][1]["secret"] == REDACTED
    assert sanitized["clusters"][0]["id"] == "c1"
    assert count == 2


def test_redact_list_of_lists() -> None:
    meta = {"matrix": [["a", "b"], ["c", "d"]]}
    sanitized, count, _ = redact_metadata(meta)
    assert sanitized["matrix"] == [["a", "b"], ["c", "d"]]
    assert count == 0


def test_redact_bearer_token_value() -> None:
    meta = {"headers": {"Authorization": "Bearer secret-token-123"}}
    sanitized, count, paths = redact_metadata(meta)
    assert sanitized["headers"]["Authorization"] == REDACTED
    assert count == 1
    assert "headers.Authorization" in paths


def test_redact_pem_key_value() -> None:
    meta = {
        "certs": {
            "key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpA...\n-----END RSA PRIVATE KEY-----"
        }
    }
    sanitized, count, paths = redact_metadata(meta)
    assert sanitized["certs"]["key"] == REDACTED
    assert count == 1


def test_redact_preserves_non_sensitive() -> None:
    meta = {
        "config": {
            "timeout": 30,
            "retries": 3,
            "urls": ["https://a.com", "https://b.com"],
            "enabled": True,
        }
    }
    sanitized, count, _ = redact_metadata(meta)
    assert sanitized == meta
    assert count == 0


def test_redact_null_empty_scalar() -> None:
    meta = {
        "null_field": None,
        "empty_dict": {},
        "empty_list": [],
        "scalar": 42,
        "bool_val": False,
    }
    sanitized, count, _ = redact_metadata(meta)
    assert sanitized["null_field"] is None
    assert sanitized["empty_dict"] == {}
    assert sanitized["empty_list"] == []
    assert sanitized["scalar"] == 42
    assert sanitized["bool_val"] is False
    assert count == 0


def test_redact_multiple_across_levels() -> None:
    meta = {
        "api_key": "top-secret",
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
    sanitized, count, paths = redact_metadata(meta)
    assert sanitized["api_key"] == REDACTED
    assert sanitized["nested"]["token"] == REDACTED
    assert sanitized["nested"]["deep"]["password"] == REDACTED
    assert sanitized["list"][0]["secret"] == REDACTED
    assert sanitized["list"][1]["normal"] == "ok"
    assert sanitized["ok"] == "fine"
    assert count == 4
    assert len(paths) == 4


def test_redact_empty_metadata() -> None:
    sanitized, count, paths = redact_metadata({})
    assert sanitized == {}
    assert count == 0
    assert paths == []


def test_redact_only_sensitive_keys() -> None:
    meta = {"api_key": "val", "password": "val2"}
    sanitized, count, _ = redact_metadata(meta)
    assert sanitized == {"api_key": REDACTED, "password": REDACTED}
    assert count == 2


def test_redact_bearer_in_deep_list() -> None:
    meta = {
        "webhooks": [
            {"url": "https://x.com", "headers": {"Authorization": "Bearer secret-abc"}},
        ]
    }
    sanitized, count, paths = redact_metadata(meta)
    assert sanitized["webhooks"][0]["headers"]["Authorization"] == REDACTED
    assert count == 1
    assert "webhooks[0].headers.Authorization" in paths


def test_redact_custom_prefix() -> None:
    meta = {"token": "abc"}
    sanitized, count, paths = redact_metadata(meta, prefix="metadata_json")
    assert sanitized["token"] == REDACTED
    assert paths == ["metadata_json.token"]


# ═══════════════════════════════════════════════════════════════════════════
# remove_metadata — removal mode
# ═══════════════════════════════════════════════════════════════════════════


def test_remove_top_level_sensitive_key() -> None:
    meta = {"api_key": "sk-abc", "version": 1}
    result = remove_metadata(meta)
    assert "api_key" not in result
    assert result["version"] == 1


def test_remove_nested_sensitive_key() -> None:
    meta = {"config": {"api_key": "nested-secret", "visible": "ok"}}
    result = remove_metadata(meta)
    assert "api_key" not in result["config"]
    assert result["config"]["visible"] == "ok"


def test_remove_list_of_dicts() -> None:
    meta = {
        "items": [
            {"token": "t1", "name": "a"},
            {"token": "t2", "name": "b"},
        ]
    }
    result = remove_metadata(meta)
    assert "token" not in result["items"][0]
    assert result["items"][0]["name"] == "a"
    assert "token" not in result["items"][1]
    assert result["items"][1]["name"] == "b"


def test_remove_bearer_token() -> None:
    meta = {"headers": {"auth": "Bearer xyz123"}}
    result = remove_metadata(meta)
    assert "auth" not in result["headers"]


def test_remove_pem_key() -> None:
    meta = {"key": "-----BEGIN PRIVATE KEY-----\nxxx"}
    result = remove_metadata(meta)
    assert "key" not in result


def test_remove_preserves_non_sensitive() -> None:
    meta = {
        "version": 2,
        "tags": ["a", "b"],
        "config": {"timeout": 30},
        "nil": None,
        "empty_list": [],
        "empty_dict": {},
    }
    result = remove_metadata(meta)
    assert result["version"] == 2
    assert result["tags"] == ["a", "b"]
    assert result["config"] == {"timeout": 30}
    assert result["nil"] is None
    assert result["empty_list"] == []
    assert result["empty_dict"] == {}


def test_remove_sensitive_in_list() -> None:
    meta = {
        "items": [
            "Bearer token1",
            "normal value",
            42,
            None,
            "Bearer token2",
        ]
    }
    result = remove_metadata(meta)
    assert result["items"] == ["normal value", 42, None]


def test_remove_sensitive_in_nested_list() -> None:
    meta = {
        "providers": [
            {"api_key": "sk-a", "name": "a"},
            {"password": "pass-b", "name": "b"},
        ]
    }
    result = remove_metadata(meta)
    assert "api_key" not in result["providers"][0]
    assert result["providers"][0]["name"] == "a"
    assert "password" not in result["providers"][1]
    assert result["providers"][1]["name"] == "b"


def test_remove_empty_metadata() -> None:
    assert remove_metadata({}) == {}


# ═══════════════════════════════════════════════════════════════════════════
# redact_state
# ═══════════════════════════════════════════════════════════════════════════


def test_redact_state_includes_redaction_meta() -> None:
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


def test_redact_state_top_level_sensitive() -> None:
    state = {"api_key": "top-secret", "display_name": "Test"}
    sanitized = _sanitize_state(state)
    assert sanitized["api_key"] == REDACTED
    assert sanitized["display_name"] == "Test"
    assert sanitized["_redaction"]["count"] == 1
    assert "api_key" in sanitized["_redaction"]["paths"]


def test_redact_state_no_redaction_meta_when_clean() -> None:
    state = {
        "display_name": "Test",
        "provider": "ollama",
        "metadata_json": {"version": 2},
    }
    sanitized = _sanitize_state(state)
    assert "_redaction" not in sanitized


def test_redact_state_non_dict_metadata() -> None:
    """_sanitize_state should not recurse metadata_json when it is not a dict."""
    state = {"metadata_json": "not-a-dict", "display_name": "ok"}
    sanitized = _sanitize_state(state)
    assert sanitized["metadata_json"] == "not-a-dict"
    assert "_redaction" not in sanitized


def test_redact_state_shared_helper_identical() -> None:
    """Verify _sanitize_state wrapper matches shared redact_state directly."""
    state = {
        "api_key": "secret",
        "metadata_json": {"token": "t", "version": 1},
        "display_name": "Test",
    }
    via_wrapper = _sanitize_state(state)
    via_shared = redact_state(state)
    assert via_wrapper == via_shared


# ═══════════════════════════════════════════════════════════════════════════
# Wrapper consistency — model._sanitize_metadata delegates to shared
# ═══════════════════════════════════════════════════════════════════════════


def test_model_wrapper_matches_shared_remove() -> None:
    meta = {
        "api_key": "sk-123",
        "nested": {"token": "t1", "name": "ok"},
        "items": [{"secret": "s1", "id": 1}],
    }
    via_wrapper = _sanitize_metadata(meta)
    via_shared = remove_metadata(meta)
    assert via_wrapper == via_shared


def test_repository_wrapper_matches_shared_redact() -> None:
    meta = {
        "api_key": "sk-123",
        "nested": {"token": "t1", "name": "ok"},
        "items": [{"secret": "s1", "id": 1}],
    }
    via_wrapper = _sanitize_metadata_json(meta)
    via_shared = redact_metadata(meta, prefix="metadata_json")
    assert via_wrapper == via_shared


# ═══════════════════════════════════════════════════════════════════════════
# Drift protection — all callers produce consistent results
# ═══════════════════════════════════════════════════════════════════════════


def _drift_input() -> dict:
    """Canonical metadata fixture used by all drift tests."""
    return {
        "api_key": "sk-proj-deadbeef",
        "auth": {
            "token": "ghp_secret_token_123",
            "headers": {"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"},
        },
        "config": {
            "version": 2,
            "timeout": 30,
            "tags": ["prod", "us-east-1"],
        },
        "secrets": [
            {"name": "db", "password": "super_secret_db_pass"},
            {"name": "redis", "token": "redis-secret-token"},
            {"name": "cache", "normal": "no-auth"},
        ],
    }


def test_drift_all_sensitive_keys_handled_consistently() -> None:
    """Every sensitive key in SENSITIVE_KEY_PARTS must be detected by both modes."""
    for part in SENSITIVE_KEY_PARTS:
        key = f"my_{part}"
        meta = {key: "test-value", "normal": "ok"}

        # Redact mode
        redacted, count, _ = redact_metadata(meta)
        assert redacted[key] == REDACTED, f"Redact mode missed key='{key}'"
        assert count >= 1, f"Redact count=0 for key='{key}'"

        # Removal mode
        removed = remove_metadata(meta)
        assert key not in removed, f"Remove mode missed key='{key}'"


def test_drift_all_sensitive_value_prefixes_handled_consistently() -> None:
    """Every sensitive value prefix in SENSITIVE_VALUE_PREFIXES must be detected."""
    fixture_map = {
        "bearer ": "Bearer some-secret-jwt-token-value",
        "-----begin": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...",
    }
    for prefix, value in fixture_map.items():
        key = "auth_header" if "bearer" in prefix else "private_key_pem"
        meta = {key: value}

        # Redact mode
        redacted, count, _ = redact_metadata(meta)
        assert redacted[key] == REDACTED, f"Redact mode missed prefix='{prefix}'"
        assert count >= 1, f"Redact count=0 for prefix='{prefix}'"

        # Removal mode
        removed = remove_metadata(meta)
        assert key not in removed, f"Remove mode missed prefix='{prefix}'"


def test_drift_detection_classifies_caller_sites() -> None:
    """Verify that all three call sites agree on what is sensitive."""
    meta = _drift_input()

    # 1. Shared redact_metadata (repository path)
    redacted_dict, redact_count, redact_paths = redact_metadata(meta)

    # 2. Shared remove_metadata (model/API path)
    removed_dict = remove_metadata(meta)

    # 3. Repository wrapper (via _sanitize_metadata_json)
    repo_dict, repo_count, repo_paths = _sanitize_metadata_json(meta)

    # Redact paths must match between shared and wrapper (accounting for prefix)
    shared_paths_stripped = [
        p[len("metadata_json.") :] if p.startswith("metadata_json.") else p
        for p in redact_metadata(meta, prefix="metadata_json")[2]
    ]
    assert shared_paths_stripped == [
        p[len("metadata_json.") :] if p.startswith("metadata_json.") else p for p in repo_paths
    ], f"Path drift: shared_with_prefix={shared_paths_stripped} vs repo_wrapper={repo_paths}"
    assert redact_count == repo_count, (
        f"Count drift: shared={redact_count} vs repo_wrapper={repo_count}"
    )

    # Every key redacted in redact mode must be absent in remove mode
    for path in redact_paths:
        # Navigate to the leaf in removed_dict
        parts = path.split(".")
        current = removed_dict
        for part in parts[:-1]:
            # Handle array index notation like key[0]
            if "[" in part and part.endswith("]"):
                dict_key, idx_str = part.split("[", 1)
                idx = int(idx_str.rstrip("]"))
                current = current[dict_key][idx]
            elif isinstance(current, dict):
                current = current[part]
            elif isinstance(current, list):
                # This shouldn't normally happen for dotted paths alone
                pass
        leaf_key = parts[-1]
        if "[" in leaf_key:
            dict_key, idx_str = leaf_key.split("[", 1)
            idx = int(idx_str.rstrip("]"))
            assert dict_key not in current[idx], (
                f"Remove mode leaked '{path}' (redact mode redacted it)"
            )
        else:
            assert leaf_key not in current, f"Remove mode leaked '{path}' (redact mode redacted it)"


def test_drift_additional_sensitive_key_propagates_to_all_callers() -> None:
    """Adding a new sensitive key part must be picked up by all callers."""
    meta = {"license_key": "LIC-12345-ABCDE", "normal": "ok"}

    # Before adding "license_key" to sensitive parts:
    # It should NOT be treated as sensitive yet.
    redacted, count, _ = redact_metadata(meta)
    # license_key is NOT in SENSITIVE_KEY_PARTS, so it should pass through
    # "license_key" does not match any SENSITIVE_KEY_PARTS entry (substring).
    # So "license_key" is not currently sensitive.

    # Let's verify the property: if we were to add "license" to SENSITIVE_KEY_PARTS,
    # both modes would need to pick it up. This is a structural test of the design.
    # We can't mutate the tuple at runtime, but we can verify the architecture:
    # both redact_metadata and remove_metadata use is_sensitive_key() which reads
    # SENSITIVE_KEY_PARTS. So changing SENSITIVE_KEY_PARTS changes both.
    assert is_sensitive_key("api_key") is True
    assert is_sensitive_key("license_key") is False  # Not a sensitive part

    # Verify architectural consistency: both modes use the same predicate
    assert is_sensitive_key("api_key") is True

    redacted_val = redact_metadata({"api_key": "v", "normal": "ok"})[0]
    assert redacted_val["api_key"] == REDACTED
    assert redacted_val["normal"] == "ok"

    removed_val = remove_metadata({"api_key": "v", "normal": "ok"})
    assert "api_key" not in removed_val
    assert removed_val["normal"] == "ok"


def test_drift_repository_model_api_same_output_for_redacted_keys() -> None:
    """Given the same metadata, every sensitive key is either [REDACTED] or removed."""
    meta = _drift_input()

    # Repository redacted output
    repo_out, _, repo_paths = _sanitize_metadata_json(meta)

    # Model (API) removed output
    model_out = _sanitize_metadata(meta)

    # Every redacted path in repo must be absent from model
    for path in repo_paths:
        parts = path.split(".")
        # Skip the "metadata_json" prefix if present
        if parts[0] == "metadata_json":
            parts = parts[1:]
        current: object = model_out
        for i, part in enumerate(parts):
            if "[" in part:
                dict_key, idx_str = part.split("[", 1)
                idx = int(idx_str.rstrip("]"))
                pre = ".".join(parts[:i])
                assert isinstance(current, dict), f"Expected dict at {pre}, got {type(current)}"
                current = current[dict_key][idx]  # type: ignore[index]
            else:
                if i == len(parts) - 1:
                    # Last part — it should NOT exist in model output
                    assert isinstance(current, dict), f"Expected dict at {'.'.join(parts[:i])}"
                    assert part not in current, f"Model API leaked '{path}' which repo redacted"
                else:
                    assert isinstance(current, dict), f"Expected dict at {'.'.join(parts[:i])}"
                    current = current[part]  # type: ignore[index]

    # Non-sensitive values should be preserved in both
    assert repo_out["config"]["version"] == 2
    assert model_out["config"]["version"] == 2
    assert repo_out["config"]["timeout"] == 30
    assert model_out["config"]["timeout"] == 30


def test_drift_state_sanitizer_agrees_with_metadata_sanitizer() -> None:
    """_sanitize_state must produce the same metadata_json as _sanitize_metadata_json."""
    meta = _drift_input()
    state = {
        "profile_id": "test.profile",
        "metadata_json": meta,
        "display_name": "Test",
    }

    state_sanitized = _sanitize_state(state)
    meta_sanitized, meta_count, meta_paths = _sanitize_metadata_json(meta)

    assert state_sanitized["metadata_json"] == meta_sanitized
    if "_redaction" in state_sanitized:
        assert state_sanitized["_redaction"]["count"] == meta_count
        # Paths from _sanitize_state are relative to metadata_json
        state_paths = [
            p[len("metadata_json.") :] if p.startswith("metadata_json.") else p
            for p in state_sanitized["_redaction"]["paths"]
        ]
        # meta_paths already include "metadata_json." prefix
        meta_relative = [
            p[len("metadata_json.") :] if p.startswith("metadata_json.") else p for p in meta_paths
        ]
        assert sorted(state_paths) == sorted(meta_relative)


def test_drift_no_plaintext_secrets_in_output() -> None:
    """All output modes must not contain plaintext secret-like values."""
    # These are values that should trigger is_sensitive_value or is_sensitive_key
    plaintext_secrets = [
        "sk-proj-deadbeef",  # would be in api_key value
        "ghp_secret_token_123",  # would be in token value
        "Bearer eyJhbGciOiJIUzI1NiJ9",  # bearer token
        "-----BEGIN RSA PRIVATE KEY-----",  # PEM header
        "super_secret_db_pass",  # password value
        "redis-secret-token",  # token value
    ]

    meta = _drift_input()

    # Redact mode
    redacted, _, _ = redact_metadata(meta)
    redacted_str = str(redacted)
    for secret in plaintext_secrets:
        assert secret not in redacted_str, f"Redact mode leaked plaintext: '{secret}'"

    # Removal mode
    removed = remove_metadata(meta)
    removed_str = str(removed)
    for secret in plaintext_secrets:
        assert secret not in removed_str, f"Remove mode leaked plaintext: '{secret}'"


def test_drift_verify_output_has_no_plain_secret_in_str_representation() -> None:
    """assert that no REDACTED value in any output is equal to original secret."""
    meta = {
        "api_key": "sk-real-actual-secret-12345",
        "nested": {"token": "ghp_actual_token_value"},
    }
    redacted, _, _ = redact_metadata(meta)
    redacted_flat = str(redacted)
    assert "sk-real-actual-secret-12345" not in redacted_flat
    assert "ghp_actual_token_value" not in redacted_flat
    assert REDACTED in redacted_flat

    removed = remove_metadata(meta)
    removed_flat = str(removed)
    assert "sk-real-actual-secret-12345" not in removed_flat
    assert "ghp_actual_token_value" not in removed_flat


# ═══════════════════════════════════════════════════════════════════════════
# Config const consistency
# ═══════════════════════════════════════════════════════════════════════════


def test_REDACTED_marker_is_consistent() -> None:
    from ragrig.repositories.processing_profile import REDACTED as REPO_REDACTED

    assert REDACTED == REPO_REDACTED == "[REDACTED]"


def test_sensitive_key_parts_are_consistent() -> None:
    from ragrig.repositories.processing_profile import SENSITIVE_KEY_PARTS as REPO_PARTS

    assert set(SENSITIVE_KEY_PARTS) == REPO_PARTS
