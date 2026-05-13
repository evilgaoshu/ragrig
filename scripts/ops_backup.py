from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg

from ragrig.config import get_settings

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = REPO_ROOT / "docs" / "operations" / "artifacts"
DEFAULT_BACKUP_DIR = REPO_ROOT / "backups"

_FORBIDDEN_FRAGMENTS: tuple[str, ...] = (
    "sk-live-",
    "sk-proj-",
    "sk-ant-",
    "ghp_",
    "Bearer ",
    "PRIVATE KEY-----",
)


def _assert_no_raw_secrets(data: object, source: str) -> None:
    if isinstance(data, str):
        for fragment in _FORBIDDEN_FRAGMENTS:
            if fragment in data:
                raise RuntimeError(f"{source}: raw secret fragment {fragment!r} detected in output")
    elif isinstance(data, dict):
        for k, v in data.items():
            _assert_no_raw_secrets(v, f"{source}.{k}")
    elif isinstance(data, list):
        for i, v in enumerate(data):
            _assert_no_raw_secrets(v, f"{source}[{i}]")


def _get_head_revision() -> str:
    versions_dir = REPO_ROOT / "alembic" / "versions"
    if not versions_dir.exists():
        return ""
    files = sorted(versions_dir.glob("*.py"))
    for f in reversed(files):
        name = f.stem
        parts = name.split("_")
        if len(parts) >= 2:
            return f"{parts[0]}_{parts[1]}"
    return ""


def _get_current_revision(dsn: str) -> str | None:
    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version_num FROM alembic_version LIMIT 1")
                row = cur.fetchone()
                return row[0] if row else None
    except Exception:
        return None


def _redact_config(obj: Any) -> Any:
    redacted_keys = {
        "dsn",
        "password",
        "api_key",
        "access_key",
        "secret",
        "token",
        "credential",
        "private_key",
        "session_token",
        "service_account",
        "database_url",
    }
    if isinstance(obj, dict):
        result: dict[str, Any] = {}
        for k, v in obj.items():
            if any(p in k.lower() for p in redacted_keys):
                result[k] = "[redacted]"
            else:
                result[k] = _redact_config(v)
        return result
    if isinstance(obj, list):
        return [_redact_config(v) for v in obj]
    if isinstance(obj, str):
        for fragment in _FORBIDDEN_FRAGMENTS:
            if fragment in obj:
                return "[redacted]"
    return obj


def backup_postgres(settings, backup_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"name": "postgres_backup", "status": "pass", "detail": None}
    try:
        pg_dir = backup_dir / "postgres"
        pg_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dump_path = pg_dir / f"ragrig_{timestamp}.dump"

        env = os.environ.copy()
        cmd = ["pg_dump", "--format=custom", "--no-owner", "--no-acl", "-f", str(dump_path)]
        subprocess.run(cmd, env=env, check=True, capture_output=True, text=True, timeout=120)

        result["dump_path"] = str(dump_path)
        result["size_bytes"] = dump_path.stat().st_size if dump_path.exists() else 0
    except subprocess.CalledProcessError as exc:
        result["status"] = "failure"
        result["detail"] = f"pg_dump failed: {exc.stderr or exc.stdout}"
    except FileNotFoundError:
        result["status"] = "degraded"
        result["detail"] = (
            "pg_dump not found on PATH; try `make ops-backup-smoke PG_DUMP=/path/to/pg_dump`"
        )
    except Exception as exc:
        result["status"] = "failure"
        result["detail"] = str(exc)
    return result


def backup_config(settings, backup_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"name": "config_backup", "status": "pass", "detail": None}
    try:
        cfg_dir = backup_dir / "config"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        env_path = REPO_ROOT / ".env"
        if env_path.exists():
            redacted_lines: list[str] = []
            for line in env_path.read_text(encoding="utf-8").splitlines(keepends=True):
                stripped = line.strip()
                if any(
                    stripped.lower().startswith(k)
                    for k in ("dsn", "password", "api_key", "access_key", "secret", "token")
                ):
                    key = stripped.split("=", 1)[0] if "=" in stripped else stripped
                    redacted_lines.append(f"{key}=[redacted]\n")
                else:
                    redacted_lines.append(line)
            cfg_copy = cfg_dir / ".env.redacted"
            cfg_copy.write_text("".join(redacted_lines), encoding="utf-8")
            result["config_path"] = str(cfg_copy)
        else:
            result["status"] = "degraded"
            result["detail"] = ".env not found"
    except Exception as exc:
        result["status"] = "failure"
        result["detail"] = str(exc)
    return result


def backup_artifacts(backup_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"name": "artifacts_backup", "status": "pass", "detail": None}
    try:
        arts_dir = backup_dir / "artifacts"
        arts_dir.mkdir(parents=True, exist_ok=True)
        if ARTIFACTS_DIR.exists():
            shutil.copytree(ARTIFACTS_DIR, arts_dir, dirs_exist_ok=True)
            result["artifact_count"] = len(list(arts_dir.rglob("*")))
        else:
            result["status"] = "degraded"
            result["detail"] = "artifacts directory not found"
    except Exception as exc:
        result["status"] = "failure"
        result["detail"] = str(exc)
    return result


def backup_vector_config(settings, backup_dir: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"name": "vector_config_backup", "status": "pass", "detail": None}
    try:
        vec_dir = backup_dir / "vector"
        vec_dir.mkdir(parents=True, exist_ok=True)
        snapshot: dict[str, Any] = {
            "backend": settings.vector_backend,
            "qdrant_url": str(settings.qdrant_url),
            "qdrant_api_key_present": settings.qdrant_api_key is not None,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        snapshot_path = vec_dir / "vector-config.json"
        safe = _redact_config(snapshot)
        snapshot_path.write_text(json.dumps(safe, indent=2), encoding="utf-8")
        result["snapshot_path"] = str(snapshot_path)
    except Exception as exc:
        result["status"] = "failure"
        result["detail"] = str(exc)
    return result


def run_backup(settings, backup_dir: Path | None = None) -> dict[str, Any]:
    if backup_dir is None:
        backup_dir = DEFAULT_BACKUP_DIR
    timestamp = datetime.now(timezone.utc)
    snapshot_id = timestamp.strftime("%Y%m%dT%H%M%SZ")
    backup_root = backup_dir / f"backup_{snapshot_id}"
    backup_root.mkdir(parents=True, exist_ok=True)

    checks = [
        backup_postgres(settings, backup_root),
        backup_config(settings, backup_root),
        backup_artifacts(backup_root),
        backup_vector_config(settings, backup_root),
    ]

    schema_revision = _get_head_revision()
    overall = "success" if all(c["status"] == "pass" for c in checks) else "failure"
    if overall == "failure" and any(c["status"] == "degraded" for c in checks):
        overall = "degraded"

    summary: dict[str, Any] = {
        "artifact": "ops-backup-summary",
        "version": "1.0.0",
        "generated_at": timestamp.isoformat(),
        "snapshot_id": snapshot_id,
        "backup_path": str(backup_root),
        "schema_revision": schema_revision or "unknown",
        "operation_status": overall,
        "verification_checks": checks,
        "report_path": str(ARTIFACTS_DIR / "ops-backup-summary.json"),
    }

    summary = _redact_config(summary)
    _assert_no_raw_secrets(summary, "ops-backup-summary")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="RAGRig backup smoke")
    parser.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_DIR))
    parser.add_argument("--output", default=str(ARTIFACTS_DIR / "ops-backup-summary.json"))
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    backup_dir = Path(args.backup_dir)
    summary = run_backup(settings, backup_dir=backup_dir)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if args.pretty:
        print(json.dumps(summary, indent=2))
    else:
        print(f"snapshot_id={summary['snapshot_id']} status={summary['operation_status']}")

    return 0 if summary["operation_status"] == "success" else 1


if __name__ == "__main__":
    import os

    raise SystemExit(main())
