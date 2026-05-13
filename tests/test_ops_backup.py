from pathlib import Path

import pytest

from scripts.ops_backup import (
    _assert_no_raw_secrets,
    _redact_config,
    run_backup,
)
from scripts.ops_deploy import run_deploy_check
from scripts.ops_restore import (
    _find_dump_file,
    _redact,
    find_latest_backup,
)
from scripts.ops_upgrade import run_upgrade

pytestmark = pytest.mark.unit


def test_backup_redact_config_hides_secrets() -> None:
    config = {
        "database_url": "postgresql://user:pass@host/db",
        "api_key": "sk-live-abc123",
        "password": "secret123",
        "url": "http://localhost:8000",
        "name": "test",
    }
    safe = _redact_config(config)

    assert safe["database_url"] == "[redacted]"
    assert safe["api_key"] == "[redacted]"
    assert safe["password"] == "[redacted]"
    assert safe["url"] == "http://localhost:8000"
    assert safe["name"] == "test"


def test_restore_redact_hides_secrets() -> None:
    data = {
        "dsn": "postgresql://user:pass@host/db",
        "token": "ghp_abcdef123",
        "nested": {
            "secret_key": "supersecret",
            "safe_field": "hello",
        },
        "list_field": [{"credential": "sk-proj-xyz"}],
    }
    safe = _redact(data)

    assert safe["dsn"] == "[redacted]"
    assert safe["token"] == "[redacted]"
    assert safe["nested"]["secret_key"] == "[redacted]"
    assert safe["nested"]["safe_field"] == "hello"
    assert safe["list_field"][0]["credential"] == "[redacted]"


def test_assert_no_raw_secrets_passes_for_safe_data() -> None:
    safe = {"status": "ok", "items": [{"name": "test"}]}
    _assert_no_raw_secrets(safe, "test")


def test_assert_no_raw_secrets_raises_on_forbidden_fragment() -> None:
    import pytest

    unsafe = {"data": "This contains sk-live-abc123"}
    with pytest.raises(RuntimeError, match="raw secret fragment"):
        _assert_no_raw_secrets(unsafe, "test")


def test_backup_summary_structure(tmp_path) -> None:
    from ragrig.config import Settings

    settings = Settings(database_url="sqlite:///:memory:")
    backup_dir = tmp_path / "backups"

    summary = run_backup(settings, backup_dir=backup_dir)

    assert summary["artifact"] == "ops-backup-summary"
    assert summary["version"] == "1.0.0"
    assert "snapshot_id" in summary
    assert "schema_revision" in summary
    assert summary["operation_status"] in ("success", "failure", "degraded")
    assert isinstance(summary["verification_checks"], list)
    assert "report_path" in summary
    assert "backup_path" in summary


def test_backup_produces_files_on_disk(tmp_path) -> None:
    from ragrig.config import Settings

    settings = Settings(database_url="sqlite:///:memory:")
    backup_dir = tmp_path / "diskbackups"

    summary = run_backup(settings, backup_dir=backup_dir)

    backup_path = Path(summary["backup_path"])
    assert backup_path.exists()
    assert (backup_path / "config").exists()
    assert (backup_path / "vector").exists()


def test_restore_fails_without_backup(tmp_path) -> None:
    from ragrig.config import Settings
    from scripts.ops_restore import run_restore

    settings = Settings(database_url="sqlite:///:memory:")
    summary = run_restore(settings, backup_dir=tmp_path / "nonexistent")

    assert summary["artifact"] == "ops-restore-summary"
    assert summary["operation_status"] == "failure"
    assert any(
        c["name"] == "backup_exists" and c["status"] == "failure"
        for c in summary["verification_checks"]
    )


def test_restore_redact_function_handles_forbidden_fragments() -> None:
    obj = "Bearer sk-live-xxxx"
    safe = _redact(obj)
    assert safe == "[redacted]"


def test_find_latest_backup(tmp_path) -> None:
    (tmp_path / "backup_20260513T000000Z").mkdir(parents=True)
    (tmp_path / "backup_20260513T010000Z").mkdir(parents=True)

    latest = find_latest_backup(tmp_path)
    assert latest is not None
    assert latest.name == "backup_20260513T010000Z"


def test_find_latest_backup_empty(tmp_path) -> None:
    latest = find_latest_backup(tmp_path)
    assert latest is None


def test_find_dump_file(tmp_path) -> None:
    backup_path = tmp_path / "backup_test"
    pg_dir = backup_path / "postgres"
    pg_dir.mkdir(parents=True)
    dump = pg_dir / "ragrig_test.dump"
    dump.write_text("fake dump")

    found = _find_dump_file(backup_path)
    assert found == dump


def test_find_dump_file_missing(tmp_path) -> None:
    backup_path = tmp_path / "backup_test"
    backup_path.mkdir()
    found = _find_dump_file(backup_path)
    assert found is None


def test_deploy_summary_structure() -> None:
    from ragrig.config import Settings

    settings = Settings(database_url="sqlite:///:memory:")
    summary = run_deploy_check(settings)

    assert summary["artifact"] == "ops-deploy-summary"
    assert summary["version"] == "1.0.0"
    assert "snapshot_id" in summary
    assert summary["operation_status"] in ("success", "failure", "degraded")
    assert isinstance(summary["verification_checks"], list)


def test_upgrade_summary_structure() -> None:
    from ragrig.config import Settings

    settings = Settings(database_url="sqlite:///:memory:")
    summary = run_upgrade(settings)

    assert summary["artifact"] == "ops-upgrade-summary"
    assert summary["version"] == "1.0.0"
    assert "snapshot_id" in summary
    assert "pre_upgrade_revision" in summary
    assert "post_upgrade_revision" in summary
    assert summary["operation_status"] in ("success", "failure", "degraded")
    assert isinstance(summary["verification_checks"], list)
