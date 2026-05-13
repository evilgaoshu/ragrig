from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg

from ragrig.config import get_settings

REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = REPO_ROOT / "docs" / "operations" / "artifacts"

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


def check_docker_compose() -> dict[str, Any]:
    result: dict[str, Any] = {"name": "docker_compose_check", "status": "pass", "detail": None}
    try:
        proc = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(REPO_ROOT),
        )
        if proc.returncode != 0:
            result["status"] = "failure"
            result["detail"] = "docker compose ps failed"
        else:
            lines = [ln for ln in proc.stdout.strip().split("\n") if ln]
            services = []
            for line in lines:
                try:
                    info = json.loads(line)
                    services.append(f"{info.get('Name', '?')}={info.get('State', '?')}")
                except json.JSONDecodeError:
                    services.append(line)
            result["detail"] = "; ".join(services) if services else "no services running"
    except FileNotFoundError:
        result["status"] = "degraded"
        result["detail"] = "docker not found on PATH"
    except subprocess.TimeoutExpired:
        result["status"] = "failure"
        result["detail"] = "docker compose ps timed out"
    except Exception as exc:
        result["status"] = "failure"
        result["detail"] = str(exc)
    return result


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


def check_vector_extension(dsn: str) -> dict[str, Any]:
    result: dict[str, Any] = {"name": "vector_extension_check", "status": "pass", "detail": None}
    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
                row = cur.fetchone()
                if row:
                    result["detail"] = "pgvector extension installed"
                else:
                    result["status"] = "degraded"
                    result["detail"] = "pgvector extension not found"
    except Exception as exc:
        result["status"] = "failure"
        result["detail"] = str(exc)
    return result


def run_deploy_check(settings) -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc)
    snapshot_id = timestamp.strftime("%Y%m%dT%H%M%SZ")
    head_revision = _get_head_revision()

    checks: list[dict[str, Any]] = []
    checks.append(check_docker_compose())
    checks.append(check_health(settings.database_url))
    checks.append(check_vector_extension(settings.database_url))

    current_revision = _get_current_revision(settings.database_url)
    checks.append(
        {
            "name": "schema_revision",
            "status": "pass" if current_revision == head_revision else "failure",
            "detail": f"revision={current_revision or 'unknown'}, expected={head_revision}",
        }
    )

    overall = "success" if all(c["status"] == "pass" for c in checks) else "failure"
    if overall == "failure" and any(c["status"] == "degraded" for c in checks):
        overall = "degraded"

    summary: dict[str, Any] = {
        "artifact": "ops-deploy-summary",
        "version": "1.0.0",
        "generated_at": timestamp.isoformat(),
        "snapshot_id": snapshot_id,
        "schema_revision": head_revision or "unknown",
        "operation_status": overall,
        "verification_checks": checks,
        "report_path": str(ARTIFACTS_DIR / "ops-deploy-summary.json"),
    }

    summary = _redact(summary)
    _assert_no_raw_secrets(summary, "ops-deploy-summary")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="RAGRig deploy smoke")
    parser.add_argument("--output", default=str(ARTIFACTS_DIR / "ops-deploy-summary.json"))
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    summary = run_deploy_check(settings)

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
