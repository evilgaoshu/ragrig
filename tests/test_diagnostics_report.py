"""Tests for answer live smoke diagnostics artifact generation and console summary.

Covers:
- generate_diagnostics_artifact() output schema
- get_diagnostics_summary() for healthy/skip/degraded/error
- Missing, corrupt, stale artifact handling
- Secret-like leak interception
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ragrig.answer.diagnostics import (
    generate_diagnostics_artifact,
    get_diagnostics_summary,
    run_answer_diagnostics,
)

pytestmark = pytest.mark.unit


# ── Fixtures ─────────────────────────────────────────────────────────────


def _fake_deps_ok():
    return True, "openai available"


def _fake_deps_skip():
    return False, "Missing optional dependency: openai"


def _fake_ping_ok(base_url):
    return True, "mock reachable"


def _fake_ping_error(base_url):
    return False, "Connection refused"


def _fake_chat_with_citations(base_url, model):
    return 3, "Mock chat with [cit-1] [cit-2] [cit-3]"


def _fake_chat_no_citations(base_url, model):
    return 0, "Mock chat with no citations"


# ── generate_diagnostics_artifact ────────────────────────────────────────


class TestGenerateDiagnosticsArtifact:
    def test_artifact_healthy_contains_all_fields(self, tmp_path):
        """Artifact output includes all required fields."""
        out = tmp_path / "answer-live-smoke.json"
        artifact = generate_diagnostics_artifact(
            provider="ollama",
            model="llama3.2:1b",
            base_url="http://localhost:11434/v1",
            output_path=out,
            _deps_fn=_fake_deps_ok,
            _ping_fn=_fake_ping_ok,
            _chat_fn=_fake_chat_with_citations,
        )

        assert artifact["artifact"] == "answer-live-smoke"
        assert artifact["schema_version"] == "1.0"
        assert artifact["provider"] == "ollama"
        assert artifact["model"] == "llama3.2:1b"
        assert "localhost:11434" in artifact["base_url_redacted"]
        assert artifact["status"] == "healthy"
        assert artifact["citation_count"] == 3
        assert artifact["timing_ms"] >= 0
        assert artifact["generated_at"] is not None
        assert artifact["report_path"] is not None
        assert str(out) in artifact["report_path"]

        # File must exist on disk
        assert out.exists()
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["artifact"] == "answer-live-smoke"

    def test_artifact_skip_when_deps_missing(self, tmp_path):
        """Missing dependency produces skip status in artifact."""
        out = tmp_path / "skip.json"
        artifact = generate_diagnostics_artifact(
            provider="ollama",
            model="llama3.2:1b",
            base_url="http://localhost:11434/v1",
            output_path=out,
            _deps_fn=_fake_deps_skip,
        )

        assert artifact["status"] == "skip"
        assert "openai" in artifact["reason"]
        assert artifact["citation_count"] == 0

    def test_artifact_error_when_ping_fails(self, tmp_path):
        """Unreachable provider produces error status."""
        out = tmp_path / "error.json"
        artifact = generate_diagnostics_artifact(
            provider="ollama",
            model="llama3.2:1b",
            base_url="http://bad-host:99999/v1",
            output_path=out,
            _deps_fn=_fake_deps_ok,
            _ping_fn=_fake_ping_error,
        )

        assert artifact["status"] == "error"
        assert "refused" in artifact["reason"].lower()

    def test_artifact_degraded_when_no_citations(self, tmp_path):
        """Zero citations produces degraded status."""
        out = tmp_path / "degraded.json"
        artifact = generate_diagnostics_artifact(
            provider="mock",
            model="mock-model",
            base_url="http://mock:1234/v1",
            output_path=out,
            _deps_fn=_fake_deps_ok,
            _ping_fn=_fake_ping_ok,
            _chat_fn=_fake_chat_no_citations,
        )

        assert artifact["status"] == "degraded"
        assert "no citations" in artifact["reason"].lower()

    def test_artifact_secret_redaction(self, tmp_path):
        """Artifact must not contain raw API keys."""
        out = tmp_path / "redacted.json"
        artifact = generate_diagnostics_artifact(
            provider="ollama",
            model="llama3.2:1b",
            base_url="http://sk-abc123@localhost:11434/v1?api_key=sk-secret&token=my-token",
            output_path=out,
            _deps_fn=_fake_deps_ok,
            _ping_fn=_fake_ping_ok,
            _chat_fn=_fake_chat_with_citations,
        )

        redacted = artifact["base_url_redacted"]
        assert "sk-abc123" not in redacted
        assert "sk-secret" not in redacted
        assert "my-token" not in redacted
        assert "[REDACTED]" in redacted

    def test_artifact_default_output_path(self):
        """When no output_path given, uses default artifact path."""
        artifact = generate_diagnostics_artifact(
            provider="ollama",
            model="llama3.2:1b",
            base_url="http://localhost:11434/v1",
            _deps_fn=_fake_deps_ok,
            _ping_fn=_fake_ping_ok,
            _chat_fn=_fake_chat_with_citations,
        )

        assert artifact["report_path"] is not None
        assert "answer-live-smoke.json" in artifact["report_path"]


# ── get_diagnostics_summary ──────────────────────────────────────────────


class TestGetDiagnosticsSummary:
    def test_healthy_console_summary(self, tmp_path):
        """Healthy artifact produces available=True console summary."""
        out = tmp_path / "healthy.json"
        generate_diagnostics_artifact(
            provider="ollama",
            model="llama3.2:1b",
            base_url="http://localhost:11434/v1",
            output_path=out,
            _deps_fn=_fake_deps_ok,
            _ping_fn=_fake_ping_ok,
            _chat_fn=_fake_chat_with_citations,
        )

        summary = get_diagnostics_summary(artifact_path=out)
        assert summary["available"] is True
        assert summary["status"] == "healthy"
        assert summary["provider"] == "ollama"
        assert summary["model"] == "llama3.2:1b"
        assert summary["is_stale"] is False
        assert summary["citation_count"] == 3

    def test_skip_console_summary(self, tmp_path):
        """Skip status flows through to console summary."""
        out = tmp_path / "skip.json"
        generate_diagnostics_artifact(
            provider="ollama",
            model="llama3.2:1b",
            base_url="http://localhost:11434/v1",
            output_path=out,
            _deps_fn=_fake_deps_skip,
        )

        summary = get_diagnostics_summary(artifact_path=out)
        assert summary["available"] is True
        assert summary["status"] == "skip"

    def test_degraded_console_summary(self, tmp_path):
        """Degraded status flows through to console summary."""
        out = tmp_path / "degraded.json"
        generate_diagnostics_artifact(
            provider="mock",
            model="mock-model",
            base_url="http://mock:1234/v1",
            output_path=out,
            _deps_fn=_fake_deps_ok,
            _ping_fn=_fake_ping_ok,
            _chat_fn=_fake_chat_no_citations,
        )

        summary = get_diagnostics_summary(artifact_path=out)
        assert summary["available"] is True
        assert summary["status"] == "degraded"

    def test_error_console_summary(self, tmp_path):
        """Error status flows through to console summary."""
        out = tmp_path / "error.json"
        generate_diagnostics_artifact(
            provider="ollama",
            model="llama3.2:1b",
            base_url="http://bad-host:99999/v1",
            output_path=out,
            _deps_fn=_fake_deps_ok,
            _ping_fn=_fake_ping_error,
        )

        summary = get_diagnostics_summary(artifact_path=out)
        assert summary["available"] is True
        assert summary["status"] == "error"

    def test_missing_artifact_returns_failure(self):
        """Missing artifact returns available=False, status=failure."""
        missing = Path("/tmp/nonexistent-answer-smoke.json")
        summary = get_diagnostics_summary(artifact_path=missing)
        assert summary["available"] is False
        assert summary["status"] == "failure"
        assert "not found" in summary["reason"]

    def test_corrupt_artifact_returns_failure(self, tmp_path):
        """Corrupt JSON returns available=False, status=failure."""
        bad = tmp_path / "corrupt.json"
        bad.write_text("this is not json", encoding="utf-8")
        summary = get_diagnostics_summary(artifact_path=bad)
        assert summary["available"] is False
        assert summary["status"] == "failure"

    def test_wrong_artifact_type_returns_failure(self, tmp_path):
        """Wrong artifact type returns available=False."""
        wrong = tmp_path / "wrong.json"
        wrong.write_text(
            json.dumps({"artifact": "something-else", "status": "healthy"}),
            encoding="utf-8",
        )
        summary = get_diagnostics_summary(artifact_path=wrong)
        assert summary["available"] is False
        assert summary["status"] == "failure"

    def test_stale_artifact_downgraded_to_degraded(self, tmp_path):
        """Artifact older than 24h is flagged as stale and downgraded."""
        old = tmp_path / "stale.json"
        old_data = {
            "artifact": "answer-live-smoke",
            "schema_version": "1.0",
            "provider": "ollama",
            "model": "llama3.2:1b",
            "base_url_redacted": "http://localhost:11434/v1",
            "status": "healthy",
            "reason": "Was healthy",
            "citation_count": 3,
            "timing_ms": 100.0,
            "generated_at": (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat(),
            "report_path": str(old),
        }
        old.write_text(json.dumps(old_data), encoding="utf-8")

        summary = get_diagnostics_summary(artifact_path=old)
        assert summary["available"] is True
        assert summary["is_stale"] is True
        assert summary["status"] == "degraded"

    def test_console_summary_secret_safety(self, tmp_path):
        """Console summary must not leak raw secrets."""
        out = tmp_path / "secrets.json"
        generate_diagnostics_artifact(
            provider="ollama",
            model="llama3.2:1b",
            base_url="http://localhost:11434/v1",
            output_path=out,
            _deps_fn=_fake_deps_ok,
            _ping_fn=_fake_ping_ok,
            _chat_fn=_fake_chat_with_citations,
        )

        summary = get_diagnostics_summary(artifact_path=out)
        summary_str = json.dumps(summary)

        forbidden = ["sk-live-", "sk-proj-", "ghp_", "PRIVATE KEY-----"]
        for frag in forbidden:
            assert frag not in summary_str

    def test_console_summary_has_report_path(self, tmp_path):
        """Console summary includes report_path."""
        out = tmp_path / "report.json"
        generate_diagnostics_artifact(
            provider="ollama",
            model="llama3.2:1b",
            base_url="http://localhost:11434/v1",
            output_path=out,
            _deps_fn=_fake_deps_ok,
            _ping_fn=_fake_ping_ok,
            _chat_fn=_fake_chat_with_citations,
        )

        summary = get_diagnostics_summary(artifact_path=out)
        assert summary["report_path"] is not None
        assert "report.json" in summary["report_path"]


# ── Integration: script compatibility ────────────────────────────────────


class TestScriptCompatibility:
    def test_generate_artifact_matches_existing_report_shape(self, tmp_path):
        """Artifact output should contain all fields the existing report provides."""
        report = run_answer_diagnostics(
            provider="test-provider",
            model="test-model",
            base_url="http://test:1234/v1",
            _deps_fn=_fake_deps_ok,
            _ping_fn=_fake_ping_ok,
            _chat_fn=_fake_chat_with_citations,
        )

        out = tmp_path / "compat.json"
        artifact = generate_diagnostics_artifact(
            provider="test-provider",
            model="test-model",
            base_url="http://test:1234/v1",
            output_path=out,
            _deps_fn=_fake_deps_ok,
            _ping_fn=_fake_ping_ok,
            _chat_fn=_fake_chat_with_citations,
        )

        # Artifact extends report dict with generated_at, report_path, etc.
        assert artifact["provider"] == report.provider
        assert artifact["model"] == report.model
        assert artifact["base_url_redacted"] == report.base_url_redacted
        assert artifact["status"] == report.status
        assert artifact["citation_count"] == report.citation_count
        assert artifact["generated_at"] is not None
        assert artifact["report_path"] is not None
