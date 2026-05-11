"""Tests for evaluation baseline management and run retention.

Covers:
- Baseline create / select / missing / corrupt
- Delta computation with strict baseline loader
- Retention protecting baseline-linked runs
- Secret-like config not entering baseline reports
"""

from __future__ import annotations

import json

import pytest

from ragrig.evaluation.baseline import (
    BASELINE_REGISTRY_NAME,
    BaselineCorruptError,
    BaselineNotFoundError,
    get_current_baseline_id,
    list_baselines,
    load_baseline_metrics_strict,
    promote_run_to_baseline,
    resolve_baseline_path,
)
from ragrig.evaluation.retention import cleanup_evaluation_runs
from ragrig.evaluation.engine import _persist_run
from ragrig.evaluation.models import EvaluationMetrics, EvaluationRun, now_iso


def _make_run(run_id: str, **overrides) -> EvaluationRun:
    defaults = {
        "created_at": now_iso(),
        "golden_set_name": "test",
        "knowledge_base": "kb",
        "provider": "p",
        "model": "m",
        "dimensions": 8,
        "top_k": 5,
        "backend": "pgvector",
        "distance_metric": "cosine",
        "total_questions": 1,
        "items": [],
        "metrics": EvaluationMetrics(total_questions=1),
    }
    defaults.update(overrides)
    return EvaluationRun(id=run_id, **defaults)


# ── Baseline Create Tests ────────────────────────────────────────────────────


def test_promote_run_to_baseline_creates_file_and_registry(tmp_path) -> None:
    """Promoting a run creates baseline file and registry entry."""
    store_dir = tmp_path / "runs"
    baseline_dir = tmp_path / "baselines"
    run = _make_run("run-1")
    _persist_run(run, store_dir)

    metadata = promote_run_to_baseline(
        "run-1", store_dir=store_dir, baseline_dir=baseline_dir, baseline_id="bl-1"
    )

    assert metadata["id"] == "bl-1"
    assert metadata["source_run_id"] == "run-1"
    assert (baseline_dir / "bl-1.json").exists()
    assert (baseline_dir / BASELINE_REGISTRY_NAME).exists()


def test_promote_run_to_baseline_generates_id(tmp_path) -> None:
    """Promoting without explicit baseline_id generates one."""
    store_dir = tmp_path / "runs"
    baseline_dir = tmp_path / "baselines"
    run = _make_run("run-2")
    _persist_run(run, store_dir)

    metadata = promote_run_to_baseline("run-2", store_dir=store_dir, baseline_dir=baseline_dir)
    assert metadata["id"].startswith("baseline-")


def test_promote_run_to_baseline_updates_current(tmp_path) -> None:
    """Promoting sets current_baseline_id to the new baseline."""
    store_dir = tmp_path / "runs"
    baseline_dir = tmp_path / "baselines"
    run = _make_run("run-3")
    _persist_run(run, store_dir)

    promote_run_to_baseline(
        "run-3", store_dir=store_dir, baseline_dir=baseline_dir, baseline_id="bl-a"
    )
    assert get_current_baseline_id(baseline_dir) == "bl-a"

    run2 = _make_run("run-4")
    _persist_run(run2, store_dir)
    promote_run_to_baseline(
        "run-4", store_dir=store_dir, baseline_dir=baseline_dir, baseline_id="bl-b"
    )
    assert get_current_baseline_id(baseline_dir) == "bl-b"


def test_promote_run_missing_raises(tmp_path) -> None:
    """Promoting a nonexistent run raises BaselineNotFoundError."""
    with pytest.raises(BaselineNotFoundError, match="Run not found"):
        promote_run_to_baseline(
            "missing", store_dir=tmp_path / "runs", baseline_dir=tmp_path / "baselines"
        )


# ── Baseline Select / Resolve Tests ──────────────────────────────────────────


def test_resolve_baseline_path_by_direct_file(tmp_path) -> None:
    """Resolving an existing file path returns it directly."""
    path = tmp_path / "my_baseline.json"
    path.write_text("{}")
    resolved = resolve_baseline_path(str(path), baseline_dir=tmp_path / "baselines")
    assert resolved == path.resolve()


def test_resolve_baseline_path_by_registry_id(tmp_path) -> None:
    """Resolving by baseline ID uses the registry."""
    store_dir = tmp_path / "runs"
    baseline_dir = tmp_path / "baselines"
    run = _make_run("run-5")
    _persist_run(run, store_dir)

    promote_run_to_baseline(
        "run-5", store_dir=store_dir, baseline_dir=baseline_dir, baseline_id="bl-5"
    )
    resolved = resolve_baseline_path("bl-5", baseline_dir=baseline_dir)
    assert resolved.name == "bl-5.json"


def test_resolve_baseline_path_fallback_in_dir(tmp_path) -> None:
    """Resolving falls back to baseline_dir/<id>.json if not in registry."""
    baseline_dir = tmp_path / "baselines"
    baseline_dir.mkdir()
    (baseline_dir / "orphan.json").write_text("{}")
    resolved = resolve_baseline_path("orphan", baseline_dir=baseline_dir)
    assert resolved.name == "orphan.json"


def test_resolve_baseline_path_missing_raises(tmp_path) -> None:
    """Resolving a missing baseline raises BaselineNotFoundError."""
    with pytest.raises(BaselineNotFoundError, match="Baseline not found"):
        resolve_baseline_path("no-such-baseline", baseline_dir=tmp_path / "baselines")


def test_resolve_baseline_path_file_missing_but_in_registry(tmp_path) -> None:
    """If registry references a moved baseline, raises BaselineNotFoundError."""
    store_dir = tmp_path / "runs"
    baseline_dir = tmp_path / "baselines"
    run = _make_run("run-6")
    _persist_run(run, store_dir)

    promote_run_to_baseline(
        "run-6", store_dir=store_dir, baseline_dir=baseline_dir, baseline_id="bl-6"
    )
    # Delete the file but keep registry
    (baseline_dir / "bl-6.json").unlink()
    with pytest.raises(BaselineNotFoundError, match="recorded but file missing"):
        resolve_baseline_path("bl-6", baseline_dir=baseline_dir)


# ── Baseline Corrupt Tests ───────────────────────────────────────────────────


def test_load_baseline_metrics_strict_missing_file(tmp_path) -> None:
    """Strict loader raises BaselineNotFoundError for missing file."""
    with pytest.raises(BaselineNotFoundError, match="not found"):
        load_baseline_metrics_strict(tmp_path / "missing.json")


def test_load_baseline_metrics_strict_invalid_json(tmp_path) -> None:
    """Strict loader raises BaselineCorruptError for invalid JSON."""
    path = tmp_path / "bad.json"
    path.write_text("not json")
    with pytest.raises(BaselineCorruptError, match="corrupt"):
        load_baseline_metrics_strict(path)


def test_load_baseline_metrics_strict_missing_metrics_key(tmp_path) -> None:
    """Strict loader raises BaselineCorruptError when metrics key missing."""
    path = tmp_path / "no_metrics.json"
    path.write_text('{"id": "x"}')
    with pytest.raises(BaselineCorruptError, match="missing 'metrics'"):
        load_baseline_metrics_strict(path)


def test_load_baseline_metrics_strict_invalid_metrics_schema(tmp_path) -> None:
    """Strict loader raises BaselineCorruptError for invalid metrics schema."""
    path = tmp_path / "bad_metrics.json"
    path.write_text('{"metrics": "not_a_dict"}')
    with pytest.raises(BaselineCorruptError, match="missing 'metrics'"):
        load_baseline_metrics_strict(path)


def test_load_baseline_metrics_strict_success(tmp_path) -> None:
    """Strict loader successfully validates valid baseline."""
    path = tmp_path / "good.json"
    run = _make_run("run-7", metrics=EvaluationMetrics(total_questions=2, hit_at_1=0.5))
    path.write_text(run.model_dump_json(), encoding="utf-8")
    metrics = load_baseline_metrics_strict(path)
    assert metrics.hit_at_1 == 0.5


# ── List Baselines Tests ─────────────────────────────────────────────────────


def test_list_baselines_empty(tmp_path) -> None:
    """Listing baselines with no registry returns empty structure."""
    result = list_baselines(baseline_dir=tmp_path / "baselines")
    assert result["current_baseline_id"] is None
    assert result["baselines"] == []


def test_list_baselines_with_entries(tmp_path) -> None:
    """Listing baselines returns registry entries."""
    store_dir = tmp_path / "runs"
    baseline_dir = tmp_path / "baselines"
    run = _make_run("run-8")
    _persist_run(run, store_dir)

    promote_run_to_baseline(
        "run-8", store_dir=store_dir, baseline_dir=baseline_dir, baseline_id="bl-8"
    )
    result = list_baselines(baseline_dir=baseline_dir)
    assert len(result["baselines"]) == 1
    assert result["baselines"][0]["id"] == "bl-8"


# ── Retention Tests ──────────────────────────────────────────────────────────


def test_cleanup_deletes_old_runs(tmp_path) -> None:
    """Cleanup removes runs beyond keep_count."""
    store_dir = tmp_path / "runs"
    baseline_dir = tmp_path / "baselines"
    store_dir.mkdir()

    for i in range(5):
        run = _make_run(f"run-{i}")
        _persist_run(run, store_dir)

    result = cleanup_evaluation_runs(
        store_dir=store_dir, baseline_dir=baseline_dir, keep_count=2, dry_run=False
    )
    assert len(result["deleted"]) == 3
    assert len(result["protected"]) == 2


def test_cleanup_protects_baseline_runs(tmp_path) -> None:
    """Cleanup never deletes runs referenced by baselines."""
    store_dir = tmp_path / "runs"
    baseline_dir = tmp_path / "baselines"

    run = _make_run("protected-run")
    _persist_run(run, store_dir)
    promote_run_to_baseline(
        "protected-run", store_dir=store_dir, baseline_dir=baseline_dir, baseline_id="bl-prot"
    )

    result = cleanup_evaluation_runs(
        store_dir=store_dir, baseline_dir=baseline_dir, keep_count=0, dry_run=False
    )
    assert "protected-run.json" in result["protected"]
    assert "protected-run.json" not in result["deleted"]


def test_cleanup_protects_current_baseline(tmp_path) -> None:
    """Cleanup protects the current baseline id even if not linked to a run."""
    store_dir = tmp_path / "runs"
    baseline_dir = tmp_path / "baselines"

    run = _make_run("run-curr")
    _persist_run(run, store_dir)
    promote_run_to_baseline(
        "run-curr", store_dir=store_dir, baseline_dir=baseline_dir, baseline_id="curr-bl"
    )

    # Also create an unrelated run
    run2 = _make_run("run-other")
    _persist_run(run2, store_dir)

    result = cleanup_evaluation_runs(
        store_dir=store_dir, baseline_dir=baseline_dir, keep_count=0, dry_run=False
    )
    assert "run-curr.json" in result["protected"]
    assert "run-other.json" in result["deleted"]


def test_cleanup_dry_run_does_not_delete(tmp_path) -> None:
    """Dry run reports but does not delete."""
    store_dir = tmp_path / "runs"
    baseline_dir = tmp_path / "baselines"

    run = _make_run("dry-run")
    _persist_run(run, store_dir)

    result = cleanup_evaluation_runs(
        store_dir=store_dir, baseline_dir=baseline_dir, keep_count=0, dry_run=True
    )
    assert "dry-run.json" in result["deleted"]
    assert (store_dir / "dry-run.json").exists()


def test_cleanup_keep_days_protects_new(tmp_path) -> None:
    """Cleanup with keep_days protects recent runs."""
    store_dir = tmp_path / "runs"
    baseline_dir = tmp_path / "baselines"
    store_dir.mkdir()

    import os
    import time

    # Create an old run by backdating mtime
    run_old = _make_run("old-run")
    _persist_run(run_old, store_dir)
    old_time = time.time() - (40 * 24 * 3600)
    os.utime(store_dir / "old-run.json", (old_time, old_time))

    # Create a new run
    run_new = _make_run("new-run")
    _persist_run(run_new, store_dir)

    result = cleanup_evaluation_runs(
        store_dir=store_dir, baseline_dir=baseline_dir, keep_days=30, dry_run=False
    )
    assert "old-run.json" in result["deleted"]
    assert "new-run.json" in result["protected"]


def test_cleanup_empty_store(tmp_path) -> None:
    """Cleanup on nonexistent store returns empty lists."""
    result = cleanup_evaluation_runs(
        store_dir=tmp_path / "empty", baseline_dir=tmp_path / "baselines"
    )
    assert result == {"deleted": [], "protected": []}


# ── Secret Sanitization in Baseline Tests ────────────────────────────────────


def test_baseline_does_not_leak_secrets(tmp_path) -> None:
    """Promoted baseline must not contain raw secrets from config_snapshot."""
    store_dir = tmp_path / "runs"
    baseline_dir = tmp_path / "baselines"
    run = _make_run(
        "secret-run",
        config_snapshot={
            "api_key": "super-secret-key-12345",
            "safe_field": "visible-value",
            "nested": {"password": "hunter2", "ok": "yes"},
        },
    )
    _persist_run(run, store_dir)

    promote_run_to_baseline(
        "secret-run", store_dir=store_dir, baseline_dir=baseline_dir, baseline_id="bl-sec"
    )

    baseline_raw = json.loads((baseline_dir / "bl-sec.json").read_text(encoding="utf-8"))
    config = baseline_raw.get("config_snapshot", {})
    assert config.get("api_key") == "[REDACTED]"
    assert config.get("safe_field") == "visible-value"
    assert config["nested"]["password"] == "[REDACTED]"
    assert config["nested"]["ok"] == "yes"

    # Ensure raw secret is not present anywhere in the file
    full_text = (baseline_dir / "bl-sec.json").read_text()
    assert "super-secret-key-12345" not in full_text
    assert "hunter2" not in full_text


# ── Registry Corruption Tests ────────────────────────────────────────────────


def test_registry_corrupt_raises_on_list(tmp_path) -> None:
    """A corrupt registry raises BaselineCorruptError on list."""
    baseline_dir = tmp_path / "baselines"
    baseline_dir.mkdir()
    (baseline_dir / BASELINE_REGISTRY_NAME).write_text("not json")
    with pytest.raises(BaselineCorruptError, match="corrupt"):
        list_baselines(baseline_dir=baseline_dir)


def test_registry_corrupt_raises_on_promote(tmp_path) -> None:
    """A corrupt registry raises BaselineCorruptError on promote."""
    store_dir = tmp_path / "runs"
    baseline_dir = tmp_path / "baselines"
    baseline_dir.mkdir()
    (baseline_dir / BASELINE_REGISTRY_NAME).write_text("not json")
    run = _make_run("run-corrupt-reg")
    _persist_run(run, store_dir)
    with pytest.raises(BaselineCorruptError, match="corrupt"):
        promote_run_to_baseline("run-corrupt-reg", store_dir=store_dir, baseline_dir=baseline_dir)


# ── Delta with Strict Baseline Tests ─────────────────────────────────────────


def test_delta_computation_with_strict_loader(tmp_path) -> None:
    """Delta computation works with load_baseline_metrics_strict."""
    from ragrig.evaluation.engine import _compute_regression_delta

    baseline_path = tmp_path / "base.json"
    baseline_run = _make_run(
        "base",
        metrics=EvaluationMetrics(
            total_questions=2,
            hit_at_1=1.0,
            hit_at_3=1.0,
            hit_at_5=1.0,
            mrr=1.0,
            mean_rank_of_expected=1.0,
            citation_coverage_mean=1.0,
            zero_result_rate=0.0,
        ),
    )
    baseline_path.write_text(baseline_run.model_dump_json(), encoding="utf-8")

    baseline_metrics = load_baseline_metrics_strict(baseline_path)
    current = EvaluationMetrics(
        total_questions=2,
        hit_at_1=0.5,
        hit_at_3=0.5,
        hit_at_5=1.0,
        mrr=0.75,
        mean_rank_of_expected=1.5,
        citation_coverage_mean=0.5,
        zero_result_rate=0.0,
    )
    delta = _compute_regression_delta(current, baseline_metrics)
    assert delta["hit_at_1"] == -0.5
    assert delta["mrr"] == -0.25
    assert delta["mean_rank_of_expected"] == 0.5
    assert delta["citation_coverage_mean"] == -0.5
