"""Tests for retrieval benchmark baseline integrity checker."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ragrig.retrieval_benchmark_integrity import (
    _check_metrics_hash,
    _compute_baseline_age_days,
    _parse_iso_datetime,
    _redact_secrets,
    check_integrity,
    generate_artifact,
    get_integrity_summary,
    main,
    summarize_artifact,
    summary_main,
)

pytestmark = [pytest.mark.unit]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_manifest(**overrides) -> dict:
    now = datetime.now(timezone.utc)
    manifest = {
        "schema_version": "1.0",
        "baseline_id": "test-baseline-id",
        "fixture_id": "test-fixture-id",
        "iteration_count": 5,
        "modes": ["dense", "hybrid", "rerank", "hybrid_rerank"],
        "metrics_hash": "85127e140d1d2bf6",
        "created_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator_version": "0.1.0",
    }
    manifest.update(overrides)
    return manifest


def _make_baseline() -> dict:
    return {
        "knowledge_base": "fixture-local",
        "queries": ["q1", "q2", "q3", "q4", "q5"],
        "iterations_per_query": 5,
        "database": "sqlite:///:memory: (temp)",
        "modes": [
            {
                "mode": "dense",
                "top_k": 5,
                "candidate_k": 20,
                "iterations": 25,
                "p50_latency_ms": 1.1,
                "p95_latency_ms": 1.4,
                "min_latency_ms": 1.0,
                "max_latency_ms": 5.0,
                "mean_latency_ms": 1.3,
                "result_count": 75,
                "degraded": False,
                "degraded_reason": "",
            },
            {
                "mode": "hybrid",
                "top_k": 5,
                "candidate_k": 20,
                "iterations": 25,
                "p50_latency_ms": 1.1,
                "p95_latency_ms": 1.5,
                "min_latency_ms": 1.1,
                "max_latency_ms": 1.5,
                "mean_latency_ms": 1.2,
                "result_count": 75,
                "degraded": False,
                "degraded_reason": "",
            },
            {
                "mode": "rerank",
                "top_k": 5,
                "candidate_k": 20,
                "iterations": 25,
                "p50_latency_ms": 1.1,
                "p95_latency_ms": 1.4,
                "min_latency_ms": 1.1,
                "max_latency_ms": 1.5,
                "mean_latency_ms": 1.2,
                "result_count": 75,
                "degraded": False,
                "degraded_reason": "",
            },
            {
                "mode": "hybrid_rerank",
                "top_k": 5,
                "candidate_k": 20,
                "iterations": 25,
                "p50_latency_ms": 1.1,
                "p95_latency_ms": 1.5,
                "min_latency_ms": 1.1,
                "max_latency_ms": 1.8,
                "mean_latency_ms": 1.2,
                "result_count": 75,
                "degraded": False,
                "degraded_reason": "",
            },
        ],
    }


# ── Redaction tests ──────────────────────────────────────────────────────────


class TestRedactSecrets:
    def test_redacts_secret_keys(self):
        obj = {"api_key": "secret123", "normal": "value"}
        result = _redact_secrets(obj)
        assert result["api_key"] == "[redacted]"
        assert result["normal"] == "value"

    def test_redacts_nested_secrets(self):
        obj = {"config": {"password": "hunter2", "host": "localhost"}}
        result = _redact_secrets(obj)
        assert result["config"]["password"] == "[redacted]"
        assert result["config"]["host"] == "localhost"

    def test_redacts_in_lists(self):
        obj = [{"token": "abc"}, {"token": "def"}]
        result = _redact_secrets(obj)
        assert result[0]["token"] == "[redacted]"
        assert result[1]["token"] == "[redacted]"

    def test_leaves_primitives_unchanged(self):
        assert _redact_secrets("hello") == "hello"
        assert _redact_secrets(42) == 42
        assert _redact_secrets(None) is None

    def test_no_raw_secrets_in_check_integrity_output(self, tmp_path):
        manifest = _make_manifest()
        manifest["api_key"] = "secret_value"
        baseline = _make_baseline()
        baseline["credentials"] = {"password": "hunter2"}

        manifest_path = tmp_path / "manifest.json"
        baseline_path = tmp_path / "baseline.json"
        manifest_path.write_text(json.dumps(manifest))
        baseline_path.write_text(json.dumps(baseline))

        result = check_integrity(manifest_path=manifest_path, baseline_path=baseline_path)
        result_str = json.dumps(result)
        assert "secret_value" not in result_str
        assert "hunter2" not in result_str


# ── ISO datetime parsing ─────────────────────────────────────────────────────


class TestParseIsoDatetime:
    def test_parses_z_suffix(self):
        dt = _parse_iso_datetime("2026-01-01T00:00:00Z")
        assert dt is not None
        assert dt.year == 2026

    def test_parses_offset(self):
        dt = _parse_iso_datetime("2026-01-01T00:00:00+00:00")
        assert dt is not None
        assert dt.year == 2026

    def test_returns_none_for_invalid(self):
        assert _parse_iso_datetime("not-a-date") is None
        assert _parse_iso_datetime("") is None
        assert _parse_iso_datetime(None) is None


# ── Baseline age computation ─────────────────────────────────────────────────


class TestComputeBaselineAgeDays:
    def test_returns_zero_for_now(self):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        age = _compute_baseline_age_days(now)
        assert age is not None
        assert 0 <= age < 0.1

    def test_returns_positive_for_past(self):
        past = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        age = _compute_baseline_age_days(past)
        assert age is not None
        assert 9.9 < age < 10.1

    def test_returns_none_for_invalid(self):
        assert _compute_baseline_age_days("invalid") is None


# ── Metrics hash check ───────────────────────────────────────────────────────


class TestCheckMetricsHash:
    def test_matches_for_identical_data(self):
        baseline = _make_baseline()
        from scripts.retrieval_benchmark_baseline_refresh import _compute_metrics_hash

        expected = _compute_metrics_hash(baseline)
        matches, computed = _check_metrics_hash(baseline, expected)
        assert matches is True
        assert computed == expected

    def test_mismatches_when_structure_changes(self):
        baseline = _make_baseline()
        from scripts.retrieval_benchmark_baseline_refresh import _compute_metrics_hash

        expected = _compute_metrics_hash(baseline)
        baseline["modes"][0]["result_count"] = 999
        matches, computed = _check_metrics_hash(baseline, expected)
        assert matches is False
        assert computed != expected


# ── check_integrity scenarios ────────────────────────────────────────────────


class TestCheckIntegrityValid:
    def test_pass_with_fresh_valid_manifest(self, tmp_path):
        manifest = _make_manifest()
        baseline = _make_baseline()

        manifest_path = tmp_path / "manifest.json"
        baseline_path = tmp_path / "baseline.json"
        manifest_path.write_text(json.dumps(manifest))
        baseline_path.write_text(json.dumps(baseline))

        result = check_integrity(manifest_path=manifest_path, baseline_path=baseline_path)

        assert result["overall_status"] == "pass"
        assert result["manifest_present"] is True
        assert result["baseline_present"] is True
        assert result["schema_version"] == "1.0"
        assert result["fixture_id"] == "test-fixture-id"
        assert result["iteration_count"] == 5
        assert result["metrics_hash_status"] == "match"
        assert result["reasons"] == []
        assert result["baseline_age"] is not None

    def test_degraded_when_stale(self, tmp_path):
        old = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest = _make_manifest(created_at=old)
        baseline = _make_baseline()

        manifest_path = tmp_path / "manifest.json"
        baseline_path = tmp_path / "baseline.json"
        manifest_path.write_text(json.dumps(manifest))
        baseline_path.write_text(json.dumps(baseline))

        result = check_integrity(
            manifest_path=manifest_path,
            baseline_path=baseline_path,
            max_age_days=30,
        )

        assert result["overall_status"] == "degraded"
        assert any("baseline_stale" in r for r in result["reasons"])

    def test_degraded_when_hash_mismatch(self, tmp_path):
        manifest = _make_manifest(metrics_hash="wronghash")
        baseline = _make_baseline()

        manifest_path = tmp_path / "manifest.json"
        baseline_path = tmp_path / "baseline.json"
        manifest_path.write_text(json.dumps(manifest))
        baseline_path.write_text(json.dumps(baseline))

        result = check_integrity(manifest_path=manifest_path, baseline_path=baseline_path)

        assert result["overall_status"] == "degraded"
        assert result["metrics_hash_status"] == "mismatch"
        assert any("metrics_hash_mismatch" in r for r in result["reasons"])

    def test_degraded_when_manifest_uses_legacy_fixture_id(self, tmp_path):
        manifest = _make_manifest(fixture_id="eb323cc73a16db53")
        baseline = _make_baseline()

        manifest_path = tmp_path / "manifest.json"
        baseline_path = tmp_path / "baseline.json"
        manifest_path.write_text(json.dumps(manifest))
        baseline_path.write_text(json.dumps(baseline))

        result = check_integrity(manifest_path=manifest_path, baseline_path=baseline_path)

        assert result["overall_status"] == "degraded"
        assert any("legacy_fixture_id" in reason for reason in result["reasons"])


class TestCheckIntegrityFailure:
    def test_failure_when_manifest_missing(self, tmp_path):
        baseline_path = tmp_path / "baseline.json"
        baseline_path.write_text(json.dumps(_make_baseline()))

        result = check_integrity(
            manifest_path=tmp_path / "nonexistent.json",
            baseline_path=baseline_path,
        )

        assert result["overall_status"] == "failure"
        assert result["manifest_present"] is False
        assert any("manifest_missing" in r for r in result["reasons"])

    def test_failure_when_manifest_corrupt(self, tmp_path):
        manifest_path = tmp_path / "manifest.json"
        baseline_path = tmp_path / "baseline.json"
        manifest_path.write_text("not json {[")
        baseline_path.write_text(json.dumps(_make_baseline()))

        result = check_integrity(manifest_path=manifest_path, baseline_path=baseline_path)

        assert result["overall_status"] == "failure"
        assert any("manifest_corrupt" in r for r in result["reasons"])

    def test_failure_when_baseline_missing(self, tmp_path):
        manifest = _make_manifest()
        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        result = check_integrity(
            manifest_path=manifest_path,
            baseline_path=tmp_path / "nonexistent.json",
        )

        assert result["overall_status"] == "failure"
        assert result["baseline_present"] is False
        assert any("baseline_missing" in r for r in result["reasons"])

    def test_failure_when_baseline_corrupt(self, tmp_path):
        manifest = _make_manifest()
        manifest_path = tmp_path / "manifest.json"
        baseline_path = tmp_path / "baseline.json"
        manifest_path.write_text(json.dumps(manifest))
        baseline_path.write_text("not json {[")

        result = check_integrity(manifest_path=manifest_path, baseline_path=baseline_path)

        assert result["overall_status"] == "failure"
        assert any("baseline_corrupt" in r for r in result["reasons"])

    def test_failure_when_schema_incompatible(self, tmp_path):
        manifest = _make_manifest(schema_version="2.0")
        baseline = _make_baseline()
        manifest_path = tmp_path / "manifest.json"
        baseline_path = tmp_path / "baseline.json"
        manifest_path.write_text(json.dumps(manifest))
        baseline_path.write_text(json.dumps(baseline))

        result = check_integrity(manifest_path=manifest_path, baseline_path=baseline_path)

        assert result["overall_status"] == "failure"
        assert any("schema_incompatible" in r for r in result["reasons"])

    def test_failure_when_manifest_is_not_object(self, tmp_path):
        manifest_path = tmp_path / "manifest.json"
        baseline_path = tmp_path / "baseline.json"
        manifest_path.write_text("[1, 2, 3]")
        baseline_path.write_text(json.dumps(_make_baseline()))

        result = check_integrity(manifest_path=manifest_path, baseline_path=baseline_path)

        assert result["overall_status"] == "failure"
        assert any("manifest_corrupt" in r for r in result["reasons"])

    def test_failure_when_baseline_is_not_object(self, tmp_path):
        manifest = _make_manifest()
        manifest_path = tmp_path / "manifest.json"
        baseline_path = tmp_path / "baseline.json"
        manifest_path.write_text(json.dumps(manifest))
        baseline_path.write_text("[1, 2, 3]")

        result = check_integrity(manifest_path=manifest_path, baseline_path=baseline_path)

        assert result["overall_status"] == "failure"
        assert any("baseline_corrupt" in r for r in result["reasons"])


class TestCheckIntegrityMaxAgeOverride:
    def test_older_threshold_avoids_stale(self, tmp_path):
        old = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest = _make_manifest(created_at=old)
        baseline = _make_baseline()

        manifest_path = tmp_path / "manifest.json"
        baseline_path = tmp_path / "baseline.json"
        manifest_path.write_text(json.dumps(manifest))
        baseline_path.write_text(json.dumps(baseline))

        result = check_integrity(
            manifest_path=manifest_path,
            baseline_path=baseline_path,
            max_age_days=60,
        )

        assert result["overall_status"] == "pass"
        assert not any("baseline_stale" in r for r in result["reasons"])


# ── generate_artifact ────────────────────────────────────────────────────────


class TestGenerateArtifact:
    def test_writes_to_output_path(self, tmp_path):
        manifest = _make_manifest()
        baseline = _make_baseline()

        manifest_path = tmp_path / "manifest.json"
        baseline_path = tmp_path / "baseline.json"
        output_path = tmp_path / "artifact.json"
        manifest_path.write_text(json.dumps(manifest))
        baseline_path.write_text(json.dumps(baseline))

        artifact = generate_artifact(
            output_path=output_path,
            manifest_path=manifest_path,
            baseline_path=baseline_path,
        )

        assert output_path.exists()
        assert artifact["artifact"] == "retrieval-benchmark-integrity"
        assert artifact["overall_status"] == "pass"

    def test_returns_without_writing_when_no_path(self, tmp_path):
        manifest = _make_manifest()
        baseline = _make_baseline()

        manifest_path = tmp_path / "manifest.json"
        baseline_path = tmp_path / "baseline.json"
        manifest_path.write_text(json.dumps(manifest))
        baseline_path.write_text(json.dumps(baseline))

        artifact = generate_artifact(
            manifest_path=manifest_path,
            baseline_path=baseline_path,
        )

        assert artifact["overall_status"] == "pass"


# ── get_integrity_summary ────────────────────────────────────────────────────


class TestGetIntegritySummary:
    def test_returns_summary_dict(self, tmp_path, monkeypatch):
        manifest = _make_manifest()
        baseline = _make_baseline()

        manifest_path = tmp_path / "manifest.json"
        baseline_path = tmp_path / "baseline.json"
        manifest_path.write_text(json.dumps(manifest))
        baseline_path.write_text(json.dumps(baseline))

        monkeypatch.setattr(
            "ragrig.retrieval_benchmark_integrity.DEFAULT_MANIFEST_PATH",
            manifest_path,
        )
        monkeypatch.setattr(
            "ragrig.retrieval_benchmark_integrity.DEFAULT_BASELINE_PATH",
            baseline_path,
        )

        summary = get_integrity_summary()

        assert summary["available"] is True
        assert summary["overall_status"] == "pass"
        assert "schema_version" in summary
        assert "baseline_age" in summary
        assert "fixture_id" in summary
        assert "iteration_count" in summary
        assert "metrics_hash_status" in summary
        assert "reasons" in summary
        assert "checked_at" in summary


# ── CLI main ─────────────────────────────────────────────────────────────────


class TestMain:
    def test_cli_returns_zero_on_pass(self, tmp_path, monkeypatch, capsys):
        manifest = _make_manifest()
        baseline = _make_baseline()

        manifest_path = tmp_path / "manifest.json"
        baseline_path = tmp_path / "baseline.json"
        manifest_path.write_text(json.dumps(manifest))
        baseline_path.write_text(json.dumps(baseline))

        output_path = tmp_path / "out.json"

        monkeypatch.setattr(
            "ragrig.retrieval_benchmark_integrity.DEFAULT_MANIFEST_PATH",
            manifest_path,
        )
        monkeypatch.setattr(
            "ragrig.retrieval_benchmark_integrity.DEFAULT_BASELINE_PATH",
            baseline_path,
        )
        monkeypatch.setattr(
            "sys.argv",
            [
                "ragrig.retrieval_benchmark_integrity",
                "--output",
                str(output_path),
                "--pretty",
            ],
        )

        code = main()
        assert code == 0
        assert output_path.exists()
        data = json.loads(output_path.read_text())
        assert data["overall_status"] == "pass"

    def test_cli_returns_one_on_failure(self, tmp_path, monkeypatch, capsys):
        output_path = tmp_path / "out.json"

        monkeypatch.setattr(
            "sys.argv",
            [
                "ragrig.retrieval_benchmark_integrity",
                "--output",
                str(output_path),
                "--manifest",
                str(tmp_path / "missing.json"),
                "--baseline",
                str(tmp_path / "missing.json"),
            ],
        )

        code = main()
        assert code == 1
        assert output_path.exists()
        data = json.loads(output_path.read_text())
        assert data["overall_status"] == "failure"

    def test_cli_respects_env_max_age(self, tmp_path, monkeypatch):
        old = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest = _make_manifest(created_at=old)
        baseline = _make_baseline()

        manifest_path = tmp_path / "manifest.json"
        baseline_path = tmp_path / "baseline.json"
        manifest_path.write_text(json.dumps(manifest))
        baseline_path.write_text(json.dumps(baseline))

        output_path = tmp_path / "out.json"

        monkeypatch.setenv("BENCHMARK_BASELINE_MAX_AGE_DAYS", "60")
        monkeypatch.setattr(
            "sys.argv",
            [
                "ragrig.retrieval_benchmark_integrity",
                "--output",
                str(output_path),
                "--manifest",
                str(manifest_path),
                "--baseline",
                str(baseline_path),
            ],
        )

        code = main()
        assert code == 0
        data = json.loads(output_path.read_text())
        assert data["overall_status"] == "pass"

    def test_cli_ignores_invalid_env_max_age(self, tmp_path, monkeypatch):
        old = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest = _make_manifest(created_at=old)
        baseline = _make_baseline()

        manifest_path = tmp_path / "manifest.json"
        baseline_path = tmp_path / "baseline.json"
        manifest_path.write_text(json.dumps(manifest))
        baseline_path.write_text(json.dumps(baseline))

        output_path = tmp_path / "out.json"

        monkeypatch.setenv("BENCHMARK_BASELINE_MAX_AGE_DAYS", "not-a-number")
        monkeypatch.setattr(
            "sys.argv",
            [
                "ragrig.retrieval_benchmark_integrity",
                "--output",
                str(output_path),
                "--manifest",
                str(manifest_path),
                "--baseline",
                str(baseline_path),
            ],
        )

        code = main()
        assert code == 0
        data = json.loads(output_path.read_text())
        assert data["overall_status"] == "degraded"

    def test_cli_respects_arg_max_age(self, tmp_path, monkeypatch):
        old = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
        manifest = _make_manifest(created_at=old)
        baseline = _make_baseline()

        manifest_path = tmp_path / "manifest.json"
        baseline_path = tmp_path / "baseline.json"
        manifest_path.write_text(json.dumps(manifest))
        baseline_path.write_text(json.dumps(baseline))

        output_path = tmp_path / "out.json"

        monkeypatch.setattr(
            "sys.argv",
            [
                "ragrig.retrieval_benchmark_integrity",
                "--output",
                str(output_path),
                "--manifest",
                str(manifest_path),
                "--baseline",
                str(baseline_path),
                "--max-age-days",
                "60",
            ],
        )

        code = main()
        assert code == 0
        data = json.loads(output_path.read_text())
        assert data["overall_status"] == "pass"

    def test_cli_uses_default_output_path(self, tmp_path, monkeypatch):
        manifest = _make_manifest()
        baseline = _make_baseline()

        manifest_path = tmp_path / "manifest.json"
        baseline_path = tmp_path / "baseline.json"
        manifest_path.write_text(json.dumps(manifest))
        baseline_path.write_text(json.dumps(baseline))

        output_path = tmp_path / "artifacts" / "retrieval-benchmark-integrity.json"

        monkeypatch.setenv("BENCHMARK_INTEGRITY_ARTIFACT_PATH", str(output_path))
        monkeypatch.setattr(
            "sys.argv",
            [
                "ragrig.retrieval_benchmark_integrity",
                "--manifest",
                str(manifest_path),
                "--baseline",
                str(baseline_path),
            ],
        )

        code = main()
        assert code == 0
        assert output_path.exists()


# ── summarize_artifact tests ──────────────────────────────────────────


_PASS_JSON = json.dumps(
    {
        "overall_status": "pass",
        "reasons": [],
        "baseline_age": 12.5,
        "fixture_id": "news_qa_2026",
        "iteration_count": 3,
        "metrics_hash_status": "match",
        "schema_version": "1.0",
        "generated_at": "2026-05-12T00:00:00Z",
        "manifest_present": True,
        "baseline_present": True,
    }
)
_DEGRADED_JSON = json.dumps(
    {
        "overall_status": "degraded",
        "reasons": ["baseline_stale: age 45d exceeds 30d"],
        "baseline_age": 45.0,
        "fixture_id": "f1",
        "iteration_count": 1,
        "metrics_hash_status": "match",
        "schema_version": "1.0",
        "generated_at": "2026-05-12T00:00:00Z",
        "manifest_present": True,
        "baseline_present": True,
    }
)
_FAILURE_JSON = json.dumps(
    {
        "overall_status": "failure",
        "reasons": ["manifest_missing: file not found"],
        "baseline_age": None,
        "fixture_id": None,
        "iteration_count": 0,
        "metrics_hash_status": None,
        "schema_version": None,
        "generated_at": "unknown",
        "manifest_present": False,
        "baseline_present": False,
    }
)
_SIMPLE_PASS_JSON = json.dumps(
    {
        "overall_status": "pass",
        "reasons": [],
        "baseline_age": 1.0,
        "fixture_id": "f1",
        "iteration_count": 1,
        "metrics_hash_status": "match",
        "schema_version": "1.0",
        "generated_at": "2026-05-12T00:00:00Z",
        "manifest_present": True,
        "baseline_present": True,
    }
)


class TestSummarizeArtifact:
    def test_summary_pass(self, tmp_path):
        ap = tmp_path / "artifact.json"
        ap.write_text(_PASS_JSON)
        summary = summarize_artifact(ap, output_dir=tmp_path)
        assert summary["overall_status"] == "pass"
        assert summary["fixture_id"] == "news_qa_2026"
        assert summary["iteration_count"] == 3
        assert summary["metrics_hash_status"] == "match"
        assert summary["baseline_age"] == "12.5d"
        assert Path(summary["json_report_path"]).exists()
        assert Path(summary["md_report_path"]).exists()

    def test_summary_degraded(self, tmp_path):
        ap = tmp_path / "artifact.json"
        ap.write_text(_DEGRADED_JSON)
        summary = summarize_artifact(ap, output_dir=tmp_path)
        assert summary["overall_status"] == "degraded"
        assert len(summary["reasons"]) == 1
        md = Path(summary["md_report_path"]).read_text()
        assert "degraded" in md
        assert "baseline_stale" in md

    def test_summary_failure(self, tmp_path):
        ap = tmp_path / "artifact.json"
        ap.write_text(_FAILURE_JSON)
        summary = summarize_artifact(ap, output_dir=tmp_path)
        assert summary["overall_status"] == "failure"
        md = Path(summary["md_report_path"]).read_text()
        assert "failure" in md

    def test_summary_missing_artifact(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Artifact not found"):
            summarize_artifact(tmp_path / "nonexistent.json")

    def test_summary_corrupt_artifact(self, tmp_path):
        ap = tmp_path / "corrupt.json"
        ap.write_text("{bad json}")
        with pytest.raises(ValueError, match="Corrupt artifact"):
            summarize_artifact(ap)

    def test_summary_not_a_dict(self, tmp_path):
        ap = tmp_path / "array.json"
        ap.write_text("[]")
        with pytest.raises(ValueError, match="not a JSON object"):
            summarize_artifact(ap)

    def test_summary_missing_fields(self, tmp_path):
        ap = tmp_path / "minimal.json"
        ap.write_text('{"overall_status":"pass"}')
        summary = summarize_artifact(ap, output_dir=tmp_path)
        assert summary["fixture_id"] == "unknown"
        assert summary["baseline_age"] == "unknown"

    def test_summary_main_cli_pass(self, tmp_path, monkeypatch):
        ap = tmp_path / "artifact.json"
        ap.write_text(_SIMPLE_PASS_JSON)
        monkeypatch.setattr("sys.argv", ["prog", str(ap), "--output-dir", str(tmp_path)])
        code = summary_main()
        assert code == 0

    def test_summary_main_cli_failure(self, tmp_path, monkeypatch):
        ap = tmp_path / "artifact.json"
        ap.write_text(_FAILURE_JSON)
        monkeypatch.setattr("sys.argv", ["prog", str(ap), "--output-dir", str(tmp_path)])
        code = summary_main()
        assert code == 1

    def test_main_delegates_to_summary(self, tmp_path, monkeypatch):
        ap = tmp_path / "artifact.json"
        ap.write_text(_SIMPLE_PASS_JSON)
        monkeypatch.setattr(
            "sys.argv",
            ["prog", "--summary", str(ap), "--output-dir", str(tmp_path)],
        )
        code = main()
        assert code == 0
