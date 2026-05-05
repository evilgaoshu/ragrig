from __future__ import annotations

from pathlib import Path

from scripts.fileshare_check import build_payload


def test_fileshare_check_payload_exposes_plugin_and_offline_protocol_smoke() -> None:
    payload = build_payload(mounted_root=Path("tests/fixtures/local_ingestion"))

    assert payload["plugin"]["plugin_id"] == "source.fileshare"
    assert payload["plugin"]["supported_protocols"] == [
        "nfs_mounted",
        "sftp",
        "smb",
        "webdav",
    ]
    assert payload["mounted_path"]["exists"] is True
    assert "guide.md" in payload["fake_protocols"]["smb"]["discovered"]
    assert payload["fake_protocols"]["webdav"]["skipped"] == []
