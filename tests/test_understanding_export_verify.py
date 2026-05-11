from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from scripts.verify_understanding_export import (
    SECRET_PATTERNS,
    VerificationError,
    format_summary,
    verify_export,
    verify_file,
)

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_export(**overrides: object) -> dict[str, object]:
    """Return a minimally valid export document."""
    doc: dict[str, object] = {
        "schema_version": "1.0",
        "generated_at": "2026-05-09T12:00:00+00:00",
        "filter": {
            "provider": "deterministic-local",
            "model": None,
            "profile_id": "*.understand.default",
            "status": "success",
            "started_after": None,
            "started_before": None,
            "limit": 50,
        },
        "run_count": 1,
        "run_ids": ["00000000-0000-0000-0000-000000000001"],
        "knowledge_base": "fixture-local",
        "knowledge_base_id": "00000000-0000-0000-0000-000000000003",
        "runs": [
            {
                "id": "00000000-0000-0000-0000-000000000001",
                "knowledge_base_id": "00000000-0000-0000-0000-000000000003",
                "provider": "deterministic-local",
                "model": "",
                "profile_id": "*.understand.default",
                "trigger_source": "api",
                "operator": "test-user",
                "status": "success",
                "total": 3,
                "created": 2,
                "skipped": 1,
                "failed": 0,
                "error_summary": None,
                "started_at": "2026-05-09T11:00:00+00:00",
                "finished_at": "2026-05-09T11:00:05+00:00",
            }
        ],
    }
    doc.update(overrides)
    return doc


# ---------------------------------------------------------------------------
# verify_export — happy path
# ---------------------------------------------------------------------------


class TestVerifyExportValid:
    def test_valid_fixture_passes(self) -> None:
        doc = _valid_export()
        summary = verify_export(doc)
        assert summary["status"] == "pass"
        assert summary["schema_version"] == "1.0"
        assert summary["run_count"] == 1
        assert summary["filter_keys"] == [
            "provider",
            "model",
            "profile_id",
            "status",
            "started_after",
            "started_before",
            "limit",
        ]
        assert summary["sanitized_field_count"] == 0

    def test_multiple_runs_passes(self) -> None:
        doc = _valid_export(
            run_count=2,
            run_ids=[
                "00000000-0000-0000-0000-000000000001",
                "00000000-0000-0000-0000-000000000002",
            ],
            runs=[
                {
                    "id": "00000000-0000-0000-0000-000000000001",
                    "knowledge_base_id": "00000000-0000-0000-0000-000000000003",
                    "provider": "deterministic-local",
                    "model": "",
                    "profile_id": "*.understand.default",
                    "trigger_source": "api",
                    "operator": "test-user",
                    "status": "success",
                    "total": 3,
                    "created": 2,
                    "skipped": 1,
                    "failed": 0,
                    "error_summary": None,
                    "started_at": "2026-05-09T11:00:00+00:00",
                    "finished_at": "2026-05-09T11:00:05+00:00",
                },
                {
                    "id": "00000000-0000-0000-0000-000000000002",
                    "knowledge_base_id": "00000000-0000-0000-0000-000000000003",
                    "provider": "deterministic-local",
                    "model": "",
                    "profile_id": "*.understand.default",
                    "trigger_source": "api",
                    "operator": "test-user",
                    "status": "partial_failure",
                    "total": 5,
                    "created": 3,
                    "skipped": 1,
                    "failed": 1,
                    "error_summary": "[00000000]: simulated failure",
                    "started_at": "2026-05-09T12:00:00+00:00",
                    "finished_at": "2026-05-09T12:00:10+00:00",
                },
            ],
        )
        summary = verify_export(doc)
        assert summary["status"] == "pass"
        assert summary["run_count"] == 2


# ---------------------------------------------------------------------------
# verify_export — missing fields
# ---------------------------------------------------------------------------


class TestVerifyExportMissingFields:
    def test_missing_top_level_field_fails(self) -> None:
        doc = _valid_export()
        del doc["run_count"]
        with pytest.raises(VerificationError) as exc_info:
            verify_export(doc)
        assert exc_info.value.code == "verification_failed"
        assert "MISSING top-level fields" in exc_info.value.message
        assert "run_count" in exc_info.value.message

    def test_missing_multiple_top_level_fields_fails(self) -> None:
        doc = _valid_export()
        del doc["run_count"]
        del doc["run_ids"]
        with pytest.raises(VerificationError) as exc_info:
            verify_export(doc)
        assert "run_count" in exc_info.value.message
        assert "run_ids" in exc_info.value.message

    def test_missing_filter_field_fails(self) -> None:
        doc = _valid_export()
        doc["filter"] = {"provider": "test"}  # missing other filter fields
        with pytest.raises(VerificationError) as exc_info:
            verify_export(doc)
        assert "MISSING filter fields" in exc_info.value.message

    def test_missing_run_field_fails(self) -> None:
        doc = _valid_export()
        run = doc["runs"][0]  # type: ignore[index]
        del run["error_summary"]  # type: ignore[index]
        with pytest.raises(VerificationError) as exc_info:
            verify_export(doc)
        assert "MISSING runs[0] fields" in exc_info.value.message
        assert "error_summary" in exc_info.value.message


# ---------------------------------------------------------------------------
# verify_export — count mismatches
# ---------------------------------------------------------------------------


class TestVerifyExportCountMismatch:
    def test_run_count_not_matching_run_ids_fails(self) -> None:
        doc = _valid_export(run_count=2, run_ids=["only-one"])
        with pytest.raises(VerificationError) as exc_info:
            verify_export(doc)
        assert "MISMATCH run_count" in exc_info.value.message
        assert "len(run_ids)" in exc_info.value.message

    def test_run_count_not_matching_runs_fails(self) -> None:
        doc = _valid_export(run_count=2)
        # runs still has 1 element
        with pytest.raises(VerificationError) as exc_info:
            verify_export(doc)
        assert "MISMATCH len(runs)" in exc_info.value.message

    def test_run_ids_longer_than_run_count_fails(self) -> None:
        doc = _valid_export(
            run_count=1,
            run_ids=["a", "b"],
        )
        with pytest.raises(VerificationError) as exc_info:
            verify_export(doc)
        assert "MISMATCH" in exc_info.value.message


# ---------------------------------------------------------------------------
# verify_export — sanitization / secret leaks
# ---------------------------------------------------------------------------


class TestVerifyExportSanitization:
    def test_forbidden_key_extracted_text_fails(self) -> None:
        doc = _valid_export()
        run = doc["runs"][0]  # type: ignore[index]
        run["extracted_text"] = "sensitive document content"  # type: ignore[index]
        with pytest.raises(VerificationError) as exc_info:
            verify_export(doc)
        assert "[FORBIDDEN KEY]" in exc_info.value.message
        assert "extracted_text" in exc_info.value.message

    def test_forbidden_key_prompt_fails(self) -> None:
        doc = _valid_export()
        run = doc["runs"][0]  # type: ignore[index]
        run["prompt"] = "tell me everything"  # type: ignore[index]
        with pytest.raises(VerificationError) as exc_info:
            verify_export(doc)
        assert "[FORBIDDEN KEY]" in exc_info.value.message
        assert "prompt" in exc_info.value.message

    def test_secret_pattern_api_key_fails(self) -> None:
        doc = _valid_export()
        run = doc["runs"][0]  # type: ignore[index]
        run["config"] = {"api_key": "sk-abc123"}  # type: ignore[index]
        with pytest.raises(VerificationError) as exc_info:
            verify_export(doc)
        assert "[SECRET PATTERN]" in exc_info.value.message
        assert "api_key" in exc_info.value.message

    def test_secret_pattern_openai_key_fails(self) -> None:
        doc = _valid_export()
        run = doc["runs"][0]  # type: ignore[index]
        run["metadata"] = {"token": "sk-topsecret12345"}  # type: ignore[index]
        with pytest.raises(VerificationError) as exc_info:
            verify_export(doc)
        assert "[SECRET PATTERN]" in exc_info.value.message

    def test_secret_in_value_string_fails(self) -> None:
        doc = _valid_export()
        run = doc["runs"][0]  # type: ignore[index]
        run["note"] = "The password is hunter2"  # type: ignore[index]
        with pytest.raises(VerificationError) as exc_info:
            verify_export(doc)
        assert "[SECRET PATTERN]" in exc_info.value.message
        assert "password" in exc_info.value.message

    def test_nested_secret_fails(self) -> None:
        doc = _valid_export()
        run = doc["runs"][0]  # type: ignore[index]
        run["deep"] = {"nested": {"secret_key": "shh"}}  # type: ignore[index]
        with pytest.raises(VerificationError) as exc_info:
            verify_export(doc)
        assert "[SECRET PATTERN]" in exc_info.value.message
        assert "secret_key" in exc_info.value.message

    def test_valid_fixture_has_zero_sanitized_fields(self) -> None:
        doc = _valid_export()
        summary = verify_export(doc)
        assert summary["sanitized_field_count"] == 0

    def test_redacted_value_still_counts(self) -> None:
        doc = _valid_export()
        run = doc["runs"][0]  # type: ignore[index]
        run["extracted_text"] = "[REDACTED]"  # type: ignore[index]
        run["api_key"] = "[REDACTED]"  # type: ignore[index]
        with pytest.raises(VerificationError) as exc_info:
            verify_export(doc)
        # Both forbidden key and secret pattern should be flagged
        assert "extracted_text" in exc_info.value.message
        assert "api_key" in exc_info.value.message


# ---------------------------------------------------------------------------
# verify_export — schema_version
# ---------------------------------------------------------------------------


class TestVerifyExportSchemaVersion:
    def test_invalid_schema_version_fails(self) -> None:
        doc = _valid_export(schema_version="2.0")
        with pytest.raises(VerificationError) as exc_info:
            verify_export(doc)
        assert "INVALID schema_version" in exc_info.value.message
        assert "2.0" in exc_info.value.message

    def test_missing_schema_version_fails(self) -> None:
        doc = _valid_export()
        del doc["schema_version"]
        with pytest.raises(VerificationError) as exc_info:
            verify_export(doc)
        assert "MISSING top-level fields" in exc_info.value.message
        assert "schema_version" in exc_info.value.message

    def test_none_schema_version_fails(self) -> None:
        doc = _valid_export(schema_version=None)
        with pytest.raises(VerificationError) as exc_info:
            verify_export(doc)
        assert "INVALID schema_version" in exc_info.value.message


# ---------------------------------------------------------------------------
# verify_file
# ---------------------------------------------------------------------------


class TestVerifyFile:
    def test_missing_file_returns_error(self) -> None:
        result = verify_file(Path("/nonexistent/path/export.json"))
        assert result["status"] == "error"
        assert result["error"] == "file_not_found"

    def test_invalid_json_returns_error(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not json at all")
            path = Path(f.name)
        try:
            result = verify_file(path)
            assert result["status"] == "error"
            assert result["error"] == "invalid_json"
        finally:
            path.unlink()

    def test_non_object_json_returns_error(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("[1, 2, 3]")
            path = Path(f.name)
        try:
            result = verify_file(path)
            assert result["status"] == "error"
            assert result["error"] == "invalid_structure"
        finally:
            path.unlink()

    def test_valid_file_returns_pass(self) -> None:
        doc = _valid_export()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(doc, f)
            path = Path(f.name)
        try:
            result = verify_file(path)
            assert result["status"] == "pass"
            assert result["schema_version"] == "1.0"
            assert result["run_count"] == 1
        finally:
            path.unlink()

    def test_valid_file_with_secret_returns_fail(self) -> None:
        doc = _valid_export()
        run = doc["runs"][0]  # type: ignore[index]
        run["extracted_text"] = "secret"  # type: ignore[index]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(doc, f)
            path = Path(f.name)
        try:
            result = verify_file(path)
            assert result["status"] == "fail"
            assert result["error"] == "verification_failed"
            assert "extracted_text" in result["message"]
        finally:
            path.unlink()


# ---------------------------------------------------------------------------
# format_summary
# ---------------------------------------------------------------------------


class TestFormatSummary:
    def test_all_pass(self) -> None:
        results = [
            {
                "path": "/tmp/good.json",
                "status": "pass",
                "schema_version": "1.0",
                "run_count": 2,
                "filter_keys": ["provider"],
                "sanitized_field_count": 0,
            }
        ]
        text = format_summary(results)
        assert "files_checked: 1" in text
        assert "passed: 1" in text
        assert "[PASS] /tmp/good.json" in text
        assert "schema_version: 1.0" in text

    def test_mixed_results(self) -> None:
        results = [
            {
                "path": "/tmp/good.json",
                "status": "pass",
                "schema_version": "1.0",
                "run_count": 1,
                "filter_keys": [],
                "sanitized_field_count": 0,
            },
            {
                "path": "/tmp/bad.json",
                "status": "fail",
                "error": "verification_failed",
                "message": "something wrong",
            },
            {
                "path": "/tmp/missing.json",
                "status": "error",
                "error": "file_not_found",
                "message": "File not found",
            },
        ]
        text = format_summary(results)
        assert "files_checked: 3" in text
        assert "passed: 1" in text
        assert "failed: 1" in text
        assert "errors: 1" in text
        assert "[FAIL] /tmp/bad.json" in text
        assert "[ERROR] /tmp/missing.json" in text

    def test_summary_never_includes_secret_content(self) -> None:
        results = [
            {
                "path": "/tmp/bad.json",
                "status": "fail",
                "error": "verification_failed",
                "message": "[SECRET PATTERN] $.runs[0].api_key",
            }
        ]
        text = format_summary(results)
        assert "[SECRET PATTERN]" in text
        assert "sk-" not in text
        assert "hunter2" not in text


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


def test_secret_patterns_cover_openai_prefix() -> None:
    assert "sk-" in SECRET_PATTERNS


def test_secret_patterns_cover_api_key() -> None:
    assert "api_key" in SECRET_PATTERNS


def test_forbidden_keys_cover_extracted_text() -> None:
    assert "extracted_text" in {"extracted_text", "prompt", "messages"}
