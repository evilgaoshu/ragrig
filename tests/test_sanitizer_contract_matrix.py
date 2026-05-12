"""Tests for the sanitizer contract matrix artifact and Console badge.

Covers:
- matrix artifact creation and schema
- pass/degraded/failure states
- missing/corrupt artifact handling
- secret-like leak interception
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ragrig.web_console import get_sanitizer_contract_status
from scripts.sanitizer_contract_check import (
    FORBIDDEN_FRAGMENTS,
    _assert_no_raw_secrets,
    _build_artifact,
    _build_callsite_matrix,
)

pytestmark = pytest.mark.unit


# ── Helpers ─────────────────────────────────────────────────────────────────


def _sample_sites(registered: bool = True) -> list[dict[str, Any]]:
    return [
        {
            "module": "ragrig.repositories.processing_profile",
            "function": "_sanitize_metadata_json",
            "line": 42,
            "registered": registered,
        },
        {
            "module": "ragrig.processing_profile.models",
            "function": "_sanitize_metadata",
            "line": 100,
            "registered": registered,
        },
        {
            "module": "ragrig.processing_profile.sanitizer",
            "function": "redact_metadata",
            "line": 200,
            "registered": True,  # canonical always registered
        },
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Matrix structure tests
# ═══════════════════════════════════════════════════════════════════════════


class TestMatrixStructure:
    def test_build_callsite_matrix_has_required_fields(self) -> None:
        sites = _sample_sites(registered=True)
        matrix = _build_callsite_matrix(sites, [], [], True)

        assert len(matrix) == len(sites)
        for row in matrix:
            assert "callsite" in row
            assert "layer" in row
            assert "registered" in row
            assert "summary_fields_ok" in row
            assert "status" in row
            assert "reason" in row

    def test_build_callsite_matrix_registered_pass(self) -> None:
        sites = _sample_sites(registered=True)
        matrix = _build_callsite_matrix(sites, [], [], True)

        for row in matrix:
            assert row["registered"] is True
            assert row["status"] == "pass"
            assert row["reason"] == ""

    def test_build_callsite_matrix_unregistered_failure(self) -> None:
        sites = _sample_sites(registered=False)
        matrix = _build_callsite_matrix(sites, [], [], True)

        for row in matrix:
            if not row["registered"]:
                assert row["status"] == "unregistered"
                assert "not in REGISTERED_CALL_SITES" in row["reason"]

    def test_build_callsite_matrix_summary_errors_add_rows(self) -> None:
        sites = _sample_sites(registered=True)
        summary_errors = ["Missing field: redacted_count"]
        matrix = _build_callsite_matrix(sites, summary_errors, [], True)

        # Should have original rows + synthetic failure rows
        assert len(matrix) > len(sites)
        failure_rows = [r for r in matrix if r["callsite"] == "_check_summary_fields"]
        assert len(failure_rows) == 1
        assert failure_rows[0]["status"] == "failure"
        assert failure_rows[0]["summary_fields_ok"] is False

    def test_build_callsite_matrix_dup_errors_add_rows(self) -> None:
        sites = _sample_sites(registered=True)
        dup_errors = ["Potential duplicate in ragrig.foo"]
        matrix = _build_callsite_matrix(sites, [], dup_errors, True)

        failure_rows = [r for r in matrix if r["callsite"] == "_check_no_duplicate_impls"]
        assert len(failure_rows) == 1
        assert failure_rows[0]["status"] == "failure"

    def test_build_callsite_matrix_fixture_failure(self) -> None:
        sites = _sample_sites(registered=True)
        matrix = _build_callsite_matrix(sites, [], [], False)

        failure_rows = [r for r in matrix if r["callsite"] == "fixture_smoke_contract"]
        assert len(failure_rows) == 1
        assert failure_rows[0]["status"] == "failure"


# ═══════════════════════════════════════════════════════════════════════════
# Artifact structure tests
# ═══════════════════════════════════════════════════════════════════════════


class TestArtifactStructure:
    def test_artifact_has_required_top_level_fields(self) -> None:
        sites = _sample_sites(registered=True)
        artifact = _build_artifact(sites, [], [], True, 0)

        assert artifact["artifact"] == "sanitizer-contract-matrix"
        assert artifact["version"] == "1.0.0"
        assert "generated_at" in artifact
        assert "status" in artifact
        assert "exit_code" in artifact
        assert "totals" in artifact
        assert "matrix" in artifact

    def test_artifact_status_pass(self) -> None:
        sites = _sample_sites(registered=True)
        artifact = _build_artifact(sites, [], [], True, 0)

        assert artifact["status"] == "pass"
        assert artifact["exit_code"] == 0

    def test_artifact_status_failure_on_exit_code(self) -> None:
        sites = _sample_sites(registered=True)
        artifact = _build_artifact(sites, ["error"], [], True, 1)

        assert artifact["status"] == "failure"
        assert artifact["exit_code"] == 1

    def test_artifact_status_degraded_on_matrix_failure(self) -> None:
        sites = _sample_sites(registered=False)
        # exit_code could be 0 but matrix has failures -> degraded
        artifact = _build_artifact(sites, [], [], True, 0)

        assert artifact["status"] == "degraded"

    def test_artifact_totals_pass(self) -> None:
        sites = _sample_sites(registered=True)
        artifact = _build_artifact(sites, [], [], True, 0)

        t = artifact["totals"]
        assert t["callsites"] == len(sites)
        assert t["registered"] == len(sites)
        assert t["unregistered"] == 0
        assert t["summary_fields_ok"] is True
        assert t["no_duplicate_impls"] is True
        assert t["fixture_ok"] is True

    def test_artifact_json_serializable(self) -> None:
        sites = _sample_sites(registered=True)
        artifact = _build_artifact(sites, [], [], True, 0)

        serialized = json.dumps(artifact, indent=2, ensure_ascii=False)
        deserialized = json.loads(serialized)

        assert deserialized["artifact"] == artifact["artifact"]
        assert len(deserialized["matrix"]) == len(artifact["matrix"])


# ═══════════════════════════════════════════════════════════════════════════
# Console badge tests (via get_sanitizer_contract_status)
# ═══════════════════════════════════════════════════════════════════════════


class TestConsoleBadge:
    def _patch_path(self, tmp_path: Path, name: str) -> Any:
        """Return context manager helper via direct attribute swap."""
        import ragrig.web_console as _wc

        return _wc

    def test_missing_artifact_returns_failure(self) -> None:
        import ragrig.web_console as wc

        original = wc._SANITIZER_CONTRACT_MATRIX_PATH
        try:
            wc._SANITIZER_CONTRACT_MATRIX_PATH = Path("/tmp/nonexistent_contract_matrix.json")
            result = get_sanitizer_contract_status()
            assert result["available"] is False
            assert result["status"] == "failure"
            assert "not found" in result["reason"]
        finally:
            wc._SANITIZER_CONTRACT_MATRIX_PATH = original

    def test_corrupt_artifact_returns_failure(self, tmp_path: Path) -> None:
        import ragrig.web_console as wc

        corrupt_path = tmp_path / "sanitizer-contract-matrix.json"
        corrupt_path.write_text("not valid json", encoding="utf-8")

        original = wc._SANITIZER_CONTRACT_MATRIX_PATH
        try:
            wc._SANITIZER_CONTRACT_MATRIX_PATH = corrupt_path
            result = get_sanitizer_contract_status()
            assert result["available"] is False
            assert result["status"] == "failure"
        finally:
            wc._SANITIZER_CONTRACT_MATRIX_PATH = original

    def test_invalid_artifact_type_returns_failure(self, tmp_path: Path) -> None:
        import ragrig.web_console as wc

        bad_path = tmp_path / "sanitizer-contract-matrix.json"
        bad_path.write_text(
            json.dumps({"artifact": "wrong-type", "status": "pass"}), encoding="utf-8"
        )

        original = wc._SANITIZER_CONTRACT_MATRIX_PATH
        try:
            wc._SANITIZER_CONTRACT_MATRIX_PATH = bad_path
            result = get_sanitizer_contract_status()
            assert result["available"] is False
            assert result["status"] == "failure"
            assert "invalid artifact type" in result["reason"]
        finally:
            wc._SANITIZER_CONTRACT_MATRIX_PATH = original

    def test_valid_artifact_returns_pass(self, tmp_path: Path) -> None:
        import ragrig.web_console as wc

        sites = _sample_sites(registered=True)
        artifact = _build_artifact(sites, [], [], True, 0)

        valid_path = tmp_path / "sanitizer-contract-matrix.json"
        valid_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

        original = wc._SANITIZER_CONTRACT_MATRIX_PATH
        try:
            wc._SANITIZER_CONTRACT_MATRIX_PATH = valid_path
            result = get_sanitizer_contract_status()
            assert result["available"] is True
            assert result["status"] == "pass"
            assert result["registered_callsite_count"] == len(sites)
            assert "report_path" in result
        finally:
            wc._SANITIZER_CONTRACT_MATRIX_PATH = original

    def test_valid_artifact_has_required_console_fields(self, tmp_path: Path) -> None:
        import ragrig.web_console as wc

        sites = _sample_sites(registered=True)
        artifact = _build_artifact(sites, [], [], True, 0)

        valid_path = tmp_path / "sanitizer-contract-matrix.json"
        valid_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")

        original = wc._SANITIZER_CONTRACT_MATRIX_PATH
        try:
            wc._SANITIZER_CONTRACT_MATRIX_PATH = valid_path
            result = get_sanitizer_contract_status()
            for field in (
                "available",
                "status",
                "exit_code",
                "registered_callsite_count",
                "report_path",
                "generated_at",
            ):
                assert field in result, f"Missing field: {field}"
        finally:
            wc._SANITIZER_CONTRACT_MATRIX_PATH = original


# ═══════════════════════════════════════════════════════════════════════════
# Secret safety tests
# ═══════════════════════════════════════════════════════════════════════════


class TestSecretSafety:
    def test_artifact_rejects_secret_fragments(self) -> None:
        """_build_artifact must raise on secret-like content in output."""
        for fragment in FORBIDDEN_FRAGMENTS:
            with pytest.raises(RuntimeError, match="raw secret fragment"):
                _assert_no_raw_secrets(
                    {"status": f"something with {fragment}"},
                    "test",
                )

    def test_artifact_allows_clean_content(self) -> None:
        """Clean content must not raise."""
        clean = {
            "status": "pass",
            "matrix": [{"callsite": "foo:bar", "status": "pass", "reason": ""}],
        }
        _assert_no_raw_secrets(clean, "test")  # must not raise

    def test_artifact_detects_nested_secret(self) -> None:
        """Deeply nested secret fragments must also be detected."""
        nested = {
            "metadata": {
                "deep": {
                    "value": "ghp_something_secret",
                }
            }
        }
        with pytest.raises(RuntimeError, match="raw secret fragment"):
            _assert_no_raw_secrets(nested, "test")

    def test_artifact_secret_in_reason_field_blocked(self) -> None:
        """Secret-like content in the 'reason' field must be blocked."""
        matrix_row = {
            "callsite": "foo:bar",
            "reason": "contains sk-proj-deadbeef in error",
        }
        with pytest.raises(RuntimeError, match="raw secret fragment"):
            _assert_no_raw_secrets(matrix_row, "test")
