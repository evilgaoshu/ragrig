"""Baseline management for Golden Question Evaluation.

Provides:
- promote_run_to_baseline: copy a run to the baseline directory with metadata and manifest
- resolve_baseline_path: resolve a baseline id or path to a file path
- list_baselines: list all baselines with metadata and integrity status
- load_baseline_metrics: load metrics from a baseline (with strict error handling)
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from ragrig.evaluation.baseline_manifest import (
    build_manifest,
    get_baseline_integrity_status,
    validate_baseline_manifest,
    write_manifest,
)
from ragrig.evaluation.models import EvaluationMetrics

DEFAULT_BASELINE_DIR = Path("evaluation_baselines")
BASELINE_REGISTRY_NAME = "baseline_registry.json"


class BaselineError(Exception):
    """Raised when baseline operations fail."""

    pass


class BaselineNotFoundError(BaselineError):
    """Raised when a requested baseline does not exist."""

    pass


class BaselineCorruptError(BaselineError):
    """Raised when a baseline file is corrupt or unreadable."""

    pass


def _baseline_registry_path(baseline_dir: Path) -> Path:
    return baseline_dir / BASELINE_REGISTRY_NAME


def _load_registry(baseline_dir: Path) -> dict[str, Any]:
    """Load the baseline registry, creating empty if missing."""
    reg_path = _baseline_registry_path(baseline_dir)
    if not reg_path.exists():
        return {"version": "1.0.0", "baselines": [], "current_baseline_id": None}
    try:
        return json.loads(reg_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise BaselineCorruptError(f"Baseline registry is corrupt: {exc}") from exc


def _save_registry(baseline_dir: Path, registry: dict[str, Any]) -> None:
    """Save the baseline registry atomically."""
    reg_path = _baseline_registry_path(baseline_dir)
    baseline_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = reg_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(reg_path)


def promote_run_to_baseline(
    run_id: str,
    *,
    store_dir: Path | None = None,
    baseline_dir: Path | None = None,
    baseline_id: str | None = None,
    promoted_by: str | None = None,
    golden_set_name: str | None = None,
) -> dict[str, Any]:
    """Promote an evaluation run to a baseline.

    Copies the run JSON from store_dir to baseline_dir, records metadata
    in the baseline registry, writes an integrity manifest, and returns
    the baseline metadata.
    """
    from ragrig.evaluation.engine import DEFAULT_EVAL_DIR, load_run_from_store

    store_dir = store_dir or DEFAULT_EVAL_DIR
    baseline_dir = baseline_dir or DEFAULT_BASELINE_DIR

    run = load_run_from_store(run_id, store_dir=store_dir)
    if run is None:
        raise BaselineNotFoundError(f"Run not found in store: {run_id}")

    baseline_id = baseline_id or f"baseline-{uuid.uuid4().hex[:8]}"
    baseline_path = baseline_dir / f"{baseline_id}.json"
    baseline_dir.mkdir(parents=True, exist_ok=True)

    # Copy run JSON to baseline dir (with redaction already applied by persistence)
    raw = json.loads((store_dir / f"{run_id}.json").read_text(encoding="utf-8"))
    baseline_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")

    # Write integrity manifest
    manifest = build_manifest(
        baseline_id=baseline_id,
        source_run_id=run_id,
        report_path=baseline_path,
        metrics=run.metrics,
        created_at=run.created_at,
    )
    write_manifest(manifest, baseline_path)

    registry = _load_registry(baseline_dir)

    # Remove any existing baseline with same id
    registry["baselines"] = [b for b in registry["baselines"] if b["id"] != baseline_id]

    try:
        rel_path = str(baseline_path.relative_to(Path.cwd()))
    except ValueError:
        rel_path = str(baseline_path)
    metadata = {
        "id": baseline_id,
        "created_at": run.created_at,
        "promoted_at": _now_iso(),
        "source_run_id": run_id,
        "promoted_by": promoted_by or os.environ.get("USER", "unknown"),
        "golden_set_name": golden_set_name or run.golden_set_name,
        "knowledge_base": run.knowledge_base,
        "metrics": run.metrics.model_dump(),
        "path": rel_path,
        "manifest": manifest,
    }
    registry["baselines"].append(metadata)
    registry["current_baseline_id"] = baseline_id
    _save_registry(baseline_dir, registry)

    return metadata


def resolve_baseline_path(
    baseline_id_or_path: str,
    baseline_dir: Path | None = None,
) -> Path:
    """Resolve a baseline identifier or path to an absolute Path.

    If baseline_id_or_path is an existing file path, return it directly.
    Otherwise look it up in the baseline registry by id.
    """
    baseline_dir = baseline_dir or DEFAULT_BASELINE_DIR

    # Direct file path
    direct = Path(baseline_id_or_path)
    if direct.exists() and direct.is_file():
        return direct.resolve()

    # Look up in registry
    registry = _load_registry(baseline_dir)
    for baseline in registry.get("baselines", []):
        if baseline["id"] == baseline_id_or_path:
            path = Path(baseline["path"])
            if path.exists():
                return path.resolve()
            # Fallback to baseline_dir / id.json
            fallback = baseline_dir / f"{baseline_id_or_path}.json"
            if fallback.exists():
                return fallback.resolve()
            raise BaselineNotFoundError(
                f"Baseline '{baseline_id_or_path}' recorded but file missing: {path}"
            )

    # Try baseline_dir / <id>.json directly without registry
    fallback = baseline_dir / f"{baseline_id_or_path}.json"
    if fallback.exists():
        return fallback.resolve()

    raise BaselineNotFoundError(f"Baseline not found: {baseline_id_or_path}")


def list_baselines(
    baseline_dir: Path | None = None,
) -> dict[str, Any]:
    """List all baselines and the current baseline id with integrity status."""
    baseline_dir = baseline_dir or DEFAULT_BASELINE_DIR
    registry = _load_registry(baseline_dir)
    baselines = registry.get("baselines", [])
    enriched = []
    for baseline in baselines:
        entry = dict(baseline)
        # Remove manifest from API response to keep it clean; integrity status is enough
        entry.pop("manifest", None)
        path = Path(baseline.get("path", ""))
        if not path.exists():
            fallback = baseline_dir / f"{baseline['id']}.json"
            if fallback.exists():
                path = fallback
        if path.exists():
            integrity = get_baseline_integrity_status(
                path,
                auto_backfill=True,
                baseline_id=baseline.get("id"),
                source_run_id=baseline.get("source_run_id"),
                created_at=baseline.get("created_at"),
            )
            entry["integrity_status"] = integrity
        else:
            entry["integrity_status"] = {
                "status": "missing_file",
                "reason": f"Baseline file not found: {path}",
            }
        # Ensure no secrets leak through API
        entry.pop("config_snapshot", None)
        entry.pop("items", None)
        enriched.append(entry)
    return {
        "current_baseline_id": registry.get("current_baseline_id"),
        "baselines": enriched,
    }


def load_baseline_metrics_strict(
    baseline_path: Path,
) -> EvaluationMetrics:
    """Load baseline metrics with strict error handling.

    Validates manifest integrity before loading metrics.
    Raises BaselineNotFoundError or BaselineCorruptError instead of returning None.
    """
    if not baseline_path.exists():
        raise BaselineNotFoundError(f"Baseline file not found: {baseline_path}")

    # Validate manifest integrity (let specific manifest errors propagate)
    validate_baseline_manifest(
        baseline_path,
        auto_backfill=True,
        baseline_id=baseline_path.stem,
    )

    try:
        raw = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise BaselineCorruptError(f"Baseline file is corrupt: {exc}") from exc

    metrics_raw = raw.get("metrics")
    if not metrics_raw or not isinstance(metrics_raw, dict):
        raise BaselineCorruptError(f"Baseline file missing 'metrics' object: {baseline_path}")
    try:
        return EvaluationMetrics.model_validate(metrics_raw)
    except Exception as exc:
        raise BaselineCorruptError(f"Baseline metrics schema invalid: {exc}") from exc


def get_current_baseline_id(baseline_dir: Path | None = None) -> str | None:
    """Return the current baseline id from registry, or None."""
    baseline_dir = baseline_dir or DEFAULT_BASELINE_DIR
    registry = _load_registry(baseline_dir)
    return registry.get("current_baseline_id")


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
