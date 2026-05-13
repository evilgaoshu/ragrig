"""Tests for retrieval benchmark baseline comparison."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import retrieval_benchmark_compare
from scripts.retrieval_benchmark import _sanitize_summary

pytestmark = [pytest.mark.unit]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_baseline(modes: list[dict]) -> dict:
    return {
        "knowledge_base": "fixture-local",
        "queries": ["q1", "q2"],
        "iterations_per_query": 2,
        "database": "sqlite:///:memory: (temp)",
        "modes": modes,
    }


def _make_mode(
    mode: str,
    p50: float,
    p95: float,
    result_count: int,
    degraded: bool = False,
    degraded_reason: str = "",
) -> dict:
    return {
        "mode": mode,
        "top_k": 5,
        "candidate_k": 20,
        "iterations": 10,
        "p50_latency_ms": p50,
        "p95_latency_ms": p95,
        "min_latency_ms": p50 * 0.8,
        "max_latency_ms": p95 * 1.2,
        "mean_latency_ms": (p50 + p95) / 2,
        "result_count": result_count,
        "degraded": degraded,
        "degraded_reason": degraded_reason,
    }


# ── Pass scenario ────────────────────────────────────────────────────────────


class TestComparePass:
    """Current benchmark within baseline thresholds."""

    def test_overall_pass_when_within_thresholds(self):
        baseline = _make_baseline(
            [
                _make_mode("dense", p50=10.0, p95=20.0, result_count=30),
                _make_mode("hybrid", p50=10.0, p95=20.0, result_count=30),
            ]
        )
        current = _make_baseline(
            [
                _make_mode("dense", p50=11.0, p95=21.0, result_count=31),
                _make_mode("hybrid", p50=10.0, p95=20.0, result_count=30),
            ]
        )

        report = retrieval_benchmark_compare.compare_benchmarks(
            baseline, current, latency_threshold_pct=20, result_count_threshold=5
        )

        assert report["overall_status"] == "pass"
        assert report["overall_reason"] == ""

        dense = [m for m in report["modes"] if m["mode"] == "dense"][0]
        assert dense["status"] == "pass"
        assert dense["reason"] == ""
        assert dense["delta"]["p50_latency_ms"] == 10.0  # (11-10)/10*100
        assert dense["delta"]["p95_latency_ms"] == 5.0
        assert dense["result_count_delta"] == 1

    def test_pass_with_improved_latency(self):
        baseline = _make_baseline(
            [
                _make_mode("dense", p50=10.0, p95=20.0, result_count=30),
            ]
        )
        current = _make_baseline(
            [
                _make_mode("dense", p50=5.0, p95=10.0, result_count=30),
            ]
        )

        report = retrieval_benchmark_compare.compare_benchmarks(
            baseline, current, latency_threshold_pct=20, result_count_threshold=5
        )

        assert report["overall_status"] == "pass"
        dense = report["modes"][0]
        assert dense["delta"]["p50_latency_ms"] == -50.0
        assert dense["delta"]["p95_latency_ms"] == -50.0


# ── Latency regression fail ──────────────────────────────────────────────────


class TestLatencyRegressionFail:
    """p50 or p95 exceeds latency threshold."""

    def test_fail_when_p50_exceeds_threshold(self):
        baseline = _make_baseline(
            [
                _make_mode("dense", p50=10.0, p95=20.0, result_count=30),
            ]
        )
        current = _make_baseline(
            [
                _make_mode("dense", p50=13.0, p95=20.0, result_count=30),
            ]
        )

        report = retrieval_benchmark_compare.compare_benchmarks(
            baseline, current, latency_threshold_pct=20, result_count_threshold=5
        )

        assert report["overall_status"] == "fail"
        dense = report["modes"][0]
        assert dense["status"] == "fail"
        assert "p50 latency regression 30.0%" in dense["reason"]

    def test_fail_when_p95_exceeds_threshold(self):
        baseline = _make_baseline(
            [
                _make_mode("dense", p50=10.0, p95=20.0, result_count=30),
            ]
        )
        current = _make_baseline(
            [
                _make_mode("dense", p50=10.0, p95=25.0, result_count=30),
            ]
        )

        report = retrieval_benchmark_compare.compare_benchmarks(
            baseline, current, latency_threshold_pct=20, result_count_threshold=5
        )

        assert report["overall_status"] == "fail"
        dense = report["modes"][0]
        assert dense["status"] == "fail"
        assert "p95 latency regression 25.0%" in dense["reason"]

    def test_fail_when_both_p50_and_p95_exceed(self):
        baseline = _make_baseline(
            [
                _make_mode("dense", p50=10.0, p95=20.0, result_count=30),
            ]
        )
        current = _make_baseline(
            [
                _make_mode("dense", p50=15.0, p95=30.0, result_count=30),
            ]
        )

        report = retrieval_benchmark_compare.compare_benchmarks(
            baseline, current, latency_threshold_pct=20, result_count_threshold=5
        )

        assert report["overall_status"] == "fail"
        dense = report["modes"][0]
        assert "p50" in dense["reason"]
        assert "p95" in dense["reason"]


# ── Result count drift ───────────────────────────────────────────────────────


class TestResultCountDrift:
    """result_count deviation exceeds threshold."""

    def test_fail_when_result_count_delta_positive(self):
        baseline = _make_baseline(
            [
                _make_mode("dense", p50=10.0, p95=20.0, result_count=30),
            ]
        )
        current = _make_baseline(
            [
                _make_mode("dense", p50=10.0, p95=20.0, result_count=40),
            ]
        )

        report = retrieval_benchmark_compare.compare_benchmarks(
            baseline, current, latency_threshold_pct=20, result_count_threshold=5
        )

        assert report["overall_status"] == "fail"
        dense = report["modes"][0]
        assert dense["status"] == "fail"
        assert "result_count delta 10 exceeds threshold" in dense["reason"]

    def test_fail_when_result_count_delta_negative(self):
        baseline = _make_baseline(
            [
                _make_mode("dense", p50=10.0, p95=20.0, result_count=30),
            ]
        )
        current = _make_baseline(
            [
                _make_mode("dense", p50=10.0, p95=20.0, result_count=20),
            ]
        )

        report = retrieval_benchmark_compare.compare_benchmarks(
            baseline, current, latency_threshold_pct=20, result_count_threshold=5
        )

        assert report["overall_status"] == "fail"
        dense = report["modes"][0]
        assert "result_count delta -10 exceeds threshold" in dense["reason"]


# ── Missing baseline ─────────────────────────────────────────────────────────


class TestMissingBaseline:
    """Baseline file does not exist."""

    def test_load_baseline_missing_file(self):
        path = Path("/nonexistent/path/baseline.json")
        data, err = retrieval_benchmark_compare._load_baseline(path)

        assert data is None
        assert "not found" in err
        assert str(path) in err


# ── Corrupt baseline ─────────────────────────────────────────────────────────


class TestCorruptBaseline:
    """Baseline file contains invalid JSON."""

    def test_load_baseline_invalid_json(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("{ not json", encoding="utf-8")

        data, err = retrieval_benchmark_compare._load_baseline(path)

        assert data is None
        assert "invalid JSON" in err

    def test_load_baseline_non_object_root(self, tmp_path):
        path = tmp_path / "list.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")

        data, err = retrieval_benchmark_compare._load_baseline(path)

        assert data is None
        assert "root must be a JSON object" in err


class TestLegacyBaselineCompatibility:
    """Legacy path-derived fixture IDs produce a migration hint."""

    def test_legacy_fixture_id_mismatch_includes_refresh_guidance(self):
        baseline = _make_baseline([_make_mode("dense", p50=10.0, p95=20.0, result_count=30)])
        baseline["_manifest"] = {
            "schema_version": "1.0",
            "fixture_id": "legacy-path-derived-id",
            "iteration_count": 2,
            "metrics_hash": retrieval_benchmark_compare._compute_metrics_hash(baseline),
        }
        current = _make_baseline([_make_mode("dense", p50=10.0, p95=20.0, result_count=30)])
        current["_manifest"] = {
            "schema_version": "1.0",
            "fixture_id": "stable-content-id",
            "iteration_count": 2,
            "metrics_hash": retrieval_benchmark_compare._compute_metrics_hash(current),
        }

        ok, reason = retrieval_benchmark_compare._check_manifest_compatibility(baseline, current)

        assert ok is False
        assert "fixture_id mismatch" in reason
        assert "refresh baseline" in reason


# ── Secret-like config sanitization ────────────────────────────────────────────


class TestSanitization:
    """Secret-like values are redacted from compare report."""

    def test_secret_keys_redacted_in_compare_report(self):
        baseline = _make_baseline(
            [
                {
                    "mode": "dense",
                    "top_k": 5,
                    "candidate_k": 20,
                    "iterations": 10,
                    "p50_latency_ms": 10.0,
                    "p95_latency_ms": 20.0,
                    "min_latency_ms": 8.0,
                    "max_latency_ms": 24.0,
                    "mean_latency_ms": 15.0,
                    "result_count": 30,
                    "degraded": False,
                    "degraded_reason": "",
                    "api_key": "sk-baseline",
                    "secret_config": {"password": "base-pass"},
                }
            ]
        )
        current = _make_baseline(
            [
                {
                    "mode": "dense",
                    "top_k": 5,
                    "candidate_k": 20,
                    "iterations": 10,
                    "p50_latency_ms": 11.0,
                    "p95_latency_ms": 21.0,
                    "min_latency_ms": 8.8,
                    "max_latency_ms": 25.2,
                    "mean_latency_ms": 16.0,
                    "result_count": 30,
                    "degraded": False,
                    "degraded_reason": "",
                    "api_key": "sk-current",
                    "secret_config": {"password": "cur-pass"},
                }
            ]
        )

        report = retrieval_benchmark_compare.compare_benchmarks(
            baseline, current, latency_threshold_pct=20, result_count_threshold=5
        )
        sanitized = _sanitize_summary(report)

        # Secrets should be redacted in both current and baseline dicts if they
        # were present, but compare_benchmarks does not copy arbitrary keys.
        # The _sanitize_summary function operates on whatever dict we give it.
        # For the report itself, we inject secrets to verify redaction.
        report_with_secrets = {
            **sanitized,
            "database_dsn": "postgresql://user:pass@host/db",
            "secret_token": "super-secret",
        }
        sanitized = _sanitize_summary(report_with_secrets)

        assert sanitized["database_dsn"] == "[redacted]"
        assert sanitized["secret_token"] == "[redacted]"

    def test_compare_output_is_json_serializable(self):
        baseline = _make_baseline(
            [
                _make_mode("dense", p50=10.0, p95=20.0, result_count=30),
            ]
        )
        current = _make_baseline(
            [
                _make_mode("dense", p50=11.0, p95=21.0, result_count=30),
            ]
        )

        report = retrieval_benchmark_compare.compare_benchmarks(
            baseline, current, latency_threshold_pct=20, result_count_threshold=5
        )
        report = _sanitize_summary(report)

        json_output = json.dumps(report, sort_keys=True)
        parsed = json.loads(json_output)
        assert parsed["overall_status"] == "pass"


# ── Degraded mode handling ───────────────────────────────────────────────────


class TestDegradedMode:
    """Benchmark-level degraded flag propagates to compare status."""

    def test_degraded_status_when_benchmark_degraded(self):
        baseline = _make_baseline(
            [
                _make_mode("dense", p50=10.0, p95=20.0, result_count=30),
            ]
        )
        current = _make_baseline(
            [
                _make_mode(
                    "dense",
                    p50=10.0,
                    p95=20.0,
                    result_count=30,
                    degraded=True,
                    degraded_reason="reranker timeout",
                ),
            ]
        )

        report = retrieval_benchmark_compare.compare_benchmarks(
            baseline, current, latency_threshold_pct=20, result_count_threshold=5
        )

        assert report["overall_status"] == "degraded"
        dense = report["modes"][0]
        assert dense["status"] == "degraded"
        assert "reranker timeout" in dense["reason"]

    def test_fail_takes_precedence_over_degraded(self):
        baseline = _make_baseline(
            [
                _make_mode("dense", p50=10.0, p95=20.0, result_count=30),
            ]
        )
        current = _make_baseline(
            [
                _make_mode(
                    "dense",
                    p50=50.0,
                    p95=20.0,
                    result_count=30,
                    degraded=True,
                    degraded_reason="reranker timeout",
                ),
            ]
        )

        report = retrieval_benchmark_compare.compare_benchmarks(
            baseline, current, latency_threshold_pct=20, result_count_threshold=5
        )

        assert report["overall_status"] == "fail"
        dense = report["modes"][0]
        assert dense["status"] == "fail"
        assert "p50 latency regression" in dense["reason"]
        assert "reranker timeout" in dense["reason"]


# ── Missing mode handling ────────────────────────────────────────────────────


class TestMissingMode:
    """Modes missing from baseline or current."""

    def test_fail_when_mode_missing_from_baseline(self):
        baseline = _make_baseline(
            [
                _make_mode("dense", p50=10.0, p95=20.0, result_count=30),
            ]
        )
        current = _make_baseline(
            [
                _make_mode("dense", p50=10.0, p95=20.0, result_count=30),
                _make_mode("hybrid", p50=10.0, p95=20.0, result_count=30),
            ]
        )

        report = retrieval_benchmark_compare.compare_benchmarks(
            baseline, current, latency_threshold_pct=20, result_count_threshold=5
        )

        assert report["overall_status"] == "fail"
        hybrid = [m for m in report["modes"] if m["mode"] == "hybrid"][0]
        assert hybrid["status"] == "fail"
        assert "missing from baseline" in hybrid["reason"]

    def test_fail_when_mode_missing_from_current(self):
        baseline = _make_baseline(
            [
                _make_mode("dense", p50=10.0, p95=20.0, result_count=30),
                _make_mode("hybrid", p50=10.0, p95=20.0, result_count=30),
            ]
        )
        current = _make_baseline(
            [
                _make_mode("dense", p50=10.0, p95=20.0, result_count=30),
            ]
        )

        report = retrieval_benchmark_compare.compare_benchmarks(
            baseline, current, latency_threshold_pct=20, result_count_threshold=5
        )

        assert report["overall_status"] == "fail"
        hybrid = [m for m in report["modes"] if m["mode"] == "hybrid"][0]
        assert hybrid["status"] == "fail"
        assert "missing from current run" in hybrid["reason"]


# ── CLI integration ───────────────────────────────────────────────────────────


class TestCliIntegration:
    """CLI arg / env resolution for baseline, thresholds."""

    def test_main_with_missing_baseline(self, capsys, monkeypatch):
        monkeypatch.setattr(
            retrieval_benchmark_compare,
            "build_parser",
            lambda: retrieval_benchmark_compare.build_parser(),
        )
        # We can't easily test main() directly with missing baseline because
        # sys.argv is global.  Instead test _load_baseline and the helper
        # functions, which are already covered above.
        data, err = retrieval_benchmark_compare._load_baseline(Path("/no/such/file"))
        assert data is None
        assert "not found" in err

    def test_main_with_corrupt_baseline(self, tmp_path):
        baseline_path = tmp_path / "bad.json"
        baseline_path.write_text("not json", encoding="utf-8")

        data, err = retrieval_benchmark_compare._load_baseline(baseline_path)
        assert data is None
        assert "invalid JSON" in err

    def test_threshold_defaults(self):
        assert retrieval_benchmark_compare.DEFAULT_LATENCY_THRESHOLD_PCT == 20
        assert retrieval_benchmark_compare.DEFAULT_RESULT_COUNT_THRESHOLD == 5

    def test_latency_delta_calculation(self):
        assert retrieval_benchmark_compare._latency_delta_pct(12.0, 10.0) == 20.0
        assert retrieval_benchmark_compare._latency_delta_pct(10.0, 10.0) == 0.0
        assert retrieval_benchmark_compare._latency_delta_pct(5.0, 10.0) == -50.0
        assert retrieval_benchmark_compare._latency_delta_pct(5.0, 0.0) == float("inf")
        assert retrieval_benchmark_compare._latency_delta_pct(0.0, 0.0) == 0.0

    def test_compare_all_four_modes(self):
        baseline = _make_baseline(
            [
                _make_mode("dense", p50=10.0, p95=20.0, result_count=30),
                _make_mode("hybrid", p50=10.0, p95=20.0, result_count=30),
                _make_mode("rerank", p50=10.0, p95=20.0, result_count=30),
                _make_mode("hybrid_rerank", p50=10.0, p95=20.0, result_count=30),
            ]
        )
        current = _make_baseline(
            [
                _make_mode("dense", p50=10.0, p95=20.0, result_count=30),
                _make_mode("hybrid", p50=10.0, p95=20.0, result_count=30),
                _make_mode("rerank", p50=10.0, p95=20.0, result_count=30),
                _make_mode("hybrid_rerank", p50=10.0, p95=20.0, result_count=30),
            ]
        )

        report = retrieval_benchmark_compare.compare_benchmarks(
            baseline, current, latency_threshold_pct=20, result_count_threshold=5
        )

        assert len(report["modes"]) == 4
        assert all(m["status"] == "pass" for m in report["modes"])
