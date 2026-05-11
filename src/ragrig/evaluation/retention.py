"""Retention and cleanup for evaluation runs.

Provides policies to remove old evaluation runs while protecting
baselines and the current baseline.
"""

from __future__ import annotations

import time
from pathlib import Path

from ragrig.evaluation.baseline import (
    DEFAULT_BASELINE_DIR,
    _load_registry,
    get_current_baseline_id,
)
from ragrig.evaluation.engine import DEFAULT_EVAL_DIR


def cleanup_evaluation_runs(
    store_dir: Path | None = None,
    baseline_dir: Path | None = None,
    *,
    keep_count: int | None = None,
    keep_days: int | None = None,
    dry_run: bool = False,
) -> dict[str, list[str]]:
    """Clean up evaluation runs according to retention policy.

    Args:
        store_dir: Directory containing evaluation run JSONs.
        baseline_dir: Directory containing baselines.
        keep_count: Retain at most this many newest runs (by mtime).
        keep_days: Retain runs newer than this many days.
        dry_run: If True, only report what would be deleted.

    Returns:
        Dict with 'deleted' and 'protected' lists of file names.
    """
    store_dir = store_dir or DEFAULT_EVAL_DIR
    baseline_dir = baseline_dir or DEFAULT_BASELINE_DIR

    if not store_dir.exists():
        return {"deleted": [], "protected": []}

    # Determine protected run IDs (any run referenced by a baseline)
    protected_ids: set[str] = set()
    registry = _load_registry(baseline_dir)
    for baseline in registry.get("baselines", []):
        source_run_id = baseline.get("source_run_id")
        if source_run_id:
            protected_ids.add(source_run_id)
        # Also protect baseline json files themselves if they happen to be in store_dir
        baseline_id = baseline.get("id")
        if baseline_id:
            protected_ids.add(baseline_id)

    # Also protect current baseline id
    current_baseline_id = get_current_baseline_id(baseline_dir)
    if current_baseline_id:
        protected_ids.add(current_baseline_id)

    # Collect run files with stats
    run_files: list[Path] = []
    for path in store_dir.glob("*.json"):
        if path.is_file():
            run_files.append(path)

    # Sort by mtime descending (newest first)
    run_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    now = time.time()
    day_seconds = 24 * 3600

    deleted: list[str] = []
    protected: list[str] = []

    for idx, path in enumerate(run_files):
        stem = path.stem
        if stem in protected_ids:
            protected.append(path.name)
            continue

        # Check keep_count
        if keep_count is not None and idx < keep_count:
            protected.append(path.name)
            continue

        # Check keep_days
        if keep_days is not None:
            age_days = (now - path.stat().st_mtime) / day_seconds
            if age_days < keep_days:
                protected.append(path.name)
                continue

        # Delete
        if not dry_run:
            path.unlink()
        deleted.append(path.name)

    return {"deleted": deleted, "protected": protected}
