"""Tests for retrieval benchmark and BGE smoke scripts."""

from __future__ import annotations

import json

import pytest

from scripts import bge_rerank_smoke, retrieval_benchmark

pytestmark = [pytest.mark.unit]


# ── Schema validation tests ──────────────────────────────────────────────────


class TestBenchmarkOutputSchema:
    """Verify the benchmark JSON output conforms to the expected schema."""

    def test_output_has_required_top_level_keys(self):
        """Top-level keys must include knowledge_base, queries, iterations, database, modes."""
        result = retrieval_benchmark.run_benchmarks(iterations=1, top_k=3, candidate_k=5)

        assert "knowledge_base" in result
        assert "queries" in result
        assert "iterations_per_query" in result
        assert "database" in result
        assert "modes" in result
        assert result["knowledge_base"] == "fixture-local"

    def test_all_four_modes_present(self):
        """Benchmark must cover dense, hybrid, rerank, hybrid_rerank."""
        result = retrieval_benchmark.run_benchmarks(iterations=1, top_k=3, candidate_k=5)

        mode_names = {m["mode"] for m in result["modes"]}
        assert mode_names == {"dense", "hybrid", "rerank", "hybrid_rerank"}

    def test_each_mode_has_required_fields(self):
        """Each mode entry must include mode, latency fields, result_count, degraded."""
        result = retrieval_benchmark.run_benchmarks(iterations=1, top_k=3, candidate_k=5)

        required_fields = {
            "mode",
            "top_k",
            "candidate_k",
            "iterations",
            "p50_latency_ms",
            "p95_latency_ms",
            "min_latency_ms",
            "max_latency_ms",
            "mean_latency_ms",
            "result_count",
            "degraded",
            "degraded_reason",
        }

        for mode_result in result["modes"]:
            for field in required_fields:
                assert field in mode_result, (
                    f"Mode {mode_result.get('mode', '?')} missing field '{field}'"
                )

    def test_latency_values_are_non_negative(self):
        """All latency values must be >= 0."""
        result = retrieval_benchmark.run_benchmarks(iterations=1, top_k=3, candidate_k=5)

        latency_fields = [
            "p50_latency_ms",
            "p95_latency_ms",
            "min_latency_ms",
            "max_latency_ms",
            "mean_latency_ms",
        ]
        for mode_result in result["modes"]:
            for field in latency_fields:
                assert mode_result[field] >= 0, (
                    f"Mode {mode_result['mode']} field '{field}' is negative: {mode_result[field]}"
                )

    def test_degraded_is_boolean(self):
        """The degraded field must be a boolean."""
        result = retrieval_benchmark.run_benchmarks(iterations=1, top_k=3, candidate_k=5)

        for mode_result in result["modes"]:
            assert isinstance(mode_result["degraded"], bool), (
                f"Mode {mode_result['mode']} degraded is not bool: {type(mode_result['degraded'])}"
            )

    def test_degraded_reason_is_string(self):
        """The degraded_reason field must be a string."""
        result = retrieval_benchmark.run_benchmarks(iterations=1, top_k=3, candidate_k=5)

        for mode_result in result["modes"]:
            assert isinstance(mode_result["degraded_reason"], str), (
                f"Mode {mode_result['mode']} degraded_reason is not str"
            )

    def test_iterations_count_is_correct(self):
        """Number of iterations per mode = queries × iterations_per_query."""
        n_iter = 2
        n_queries = len(retrieval_benchmark.BENCHMARK_QUERIES)
        expected_iter = n_queries * n_iter

        result = retrieval_benchmark.run_benchmarks(iterations=n_iter, top_k=3, candidate_k=5)

        for mode_result in result["modes"]:
            assert mode_result["iterations"] == expected_iter, (
                f"Mode {mode_result['mode']} iterations mismatch"
            )

    def test_output_is_json_serializable(self):
        """The output dict must be JSON-serializable."""
        result = retrieval_benchmark.run_benchmarks(iterations=1, top_k=3, candidate_k=5)
        output = retrieval_benchmark._sanitize_summary(result)

        # Should not raise
        json_output = json.dumps(output, sort_keys=True)
        assert isinstance(json_output, str)
        # Should be valid JSON when parsed
        parsed = json.loads(json_output)
        assert parsed["knowledge_base"] == "fixture-local"


# ── Sanitization tests ───────────────────────────────────────────────────────


class TestSanitizeSummary:
    """Verify secret-like config values are redacted from output."""

    def test_secret_keys_are_redacted(self):
        """Keys containing api_key, password, token, etc. should be redacted."""
        input_data = {
            "modes": [
                {
                    "mode": "dense",
                    "api_key": "sk-1234567890abcdef",
                    "config": {
                        "access_key": "AKIAIOSFODNN7EXAMPLE",
                        "secret_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                        "password": "super-secret-password",
                        "token": "ghp_1234567890abcdef",
                        "credential": "my-credential-string",
                        "private_key": "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END-----",
                        "dsn": "postgresql://user:pass@host/db",
                        "session_token": "FQoGZXIvYXdzE...",
                        "service_account": '{"type": "service_account"}',
                    },
                    "normal_key": "this-should-remain-visible",
                }
            ],
            "provider": "deterministic-local",
        }

        sanitized = retrieval_benchmark._sanitize_summary(input_data)

        mode = sanitized["modes"][0]
        assert mode["api_key"] == "[redacted]"
        config = mode["config"]
        assert config["access_key"] == "[redacted]"
        assert config["secret_key"] == "[redacted]"
        assert config["password"] == "[redacted]"
        assert config["token"] == "[redacted]"
        assert config["credential"] == "[redacted]"
        assert config["private_key"] == "[redacted]"
        assert config["dsn"] == "[redacted]"
        assert config["session_token"] == "[redacted]"
        assert config["service_account"] == "[redacted]"
        assert mode["normal_key"] == "this-should-remain-visible"

    def test_non_secret_keys_are_not_redacted(self):
        """Keys without secret-like patterns should NOT be redacted."""
        input_data = {
            "modes": [
                {
                    "mode": "dense",
                    "query": "retrieval configuration guide",
                    "model": "hash-8d",
                    "provider": "deterministic-local",
                    "dimensions": 8,
                    "backend": "pgvector",
                    "first_name": "Alice",
                    "last_name": "Smith",
                    "email": "alice@example.com",
                    "url": "https://example.com",
                }
            ]
        }

        sanitized = retrieval_benchmark._sanitize_summary(input_data)

        mode = sanitized["modes"][0]
        assert mode["query"] == "retrieval configuration guide"
        assert mode["model"] == "hash-8d"
        assert mode["provider"] == "deterministic-local"
        assert mode["dimensions"] == 8
        assert mode["backend"] == "pgvector"
        assert mode["first_name"] == "Alice"
        assert mode["last_name"] == "Smith"
        assert mode["email"] == "alice@example.com"
        assert mode["url"] == "https://example.com"

    def test_nested_lists_are_sanitized(self):
        """Secret-like values in nested lists should also be redacted."""
        input_data = {
            "providers": [
                {"name": "openai", "api_key": "sk-deeply-nested-key"},
                {"name": "bedrock", "access_key": "nested-access-key"},
            ]
        }

        sanitized = retrieval_benchmark._sanitize_summary(input_data)

        assert sanitized["providers"][0]["api_key"] == "[redacted]"
        assert sanitized["providers"][1]["access_key"] == "[redacted]"
        assert sanitized["providers"][0]["name"] == "openai"

    def test_edges_cases_empty_and_non_dict(self):
        """Edge cases: empty dict, non-dict values should not crash."""
        assert retrieval_benchmark._sanitize_summary({}) == {}
        assert retrieval_benchmark._sanitize_summary({"key": 42}) == {"key": 42}
        assert retrieval_benchmark._sanitize_summary({"key": None}) == {"key": None}
        assert retrieval_benchmark._sanitize_summary({"key": True}) == {"key": True}

    def test_case_insensitive_redaction(self):
        """Redaction should be case-insensitive for keys."""
        input_data = {
            "API_KEY": "upper-case-secret",
            "Api_Key": "mixed-case-secret",
            "SECRET_TOKEN": "shouty-secret",
        }

        sanitized = retrieval_benchmark._sanitize_summary(input_data)

        assert sanitized["API_KEY"] == "[redacted]"
        assert sanitized["Api_Key"] == "[redacted]"
        assert sanitized["SECRET_TOKEN"] == "[redacted]"


# ── BGE smoke test dependency check ─────────────────────────────────────────


class TestBgeDependencyCheck:
    """Verify BGE dependency check returns correct status."""

    def test_returns_not_available_when_deps_missing(self, monkeypatch):
        """When deps are missing, return available=False with reason and missing list."""
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "FlagEmbedding":
                raise ImportError("No module named 'FlagEmbedding'")
            if name == "sentence_transformers":
                raise ImportError("No module named 'sentence_transformers'")
            if name == "torch":
                raise ImportError("No module named 'torch'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        result = bge_rerank_smoke._check_bge_dependencies()

        assert result["available"] is False
        assert "FlagEmbedding" in result["missing"]
        assert "sentence-transformers" in result["missing"]
        assert "torch" in result["missing"]
        assert "uv sync --extra local-ml" in result["reason"]

    def test_run_bge_smoke_skips_when_deps_missing(self, monkeypatch):
        """The full smoke test should return skipped status when deps missing."""
        monkeypatch.setattr(
            bge_rerank_smoke,
            "_check_bge_dependencies",
            lambda: {
                "available": False,
                "reason": "Missing dependencies: torch. Install with: uv sync --extra local-ml",
                "missing": ["torch"],
            },
        )

        result = bge_rerank_smoke.run_bge_smoke()

        assert result["status"] == "skipped"
        assert "Missing dependencies" in result["reason"]

    def test_smoke_result_is_json_serializable(self):
        """The BGE smoke result must be JSON-serializable."""
        result = bge_rerank_smoke.run_bge_smoke()
        sanitized = bge_rerank_smoke._sanitize_result(result)

        json_output = json.dumps(sanitized, sort_keys=True)
        parsed = json.loads(json_output)
        assert parsed["test"] == "bge_rerank_smoke"
        assert parsed["status"] in ("success", "skipped")

    def test_sanitize_result_redacts_secrets(self):
        """BGE smoke result sanitization should redact secret-like keys."""
        input_data = {
            "test": "bge_rerank_smoke",
            "status": "skipped",
            "bge_dependencies": {"available": False, "api_key": "should-be-redacted"},
            "details": {"secret": "also-redacted"},
        }

        sanitized = bge_rerank_smoke._sanitize_result(input_data)

        assert sanitized["bge_dependencies"]["api_key"] == "[redacted]"
        assert sanitized["details"]["secret"] == "[redacted]"


# ── Benchmark degraded behavior ──────────────────────────────────────────────


class TestBenchmarkDegradedBehavior:
    """Verify benchmark handles degraded states correctly."""

    def test_dense_mode_not_degraded_by_default(self):
        """Dense mode without reranker should not be degraded."""
        result = retrieval_benchmark.run_benchmarks(iterations=1, top_k=3, candidate_k=5)

        dense_result = [m for m in result["modes"] if m["mode"] == "dense"][0]
        assert dense_result["degraded"] is False
        assert dense_result["degraded_reason"] == ""

    def test_rerank_mode_uses_fake_reranker_by_default(self):
        """Rerank mode with no explicit provider uses fake reranker — not degraded."""
        result = retrieval_benchmark.run_benchmarks(iterations=1, top_k=3, candidate_k=5)

        rerank_result = [m for m in result["modes"] if m["mode"] == "rerank"][0]
        # fake reranker should not be degraded
        assert rerank_result["degraded"] is False

    def test_single_query_benchmark(self):
        """Benchmark with a single query works correctly."""
        result = retrieval_benchmark.run_benchmarks(
            iterations=2, top_k=2, candidate_k=3, queries=["retrieval configuration guide"]
        )

        for mode_result in result["modes"]:
            assert mode_result["iterations"] == 2  # 1 query × 2 iterations


# ── Benchmark with explicit database URL ─────────────────────────────────────


class TestBenchmarkWithDatabaseUrl:
    """Verify benchmark works with an explicit database URL."""

    def test_benchmark_with_sqlite_file(self, tmp_path):
        """Benchmark should work with an explicit file-based sqlite URL."""
        db_path = tmp_path / "benchmark-test.db"
        db_url = f"sqlite+pysqlite:///{db_path}"

        result = retrieval_benchmark.run_benchmarks(
            iterations=1, top_k=3, candidate_k=5, database_url=db_url
        )

        assert "knowledge_base" in result
        assert len(result["modes"]) == 4

        # Running again should work (re-seeding)
        result2 = retrieval_benchmark.run_benchmarks(
            iterations=1, top_k=3, candidate_k=5, database_url=db_url
        )
        assert len(result2["modes"]) == 4
