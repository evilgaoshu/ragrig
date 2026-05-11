"""Baseline manifest: integrity checksum, schema version, and compatibility.

Provides:
- Manifest read/write alongside baseline JSON files
- Metrics hash (SHA-256 of canonical metrics JSON)
- Schema compatibility checking
- Legacy baseline backfill (auto-generate manifest for old baselines)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ragrig.evaluation.models import EvaluationMetrics

MANIFEST_SCHEMA_VERSION = "1.0.0"
COMPATIBLE_EVAL_SCHEMA = "1.0.0"
MANIFEST_SUFFIX = ".manifest.json"


class BaselineManifestMissingError(Exception):
    """Raised when a baseline manifest is missing."""

    pass


class BaselineManifestCorruptError(Exception):
    """Raised when a baseline manifest is corrupt or unreadable."""

    pass


class BaselineHashMismatchError(Exception):
    """Raised when baseline metrics hash does not match manifest."""

    pass


class BaselineIncompatibleSchemaError(Exception):
    """Raised when baseline manifest schema version is incompatible."""

    pass


def _manifest_path(baseline_path: Path) -> Path:
    """Return the manifest path for a given baseline file path."""
    return baseline_path.with_suffix("").with_suffix(MANIFEST_SUFFIX)


def _compute_metrics_hash(metrics: EvaluationMetrics | dict[str, Any]) -> str:
    """Compute a SHA-256 hash of canonical metrics JSON for integrity."""
    if isinstance(metrics, EvaluationMetrics):
        metrics = metrics.model_dump()
    canonical = json.dumps(metrics, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def build_manifest(
    baseline_id: str,
    source_run_id: str,
    report_path: Path,
    metrics: EvaluationMetrics | dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    """Build a manifest dict for a baseline."""
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "baseline_id": baseline_id,
        "source_run_id": source_run_id,
        "report_path": str(report_path),
        "metrics_hash": _compute_metrics_hash(metrics),
        "created_at": created_at,
        "compatible_eval_schema": COMPATIBLE_EVAL_SCHEMA,
    }


def write_manifest(manifest: dict[str, Any], baseline_path: Path) -> Path:
    """Write manifest next to the baseline file. Returns the manifest path."""
    path = _manifest_path(baseline_path)
    path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def read_manifest(baseline_path: Path) -> dict[str, Any]:
    """Read manifest for a baseline, raising on missing or corrupt."""
    path = _manifest_path(baseline_path)
    if not path.exists():
        raise BaselineManifestMissingError(
            f"Baseline manifest missing: {path.name}"
        )
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise BaselineManifestCorruptError(
            f"Baseline manifest is corrupt: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise BaselineManifestCorruptError(
            f"Baseline manifest is not a JSON object: {path}"
        )
    return raw


def _validate_manifest_schema(manifest: dict[str, Any]) -> None:
    """Validate manifest schema version is compatible."""
    schema_version = manifest.get("schema_version")
    if schema_version != MANIFEST_SCHEMA_VERSION:
        raise BaselineIncompatibleSchemaError(
            f"Incompatible manifest schema_version: {schema_version} "
            f"(expected {MANIFEST_SCHEMA_VERSION})"
        )


def _validate_metrics_hash(baseline_path: Path, manifest: dict[str, Any]) -> None:
    """Validate baseline metrics hash against manifest."""
    expected_hash = manifest.get("metrics_hash")
    if not expected_hash:
        raise BaselineManifestCorruptError(
            "Baseline manifest missing 'metrics_hash'"
        )
    if not baseline_path.exists():
        raise BaselineManifestMissingError(
            f"Baseline file missing: {baseline_path}"
        )
    try:
        raw = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise BaselineManifestCorruptError(
            f"Baseline file is corrupt: {exc}"
        ) from exc
    metrics_raw = raw.get("metrics")
    if not metrics_raw or not isinstance(metrics_raw, dict):
        raise BaselineManifestCorruptError(
            f"Baseline file missing 'metrics' object: {baseline_path}"
        )
    actual_hash = _compute_metrics_hash(metrics_raw)
    if actual_hash != expected_hash:
        raise BaselineHashMismatchError(
            f"Baseline metrics hash mismatch: expected {expected_hash}, got {actual_hash}"
        )


def validate_baseline_manifest(
    baseline_path: Path,
    *,
    auto_backfill: bool = True,
    baseline_id: str | None = None,
    source_run_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Validate a baseline's manifest and integrity.

    Args:
        baseline_path: Path to the baseline JSON file.
        auto_backfill: If True, auto-generate manifest for legacy baselines
            that have no manifest file.
        baseline_id: Required for backfill if manifest is missing.
        source_run_id: Required for backfill if manifest is missing.
        created_at: Required for backfill if manifest is missing.

    Returns:
        The validated manifest dict.

    Raises:
        BaselineManifestMissingError: If manifest is missing and cannot be backfilled.
        BaselineManifestCorruptError: If manifest or baseline file is corrupt.
        BaselineHashMismatchError: If metrics hash does not match.
        BaselineIncompatibleSchemaError: If schema version is incompatible.
    """
    try:
        manifest = read_manifest(baseline_path)
    except BaselineManifestMissingError:
        if not auto_backfill:
            raise
        if baseline_id is None or source_run_id is None or created_at is None:
            # Try to infer from baseline file content for best-effort backfill
            try:
                raw = json.loads(baseline_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                raise BaselineManifestCorruptError(
                    f"Baseline file is corrupt, cannot backfill manifest: {exc}"
                ) from exc
            inferred_id = baseline_id or raw.get("id") or baseline_path.stem
            inferred_run_id = source_run_id or raw.get("id") or "unknown"
            inferred_created_at = created_at or raw.get("created_at")
            if inferred_created_at is None:
                raise BaselineManifestMissingError(
                    f"Baseline manifest missing and cannot backfill (no created_at): "
                    f"{baseline_path}"
                ) from None
            metrics_raw = raw.get("metrics", {})
            manifest = build_manifest(
                baseline_id=inferred_id,
                source_run_id=inferred_run_id,
                report_path=baseline_path,
                metrics=metrics_raw,
                created_at=inferred_created_at,
            )
            write_manifest(manifest, baseline_path)
        else:
            # We have explicit values; generate manifest
            metrics_raw = {}
            if baseline_path.exists():
                try:
                    raw = json.loads(baseline_path.read_text(encoding="utf-8"))
                    metrics_raw = raw.get("metrics", {})
                except (json.JSONDecodeError, OSError):
                    pass
            manifest = build_manifest(
                baseline_id=baseline_id,
                source_run_id=source_run_id,
                report_path=baseline_path,
                metrics=metrics_raw,
                created_at=created_at,
            )
            write_manifest(manifest, baseline_path)

    _validate_manifest_schema(manifest)
    _validate_metrics_hash(baseline_path, manifest)
    return manifest


def get_baseline_integrity_status(
    baseline_path: Path,
    *,
    auto_backfill: bool = True,
    baseline_id: str | None = None,
    source_run_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Return integrity status dict for a baseline without raising.

    Safe for API/Web Console use. Never leaks raw secrets.
    """
    if not baseline_path.exists():
        return {
            "status": "missing_file",
            "reason": f"Baseline file not found: {baseline_path}",
        }
    try:
        manifest = validate_baseline_manifest(
            baseline_path,
            auto_backfill=auto_backfill,
            baseline_id=baseline_id,
            source_run_id=source_run_id,
            created_at=created_at,
        )
        return {
            "status": "valid",
            "schema_version": manifest.get("schema_version"),
            "metrics_hash": manifest.get("metrics_hash"),
            "compatible_eval_schema": manifest.get("compatible_eval_schema"),
            "created_at": manifest.get("created_at"),
        }
    except BaselineManifestMissingError as exc:
        return {"status": "missing_manifest", "reason": str(exc)}
    except BaselineManifestCorruptError as exc:
        return {"status": "corrupt", "reason": str(exc)}
    except BaselineHashMismatchError as exc:
        return {"status": "hash_mismatch", "reason": str(exc)}
    except BaselineIncompatibleSchemaError as exc:
        return {"status": "incompatible_schema", "reason": str(exc)}
    except Exception as exc:
        return {"status": "unknown_error", "reason": str(exc)}
