"""Cross-layer contract tests for sanitizer summary consistency.

Verifies that the same fixture produces identical SanitizationSummary
fields across all four layers:

1. sanitizer  – ragrig.processing_profile.sanitizer
2. repository – ragrig.repositories.processing_profile
3. model      – ragrig.processing_profile.models
4. API        – ProcessingProfile.to_api_dict()

Fixtures covered:
- no-op (clean metadata)
- non-string key
- depth truncation
- secret-like (api_key, bearer token, PEM)
- remove/redact (mixed nested)
"""

from __future__ import annotations

from typing import Any

import pytest

from ragrig.processing_profile.models import ProcessingProfile, TaskType, _sanitize_metadata
from ragrig.processing_profile.sanitizer import (
    DEGRADED,
    REDACTED,
    redact_metadata,
    remove_metadata,
)
from ragrig.repositories.processing_profile import (
    _sanitize_metadata_json,
    _sanitize_state,
)

pytestmark = pytest.mark.unit


# ═══════════════════════════════════════════════════════════════════════════
# Shared fixtures
# ═══════════════════════════════════════════════════════════════════════════


FIXTURE_NO_OP: dict[str, Any] = {
    "version": 2,
    "tags": ["a", "b"],
    "config": {"timeout": 30},
    "nil": None,
    "empty_list": [],
    "empty_dict": {},
}

FIXTURE_NON_STRING_KEY: dict[Any, Any] = {
    123: "numeric-key-value",
    None: "none-key-value",
    ("tuple", "key"): "tuple-key-value",
    "normal": "ok",
    "api_key": "secret",
}

FIXTURE_DEPTH_TRUNCATION: dict[str, Any] = {
    "a": {"b": {"c": {"d": {"e": "deep-value"}}}},
}

FIXTURE_SECRET_LIKE: dict[str, Any] = {
    "api_key": "sk-proj-deadbeef",
    "auth": {
        "token": "ghp_secret_token_123",
        "headers": {"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"},
    },
    "config": {"version": 2, "timeout": 30, "tags": ["prod", "us-east-1"]},
    "secrets": [
        {"name": "db", "password": "super_secret_db_pass"},
        {"name": "redis", "token": "redis-secret-token"},
        {"name": "cache", "normal": "no-auth"},
    ],
    "certs": {"key": "-----BEGIN RSA PRIVATE KEY-----\nMIIEpA...\n-----END RSA PRIVATE KEY-----"},
}

FIXTURE_REMOVE_REDACT_MIXED: dict[str, Any] = {
    "api_key": "sk-123",
    "nested": {"token": "t1", "name": "ok"},
    "items": [{"secret": "s1", "id": 1}, {"secret": "s2", "id": 2}],
    "normal": "fine",
    42: "non-string-key",
    "deep": {
        "level2": {
            "level3": {"password": "deep-pass", "host": "localhost"},
        }
    },
}

# Ordered list for parametrisation
CONTRACT_FIXTURES: list[tuple[str, dict[str, Any]]] = [
    ("no_op", FIXTURE_NO_OP),
    ("non_string_key", FIXTURE_NON_STRING_KEY),
    ("depth_truncation", FIXTURE_DEPTH_TRUNCATION),
    ("secret_like", FIXTURE_SECRET_LIKE),
    ("remove_redact_mixed", FIXTURE_REMOVE_REDACT_MIXED),
]

# All summary fields that must be present in every summary dict.
REQUIRED_SUMMARY_FIELDS: set[str] = {
    "schema_version",
    "redacted_count",
    "removed_count",
    "degraded_count",
    "non_string_key_count",
    "max_depth_exceeded",
}


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _api_dict_for_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Build an API dict using the real model layer."""
    profile = ProcessingProfile(
        profile_id="test.contract",
        extension=".test",
        task_type=TaskType.CHUNK,
        display_name="Contract Test",
        description="Test.",
        provider="deterministic-local",
        metadata=metadata,
    )
    return profile.to_api_dict()


def _assert_summary_fields_present(summary_dict: dict[str, Any], source: str) -> None:
    missing = REQUIRED_SUMMARY_FIELDS - set(summary_dict.keys())
    assert not missing, f"{source}: missing summary fields {missing}"


def _assert_no_raw_secrets_in_output(output: dict[str, Any], source: str) -> None:
    """Ensure no plaintext secrets leak into the output dict."""
    forbidden = [
        "sk-proj-deadbeef",
        "ghp_secret_token_123",
        "super_secret_db_pass",
        "redis-secret-token",
        "deep-pass",
        "eyJhbGciOiJIUzI1NiJ9",
        "MIIEpA",
    ]
    output_str = str(output)
    for frag in forbidden:
        assert frag not in output_str, f"{source}: leaked raw secret fragment {frag!r}"


# ═══════════════════════════════════════════════════════════════════════════
# Remove-mode consistency: sanitizer, model, API
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("fixture_name,fixture", CONTRACT_FIXTURES)
def test_remove_mode_sanitizer_equals_model(fixture_name: str, fixture: dict[str, Any]) -> None:
    """Shared remove_metadata and model _sanitize_metadata must agree."""
    sanitizer_result, sanitizer_summary = remove_metadata(fixture)
    model_result, model_summary = _sanitize_metadata(fixture)

    assert sanitizer_result == model_result, (
        f"[{fixture_name}] sanitized dict mismatch:\n"
        f"  sanitizer: {sanitizer_result!r}\n"
        f"  model:     {model_result!r}"
    )
    assert sanitizer_summary == model_summary, (
        f"[{fixture_name}] summary mismatch:\n"
        f"  sanitizer: {sanitizer_summary!r}\n"
        f"  model:     {model_summary!r}"
    )


@pytest.mark.parametrize("fixture_name,fixture", CONTRACT_FIXTURES)
def test_remove_mode_api_equals_sanitizer(fixture_name: str, fixture: dict[str, Any]) -> None:
    """API to_api_dict must produce the same remove-mode summary as shared sanitizer."""
    _, sanitizer_summary = remove_metadata(fixture)
    api_dict = _api_dict_for_metadata(fixture)
    api_summary_dict = api_dict.get("_sanitization_summary", {})

    _assert_summary_fields_present(api_summary_dict, f"API[{fixture_name}]")

    assert api_summary_dict["schema_version"] == sanitizer_summary.schema_version
    assert api_summary_dict["removed_count"] == sanitizer_summary.removed_count
    assert api_summary_dict["degraded_count"] == sanitizer_summary.degraded_count
    assert api_summary_dict["non_string_key_count"] == sanitizer_summary.non_string_key_count
    assert api_summary_dict["max_depth_exceeded"] == sanitizer_summary.max_depth_exceeded
    assert api_summary_dict["redacted_count"] == 0, (
        f"API remove-mode should never redact; "
        f"got redacted_count={api_summary_dict['redacted_count']}"
    )

    _assert_no_raw_secrets_in_output(api_dict, f"API[{fixture_name}]")


# ═══════════════════════════════════════════════════════════════════════════
# Redact-mode consistency: sanitizer, repository
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("fixture_name,fixture", CONTRACT_FIXTURES)
def test_redact_mode_sanitizer_equals_repository(
    fixture_name: str, fixture: dict[str, Any]
) -> None:
    """Shared redact_metadata and repository _sanitize_metadata_json must agree."""
    sanitizer_result, sanitizer_count, sanitizer_paths, sanitizer_summary = redact_metadata(
        fixture, prefix="metadata_json"
    )
    repo_result, repo_count, repo_paths, repo_summary = _sanitize_metadata_json(fixture)

    assert sanitizer_result == repo_result, (
        f"[{fixture_name}] redacted dict mismatch:\n"
        f"  sanitizer: {sanitizer_result!r}\n"
        f"  repo:      {repo_result!r}"
    )
    assert sanitizer_count == repo_count, (
        f"[{fixture_name}] redaction count mismatch: "
        f"sanitizer={sanitizer_count} vs repo={repo_count}"
    )
    assert sorted(sanitizer_paths) == sorted(repo_paths), (
        f"[{fixture_name}] redaction paths mismatch:\n"
        f"  sanitizer: {sorted(sanitizer_paths)}\n"
        f"  repo:      {sorted(repo_paths)}"
    )
    assert sanitizer_summary == repo_summary, (
        f"[{fixture_name}] summary mismatch:\n"
        f"  sanitizer: {sanitizer_summary!r}\n"
        f"  repo:      {repo_summary!r}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# State sanitizer consistency
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("fixture_name,fixture", CONTRACT_FIXTURES)
def test_redact_state_summary_matches_metadata_redact(
    fixture_name: str, fixture: dict[str, Any]
) -> None:
    """_sanitize_state must include a summary whose metadata counts match redact_metadata."""
    state = {
        "profile_id": "test.contract",
        "metadata_json": fixture,
        "display_name": "Test",
    }
    sanitized_state = _sanitize_state(state)
    state_summary = sanitized_state.get("_sanitization_summary", {})

    _assert_summary_fields_present(state_summary, f"state[{fixture_name}]")

    # When metadata has redactions, the state summary aggregates them
    if fixture:
        _, _count, _paths, meta_summary = redact_metadata(fixture)
        assert state_summary["redacted_count"] == meta_summary.redacted_count, (
            f"[{fixture_name}] state redacted_count mismatch: "
            f"state={state_summary['redacted_count']} vs meta={meta_summary.redacted_count}"
        )
        assert state_summary["degraded_count"] == meta_summary.degraded_count
        assert state_summary["non_string_key_count"] == meta_summary.non_string_key_count
        assert state_summary["max_depth_exceeded"] == meta_summary.max_depth_exceeded

    _assert_no_raw_secrets_in_output(sanitized_state, f"state[{fixture_name}]")


# ═══════════════════════════════════════════════════════════════════════════
# Depth-truncation specific contract
# ═══════════════════════════════════════════════════════════════════════════


def test_depth_truncation_all_layers() -> None:
    """A fixture that exceeds max_depth must trigger degraded_count>0 and
    max_depth_exceeded=True in every layer, without raising RecursionError."""
    # Build a dict that exceeds DEFAULT_MAX_DEPTH (100)
    deep_meta: dict[str, object] = {"bottom": "secret"}
    for _ in range(150):
        deep_meta = {"level": deep_meta}

    # 1. sanitizer redact
    redacted, _count, _paths, redact_summary = redact_metadata(deep_meta)
    assert redact_summary.max_depth_exceeded is True
    assert redact_summary.degraded_count >= 1
    assert DEGRADED in str(redacted)

    # 2. sanitizer remove
    removed, remove_summary = remove_metadata(deep_meta)
    assert remove_summary.max_depth_exceeded is True
    assert remove_summary.degraded_count >= 1

    # 3. repository redact
    repo_redacted, repo_count, _repo_paths, repo_summary = _sanitize_metadata_json(deep_meta)
    assert repo_summary.max_depth_exceeded is True
    assert repo_summary.degraded_count >= 1

    # 4. model remove
    model_removed, model_summary = _sanitize_metadata(deep_meta)
    assert model_summary.max_depth_exceeded is True
    assert model_summary.degraded_count >= 1

    # 5. API
    api_dict = _api_dict_for_metadata(deep_meta)
    api_summary = api_dict.get("_sanitization_summary", {})
    assert api_summary["max_depth_exceeded"] is True
    assert api_summary["degraded_count"] >= 1

    # 6. state
    state = {"profile_id": "test", "metadata_json": deep_meta}
    state_sanitized = _sanitize_state(state)
    state_summary = state_sanitized.get("_sanitization_summary", {})
    assert state_summary["max_depth_exceeded"] is True
    assert state_summary["degraded_count"] >= 1

    # Cross-layer agreement on degraded_count for remove mode
    assert remove_summary.degraded_count == model_summary.degraded_count
    assert model_summary.degraded_count == api_summary["degraded_count"]

    # Cross-layer agreement on degraded_count for redact mode
    assert redact_summary.degraded_count == repo_summary.degraded_count


# ═══════════════════════════════════════════════════════════════════════════
# Non-string-key specific contract
# ═══════════════════════════════════════════════════════════════════════════


def test_non_string_key_all_layers() -> None:
    """Non-string keys must be counted identically across all layers."""
    fixture = {
        123: "numeric",
        None: "none",
        ("tuple",): "tuple",
        "normal": "ok",
        "api_key": "secret",
    }

    _, _, _, redact_summary = redact_metadata(fixture)
    removed, remove_summary = remove_metadata(fixture)
    _, _, _, repo_summary = _sanitize_metadata_json(fixture)
    _, model_summary = _sanitize_metadata(fixture)
    api_dict = _api_dict_for_metadata(fixture)
    api_summary = api_dict.get("_sanitization_summary", {})

    # All layers see 3 non-string keys
    assert redact_summary.non_string_key_count == 3
    assert remove_summary.non_string_key_count == 3
    assert repo_summary.non_string_key_count == 3
    assert model_summary.non_string_key_count == 3
    assert api_summary["non_string_key_count"] == 3

    # Non-string keys are preserved in redact and remove modes
    assert redact_summary.redacted_count == 1  # api_key redacted
    assert remove_summary.removed_count == 1  # api_key removed
    assert repo_summary.redacted_count == 1
    assert model_summary.removed_count == 1
    assert api_summary["removed_count"] == 1

    # Verify the non-string keys are actually present in outputs
    assert 123 in removed
    assert None in removed
    assert ("tuple",) in removed


# ═══════════════════════════════════════════════════════════════════════════
# Secret-like specific contract
# ═══════════════════════════════════════════════════════════════════════════


def test_secret_like_all_layers() -> None:
    """Secret-like fixtures must not leak raw values in any layer."""
    fixture = FIXTURE_SECRET_LIKE

    redacted, redact_count, _paths, redact_summary = redact_metadata(fixture)
    removed, remove_summary = remove_metadata(fixture)
    repo_redacted, repo_count, _repo_paths, repo_summary = _sanitize_metadata_json(fixture)
    model_removed, model_summary = _sanitize_metadata(fixture)
    api_dict = _api_dict_for_metadata(fixture)
    api_summary = api_dict.get("_sanitization_summary", {})

    # No plaintext secrets in any output
    _assert_no_raw_secrets_in_output(redacted, "redact")
    _assert_no_raw_secrets_in_output(removed, "remove")
    _assert_no_raw_secrets_in_output(repo_redacted, "repo_redact")
    _assert_no_raw_secrets_in_output(model_removed, "model_remove")
    _assert_no_raw_secrets_in_output(api_dict, "api")

    # Redact counts agree between sanitizer and repository
    assert redact_count == repo_count
    assert redact_summary.redacted_count == repo_summary.redacted_count

    # Remove counts agree between sanitizer, model, API
    assert remove_summary.removed_count == model_summary.removed_count
    assert model_summary.removed_count == api_summary["removed_count"]

    # api_key is redacted in redact mode
    assert redacted["api_key"] == REDACTED
    assert repo_redacted["api_key"] == REDACTED

    # api_key is removed in remove mode
    assert "api_key" not in removed
    assert "api_key" not in model_removed
    assert "api_key" not in api_dict["metadata"]


# ═══════════════════════════════════════════════════════════════════════════
# No-op specific contract
# ═══════════════════════════════════════════════════════════════════════════


def test_no_op_all_layers_zero_counts() -> None:
    """Clean metadata must produce zero counts in every layer."""
    fixture = FIXTURE_NO_OP

    _, redact_count, _paths, redact_summary = redact_metadata(fixture)
    removed, remove_summary = remove_metadata(fixture)
    _, repo_count, _repo_paths, repo_summary = _sanitize_metadata_json(fixture)
    _, model_summary = _sanitize_metadata(fixture)

    # API clean metadata now always includes _sanitization_summary
    # for cross-layer contract consistency; we assert all layers here.
    assert redact_count == 0
    assert redact_summary.redacted_count == 0
    assert redact_summary.removed_count == 0
    assert redact_summary.degraded_count == 0
    assert redact_summary.non_string_key_count == 0
    assert redact_summary.max_depth_exceeded is False

    assert remove_summary.redacted_count == 0
    assert remove_summary.removed_count == 0
    assert remove_summary.degraded_count == 0
    assert remove_summary.non_string_key_count == 0
    assert remove_summary.max_depth_exceeded is False

    assert repo_count == 0
    assert repo_summary.redacted_count == 0
    assert model_summary.removed_count == 0

    # Data is preserved unchanged in no-op case
    assert removed == fixture


# ═══════════════════════════════════════════════════════════════════════════
# Summary schema contract
# ═══════════════════════════════════════════════════════════════════════════


def test_summary_schema_version_unchanged() -> None:
    """schema_version must be '1.0' in every layer."""
    fixture = {"api_key": "sk-test"}

    _, _, _, redact_summary = redact_metadata(fixture)
    _, remove_summary = remove_metadata(fixture)
    _, _, _, repo_summary = _sanitize_metadata_json(fixture)
    _, model_summary = _sanitize_metadata(fixture)

    assert redact_summary.schema_version == "1.0"
    assert remove_summary.schema_version == "1.0"
    assert repo_summary.schema_version == "1.0"
    assert model_summary.schema_version == "1.0"


def test_summary_to_dict_never_contains_secrets() -> None:
    """SanitizationSummary.to_dict() must never contain raw values."""
    fixture = {"api_key": "sk-real-secret-12345", "password": "hunter2"}

    _, _, _, redact_summary = redact_metadata(fixture)
    _, remove_summary = remove_metadata(fixture)

    for summary in (redact_summary, remove_summary):
        d = summary.to_dict()
        d_str = str(d)
        assert "sk-real-secret-12345" not in d_str
        assert "hunter2" not in d_str
        assert REDACTED not in d_str
        assert DEGRADED not in d_str
        # All required fields present
        assert REQUIRED_SUMMARY_FIELDS.issubset(d.keys())


# ═══════════════════════════════════════════════════════════════════════════
# API layer specific contract
# ═══════════════════════════════════════════════════════════════════════════


def test_api_dict_always_includes_summary() -> None:
    """to_api_dict always includes _sanitization_summary for cross-layer
    contract consistency.  Clean metadata produces zeros; dirty metadata
    produces non-zero counts."""
    clean = ProcessingProfile(
        profile_id="clean",
        extension=".test",
        task_type=TaskType.CHUNK,
        display_name="Clean",
        description="Clean.",
        provider="deterministic-local",
        metadata={"version": 1},
    )
    dirty = ProcessingProfile(
        profile_id="dirty",
        extension=".test",
        task_type=TaskType.CHUNK,
        display_name="Dirty",
        description="Dirty.",
        provider="deterministic-local",
        metadata={"api_key": "sk-test"},
    )

    clean_dict = clean.to_api_dict()
    dirty_dict = dirty.to_api_dict()

    assert "_sanitization_summary" in clean_dict
    assert clean_dict["_sanitization_summary"]["removed_count"] == 0
    assert "_sanitization_summary" in dirty_dict
    assert dirty_dict["_sanitization_summary"]["removed_count"] == 1


def test_api_dict_metadata_never_contains_sensitive_keys() -> None:
    """The metadata field in an API dict must never contain sensitive keys."""
    fixture = {
        "api_key": "sk-test",
        "nested": {"password": "secret", "host": "localhost"},
        "list": [{"token": "t1", "name": "a"}],
    }
    api_dict = _api_dict_for_metadata(fixture)
    meta = api_dict["metadata"]

    assert "api_key" not in meta
    assert "password" not in meta.get("nested", {})
    assert "token" not in meta.get("list", [{}])[0]
    assert meta["nested"]["host"] == "localhost"
    assert meta["list"][0]["name"] == "a"


# ═══════════════════════════════════════════════════════════════════════════
# Regression: no RecursionError on extreme depth
# ═══════════════════════════════════════════════════════════════════════════


def test_extreme_depth_no_recursion_error_all_layers() -> None:
    """Inputs with >1500 nesting levels must not raise RecursionError in any layer."""
    deep: dict[str, object] = {"bottom": "secret"}
    for _ in range(1500):
        deep = {"level": deep}

    # Each call must complete without raising
    redact_metadata(deep)
    remove_metadata(deep)
    _sanitize_metadata_json(deep)
    _sanitize_metadata(deep)
    _api_dict_for_metadata(deep)
    _sanitize_state({"profile_id": "test", "metadata_json": deep})


# ═══════════════════════════════════════════════════════════════════════════
# Contract matrix helper
# ═══════════════════════════════════════════════════════════════════════════


def test_contract_matrix_can_be_built() -> None:
    """A contract matrix can be programmatically built from the fixtures
    and layers.  This is the programmatic equivalent of the CI artifact."""
    matrix: list[dict[str, Any]] = []
    layers = [
        ("sanitizer_redact", lambda f: redact_metadata(f)[3].to_dict()),
        ("sanitizer_remove", lambda f: remove_metadata(f)[1].to_dict()),
        ("repository_redact", lambda f: _sanitize_metadata_json(f)[3].to_dict()),
        ("model_remove", lambda f: _sanitize_metadata(f)[1].to_dict()),
    ]
    for fixture_name, fixture in CONTRACT_FIXTURES:
        for layer_name, layer_fn in layers:
            summary = layer_fn(fixture)
            _assert_summary_fields_present(summary, f"{layer_name}/{fixture_name}")
            matrix.append(
                {
                    "fixture": fixture_name,
                    "layer": layer_name,
                    "schema_version": summary["schema_version"],
                    "redacted_count": summary["redacted_count"],
                    "removed_count": summary["removed_count"],
                    "degraded_count": summary["degraded_count"],
                    "non_string_key_count": summary["non_string_key_count"],
                    "max_depth_exceeded": summary["max_depth_exceeded"],
                }
            )

    # Every fixture must have exactly 4 rows
    for fixture_name, _ in CONTRACT_FIXTURES:
        rows = [r for r in matrix if r["fixture"] == fixture_name]
        assert len(rows) == 4, f"Expected 4 layers for {fixture_name}, got {len(rows)}"

    # All schema versions identical
    versions = {r["schema_version"] for r in matrix}
    assert versions == {"1.0"}, f"Inconsistent schema versions: {versions}"

    # Print a human-readable matrix (visible with pytest -s)
    print("\n── Sanitizer Cross-Layer Contract Matrix ──")
    print(f"{'Fixture':<22} {'Layer':<22} {'R':>3} {'M':>3} {'D':>3} {'N':>3} {'X':>3}")
    print("-" * 64)
    for r in matrix:
        print(
            f"{r['fixture']:<22} {r['layer']:<22} "
            f"{r['redacted_count']:>3} {r['removed_count']:>3} "
            f"{r['degraded_count']:>3} {r['non_string_key_count']:>3} "
            f"{1 if r['max_depth_exceeded'] else 0:>3}"
        )
