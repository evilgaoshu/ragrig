"""Tests for retrieval benchmark baseline refresh and manifest compatibility."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import retrieval_benchmark_baseline_refresh
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
    p50: float = 10.0,
    p95: float = 20.0,
    result_count: int = 30,
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


def _make_manifest(**overrides) -> dict:
    manifest = {
        "schema_version": "1.0",
        "baseline_id": "test-baseline-id",
        "fixture_id": "test-fixture-id",
        "iteration_count": 2,
        "modes": ["dense", "hybrid", "rerank", "hybrid_rerank"],
        "metrics_hash": "abc123",
        "created_at": "2026-01-01T00:00:00Z",
        "generator_version": "0.1.0",
    }
    manifest.update(overrides)
    return manifest


# ── Manifest build tests ─────────────────────────────────────────────────────


class TestBuildManifest:
    """Manifest construction from benchmark data."""

    def test_manifest_has_required_fields(self):
        data = _make_baseline(
            [
                _make_mode("dense"),
                _make_mode("hybrid"),
            ]
        )
        manifest = retrieval_benchmark_baseline_refresh.build_manifest(
            data, fixture_root=Path("tests/fixtures/local_ingestion")
        )

        assert manifest["schema_version"] == "1.0"
        assert "baseline_id" in manifest
        assert "fixture_id" in manifest
        assert manifest["iteration_count"] == 2
        assert manifest["modes"] == ["dense", "hybrid"]
        assert "metrics_hash" in manifest
        assert "created_at" in manifest
        assert "generator_version" in manifest

    def test_fixture_id_is_stable(self):
        data = _make_baseline([_make_mode("dense")])
        m1 = retrieval_benchmark_baseline_refresh.build_manifest(
            data, fixture_root=Path("tests/fixtures/local_ingestion")
        )
        m2 = retrieval_benchmark_baseline_refresh.build_manifest(
            data, fixture_root=Path("tests/fixtures/local_ingestion")
        )
        assert m1["fixture_id"] == m2["fixture_id"]

    def test_fixture_id_matches_across_different_workspace_roots(self, tmp_path):
        root_a = tmp_path / "workspace-a" / "fixtures"
        root_b = tmp_path / "workspace-b" / "fixtures"
        for root in (root_a, root_b):
            docs = root / "nested"
            docs.mkdir(parents=True)
            (root / "alpha.txt").write_text("same corpus", encoding="utf-8")
            (docs / "beta.txt").write_text("same nested corpus", encoding="utf-8")

        fixture_id_a = retrieval_benchmark_baseline_refresh._compute_fixture_id(root_a)
        fixture_id_b = retrieval_benchmark_baseline_refresh._compute_fixture_id(root_b)

        assert fixture_id_a == fixture_id_b

    def test_fixture_id_changes_when_file_content_changes_without_size_change(self, tmp_path):
        fixture_root = tmp_path / "fixtures"
        fixture_root.mkdir()
        file_path = fixture_root / "alpha.txt"
        file_path.write_text("abc", encoding="utf-8")

        original_fixture_id = retrieval_benchmark_baseline_refresh._compute_fixture_id(fixture_root)

        file_path.write_text("xyz", encoding="utf-8")
        updated_fixture_id = retrieval_benchmark_baseline_refresh._compute_fixture_id(fixture_root)

        assert updated_fixture_id != original_fixture_id

    def test_metrics_hash_changes_with_structure(self):
        data1 = _make_baseline([_make_mode("dense", result_count=10)])
        data2 = _make_baseline([_make_mode("dense", result_count=20)])

        h1 = retrieval_benchmark_baseline_refresh._compute_metrics_hash(data1)
        h2 = retrieval_benchmark_baseline_refresh._compute_metrics_hash(data2)

        assert h1 != h2

    def test_metrics_hash_ignores_latency_values(self):
        data1 = _make_baseline([_make_mode("dense", p50=5.0, p95=10.0)])
        data2 = _make_baseline([_make_mode("dense", p50=50.0, p95=100.0)])

        h1 = retrieval_benchmark_baseline_refresh._compute_metrics_hash(data1)
        h2 = retrieval_benchmark_baseline_refresh._compute_metrics_hash(data2)

        assert h1 == h2


# ── Refresh pass ─────────────────────────────────────────────────────────────


class TestRefreshPass:
    """Baseline refresh produces valid output."""

    def test_refresh_baseline_embeds_manifest(self, tmp_path):
        baseline = retrieval_benchmark_baseline_refresh.refresh_baseline(
            iterations=1,
            top_k=3,
            candidate_k=5,
            fixture_root=tmp_path,
        )

        assert "_manifest" in baseline
        manifest = baseline["_manifest"]
        assert manifest["schema_version"] == "1.0"
        assert manifest["iteration_count"] == 1
        assert set(manifest["modes"]) == {"dense", "hybrid", "rerank", "hybrid_rerank"}

    def test_refresh_output_is_json_serializable(self, tmp_path):
        baseline = retrieval_benchmark_baseline_refresh.refresh_baseline(
            iterations=1,
            top_k=3,
            candidate_k=5,
            fixture_root=tmp_path,
        )
        baseline = _sanitize_summary(baseline)

        json_output = json.dumps(baseline, sort_keys=True)
        parsed = json.loads(json_output)
        assert parsed["knowledge_base"] == "fixture-local"
        assert "_manifest" in parsed

    def test_refresh_with_missing_fixture_raises(self):
        with pytest.raises(FileNotFoundError):
            retrieval_benchmark_baseline_refresh.refresh_baseline(
                iterations=1,
                top_k=3,
                candidate_k=5,
                fixture_root=Path("/nonexistent/fixture"),
            )


# ── Manifest compatibility checks ────────────────────────────────────────────


class TestManifestCompatibility:
    """_check_manifest_compatibility returns correct status."""

    def test_pass_when_fresh_baseline(self, tmp_path):
        baseline = retrieval_benchmark_baseline_refresh.refresh_baseline(
            iterations=1,
            top_k=3,
            candidate_k=5,
            fixture_root=tmp_path,
        )
        current = retrieval_benchmark_baseline_refresh.refresh_baseline(
            iterations=1,
            top_k=3,
            candidate_k=5,
            fixture_root=tmp_path,
        )

        from scripts.retrieval_benchmark_compare import _check_manifest_compatibility

        ok, reason = _check_manifest_compatibility(baseline, current)
        assert ok is True
        assert reason == ""

    def test_fail_when_missing_manifest(self):
        baseline = _make_baseline([_make_mode("dense")])
        current = _make_baseline([_make_mode("dense")])

        from scripts.retrieval_benchmark_compare import _check_manifest_compatibility

        ok, reason = _check_manifest_compatibility(baseline, current)
        assert ok is False
        assert "missing _manifest" in reason

    def test_fail_when_schema_mismatch(self):
        baseline = _make_baseline([_make_mode("dense")])
        baseline["_manifest"] = _make_manifest(schema_version="0.9")
        current = _make_baseline([_make_mode("dense")])
        current["_manifest"] = _make_manifest(schema_version="1.0")

        from scripts.retrieval_benchmark_compare import _check_manifest_compatibility

        ok, reason = _check_manifest_compatibility(baseline, current)
        assert ok is False
        assert "schema_version mismatch" in reason

    def test_fail_when_fixture_id_mismatch(self, tmp_path):
        baseline_root = tmp_path / "baseline-fixture"
        current_root = tmp_path / "current-fixture"
        baseline_root.mkdir()
        current_root.mkdir()
        (baseline_root / "alpha.txt").write_text("same", encoding="utf-8")
        (current_root / "alpha.txt").write_text("changed", encoding="utf-8")

        baseline = retrieval_benchmark_baseline_refresh.refresh_baseline(
            iterations=1,
            top_k=3,
            candidate_k=5,
            fixture_root=baseline_root,
        )
        current = retrieval_benchmark_baseline_refresh.refresh_baseline(
            iterations=1,
            top_k=3,
            candidate_k=5,
            fixture_root=current_root,
        )

        from scripts.retrieval_benchmark_compare import _check_manifest_compatibility

        ok, reason = _check_manifest_compatibility(baseline, current)
        assert ok is False
        assert "fixture_id mismatch" in reason

    def test_fail_when_iteration_count_mismatch(self, tmp_path):
        baseline = retrieval_benchmark_baseline_refresh.refresh_baseline(
            iterations=2,
            top_k=3,
            candidate_k=5,
            fixture_root=tmp_path,
        )
        current = retrieval_benchmark_baseline_refresh.refresh_baseline(
            iterations=1,
            top_k=3,
            candidate_k=5,
            fixture_root=tmp_path,
        )

        from scripts.retrieval_benchmark_compare import _check_manifest_compatibility

        ok, reason = _check_manifest_compatibility(baseline, current)
        assert ok is False
        assert "iteration_count mismatch" in reason

    def test_fail_when_metrics_hash_mismatch(self, tmp_path):
        baseline = retrieval_benchmark_baseline_refresh.refresh_baseline(
            iterations=1,
            top_k=3,
            candidate_k=5,
            fixture_root=tmp_path,
        )
        current = retrieval_benchmark_baseline_refresh.refresh_baseline(
            iterations=1,
            top_k=3,
            candidate_k=5,
            fixture_root=tmp_path,
        )
        # Mutate current metrics structure to change hash and remove the
        # cached metrics_hash so the check recomputes it from the data.
        current["modes"] = current["modes"][:2]
        current["_manifest"].pop("metrics_hash", None)

        from scripts.retrieval_benchmark_compare import _check_manifest_compatibility

        ok, reason = _check_manifest_compatibility(baseline, current)
        assert ok is False
        assert "metrics_hash mismatch" in reason


# ── Secret-like config sanitization ────────────────────────────────────────────


class TestSanitization:
    """Secret-like values are redacted from refresh output."""

    def test_secret_keys_redacted_in_refresh_output(self, tmp_path):
        baseline = retrieval_benchmark_baseline_refresh.refresh_baseline(
            iterations=1,
            top_k=3,
            candidate_k=5,
            fixture_root=tmp_path,
        )
        baseline["api_key"] = "sk-refresh-secret"
        baseline["secret_config"] = {"password": "refresh-pass"}

        sanitized = _sanitize_summary(baseline)
        assert sanitized["api_key"] == "[redacted]"
        # The key "secret_config" itself contains "secret", so the whole value
        # is redacted — not just nested keys inside it.
        assert sanitized["secret_config"] == "[redacted]"

    def test_manifest_not_mutated_by_sanitization(self, tmp_path):
        baseline = retrieval_benchmark_baseline_refresh.refresh_baseline(
            iterations=1,
            top_k=3,
            candidate_k=5,
            fixture_root=tmp_path,
        )
        baseline["_manifest"]["test_api_key"] = "should-be-redacted"

        sanitized = _sanitize_summary(baseline)
        assert sanitized["_manifest"]["test_api_key"] == "[redacted]"


# ── CLI integration ────────────────────────────────────────────────────────────


class TestCliIntegration:
    """CLI arg / env resolution for baseline refresh."""

    def test_parser_defaults(self):
        parser = retrieval_benchmark_baseline_refresh.build_parser()
        args = parser.parse_args([])

        assert args.iterations == 5
        assert args.top_k == 5
        assert args.candidate_k == 20
        assert args.output is None
        assert args.manifest_output is None
        assert args.pretty is False

    def test_parser_overrides(self):
        parser = retrieval_benchmark_baseline_refresh.build_parser()
        args = parser.parse_args(
            ["--iterations", "10", "--top-k", "3", "--candidate-k", "10", "--pretty"]
        )

        assert args.iterations == 10
        assert args.top_k == 3
        assert args.candidate_k == 10
        assert args.pretty is True
