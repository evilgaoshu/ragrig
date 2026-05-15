from __future__ import annotations

import argparse
import json
import os
import shlex
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

SECRET_REDACTED_KEYS = {
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


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        result: dict[str, Any] = {}
        for k, v in obj.items():
            if any(p in k.lower() for p in SECRET_REDACTED_KEYS):
                result[k] = "[redacted]"
            else:
                result[k] = _redact(v)
        return result
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    if isinstance(obj, str):
        for fragment in _FORBIDDEN_FRAGMENTS:
            if fragment in obj:
                return "[redacted]"
    return obj


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


def _count_entities(dsn: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                for table, key in [
                    ("knowledge_bases", "kb_count"),
                    ("sources", "source_count"),
                    ("documents", "document_count"),
                    ("document_versions", "document_version_count"),
                    ("chunks", "chunk_count"),
                ]:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    row = cur.fetchone()
                    counts[key] = row[0] if row else 0
    except Exception:
        pass
    return counts


def find_latest_backup(backup_dir: Path) -> Path | None:
    backups = sorted(backup_dir.glob("backup_*"))
    return backups[-1] if backups else None


def find_latest_restorable_backup(backup_dir: Path) -> Path | None:
    backups = sorted(backup_dir.glob("backup_*"), reverse=True)
    for backup in backups:
        if _find_dump_file(backup) is not None:
            return backup
    return None


def _find_dump_file(backup_path: Path) -> Path | None:
    pg_dir = backup_path / "postgres"
    if not pg_dir.exists():
        return None
    dumps = sorted(pg_dir.glob("ragrig_*.dump"))
    return dumps[-1] if dumps else None


def check_health(dsn: str) -> dict[str, Any]:
    result: dict[str, Any] = {"name": "health_check", "status": "pass", "detail": None}
    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        result["detail"] = "database connected"
    except Exception as exc:
        result["status"] = "failure"
        result["detail"] = str(exc)
    return result


def check_revision(dsn: str, expected: str) -> dict[str, Any]:
    result: dict[str, Any] = {"name": "schema_revision_check", "status": "pass", "detail": None}
    current = _get_current_revision(dsn)
    if current is None:
        result["status"] = "failure"
        result["detail"] = "unable to read alembic_version"
    elif current != expected:
        result["status"] = "failure"
        result["detail"] = f"revision mismatch: current={current} expected={expected}"
    else:
        result["detail"] = f"revision {current} matches expected {expected}"
    return result


def check_entity_counts(dsn: str, expected: dict[str, int]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": "entity_count_check",
        "status": "pass",
        "detail": None,
        "expected": expected,
    }
    actual = _count_entities(dsn)
    result["actual"] = actual
    mismatches: list[str] = []
    for key, exp_val in expected.items():
        act_val = actual.get(key, -1)
        if act_val != exp_val:
            mismatches.append(f"{key}: expected={exp_val} actual={act_val}")
    if mismatches:
        result["status"] = "failure"
        result["detail"] = "; ".join(mismatches)
    else:
        result["detail"] = "all entity counts match"
    return result


def restore_postgres(dsn: str, dump_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"name": "postgres_restore", "status": "pass", "detail": None}
    try:
        resolved = _resolve_pg_restore_command(dsn)
        if resolved is None:
            result["status"] = "degraded"
            result["detail"] = (
                "pg_restore not found on PATH and Docker Compose db fallback is unavailable; "
                "set PG_RESTORE=/path/to/pg_restore or use PG_RESTORE_COMMAND with a "
                "pg_restore-compatible command."
            )
            return result

        cmd, stdin_dump, source = resolved
        cmd = [*cmd, "--clean", "--if-exists", "--no-owner", "--no-acl"]
        input_bytes = None
        if stdin_dump:
            input_bytes = dump_path.read_bytes()
        else:
            cmd.append(str(dump_path))
        proc = subprocess.run(
            cmd,
            input=input_bytes,
            env=os.environ.copy(),
            check=False,
            capture_output=True,
            timeout=300,
            cwd=str(REPO_ROOT),
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or b"").decode("utf-8", errors="replace")
            result["status"] = "failure"
            result["detail"] = f"pg_restore failed via {source}: {detail[:500]}"
        else:
            result["detail"] = f"restored from {dump_path.name} via {source}"
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr or exc.stdout or ""
        result["status"] = "failure"
        result["detail"] = f"pg_restore failed: {detail[:500]}"
    except FileNotFoundError as exc:
        result["status"] = "degraded"
        result["detail"] = f"pg_restore command not found: {exc.filename}"
    except Exception as exc:
        result["status"] = "failure"
        result["detail"] = str(exc)
    return result


def _resolve_pg_restore_command(dsn: str) -> tuple[list[str], bool, str] | None:
    command = os.environ.get("PG_RESTORE_COMMAND")
    if command:
        return shlex.split(command), True, "PG_RESTORE_COMMAND"

    executable = os.environ.get("PG_RESTORE", "pg_restore")
    if shutil.which(executable):
        return [executable, "-d", dsn], False, "host pg_restore"

    docker_tool = [
        "docker",
        "compose",
        "exec",
        "-T",
        "db",
        "pg_restore",
    ]
    docker_cmd = [
        *docker_tool,
        "-U",
        "ragrig",
        "-d",
        "ragrig",
    ]
    probe = subprocess.run(
        [*docker_tool, "--version"],
        capture_output=True,
        text=True,
        timeout=15,
        cwd=str(REPO_ROOT),
    )
    if probe.returncode == 0:
        return docker_cmd, True, "docker compose db pg_restore"

    return None


def restore_config(backup_path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"name": "config_restore", "status": "pass", "detail": None}
    cfg_dir = backup_path / "config"
    if not cfg_dir.exists():
        result["status"] = "degraded"
        result["detail"] = "config backup not found"
        return result

    config_files = [*cfg_dir.glob(".env*"), *cfg_dir.glob("settings.redacted.json")]
    if config_files:
        result["detail"] = f"config backup available at {config_files[0].name}"
    else:
        result["status"] = "degraded"
        result["detail"] = "no config files in backup"
    return result


def run_restore(settings, backup_dir: Path | None = None) -> dict[str, Any]:
    if backup_dir is None:
        backup_dir = DEFAULT_BACKUP_DIR
    timestamp = datetime.now(timezone.utc)
    snapshot_id = timestamp.strftime("%Y%m%dT%H%M%SZ")

    latest = find_latest_restorable_backup(backup_dir) or find_latest_backup(backup_dir)
    if latest is None:
        return {
            "artifact": "ops-restore-summary",
            "version": "1.0.0",
            "generated_at": timestamp.isoformat(),
            "snapshot_id": snapshot_id,
            "schema_revision": "unknown",
            "operation_status": "failure",
            "verification_checks": [
                {"name": "backup_exists", "status": "failure", "detail": "no backup found"}
            ],
            "report_path": str(ARTIFACTS_DIR / "ops-restore-summary.json"),
        }

    schema_revision = _get_head_revision()

    checks: list[dict[str, Any]] = [
        {"name": "backup_exists", "status": "pass", "detail": f"found backup at {latest.name}"},
    ]

    dump_path = _find_dump_file(latest)
    if dump_path is None or not dump_path.exists():
        checks.append(
            {"name": "dump_file", "status": "failure", "detail": "no dump file in backup"}
        )
        overall = "failure"
    else:
        checks.append(
            {
                "name": "dump_file",
                "status": "pass",
                "detail": f"dump file {dump_path.name} ({dump_path.stat().st_size} bytes)",
            }
        )
        checks.append(check_health(settings.database_url))

        pre_counts = _count_entities(settings.database_url)
        checks.append(restore_postgres(settings.database_url, dump_path))
        checks.append(check_health(settings.database_url))
        checks.append(check_revision(settings.database_url, schema_revision))
        checks.append(check_entity_counts(settings.database_url, pre_counts))
        checks.append(restore_config(latest))

        overall = "success" if all(c["status"] == "pass" for c in checks) else "failure"
        if overall == "failure" and any(c["status"] == "degraded" for c in checks):
            overall = "degraded"

    summary: dict[str, Any] = {
        "artifact": "ops-restore-summary",
        "version": "1.0.0",
        "generated_at": timestamp.isoformat(),
        "snapshot_id": snapshot_id,
        "backup_path": str(latest),
        "schema_revision": schema_revision or "unknown",
        "operation_status": overall,
        "verification_checks": checks,
        "report_path": str(ARTIFACTS_DIR / "ops-restore-summary.json"),
    }

    summary = _redact(summary)
    _assert_no_raw_secrets(summary, "ops-restore-summary")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="RAGRig restore smoke")
    parser.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_DIR))
    parser.add_argument("--output", default=str(ARTIFACTS_DIR / "ops-restore-summary.json"))
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    backup_dir = Path(args.backup_dir)
    summary = run_restore(settings, backup_dir=backup_dir)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if args.pretty:
        print(json.dumps(summary, indent=2))
    else:
        print(f"snapshot_id={summary['snapshot_id']} status={summary['operation_status']}")

    return 0 if summary["operation_status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
