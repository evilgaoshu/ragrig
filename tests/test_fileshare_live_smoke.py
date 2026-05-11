from __future__ import annotations

import os

import pytest

from ragrig.plugins.sources.fileshare.client import SFTPClient, SMBClient, WebDAVClient
from ragrig.plugins.sources.fileshare.scanner import scan_files

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("RAGRIG_FILESHARE_LIVE_SMOKE") != "1",
        reason="set RAGRIG_FILESHARE_LIVE_SMOKE=1 to run live fileshare smoke tests",
    ),
]

_WEBDAV_PORT = int(os.environ.get("WEBDAV_HOST_PORT", "8080"))
_SMB_PORT = int(os.environ.get("SMB_HOST_PORT", "1445"))
_SFTP_PORT = int(os.environ.get("SFTP_HOST_PORT", "2222"))


def _live_config(protocol: str, **overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "protocol": protocol,
        "root_path": "/",
        "include_patterns": ["*.md", "*.txt"],
        "exclude_patterns": [],
        "max_file_size_mb": 10,
        "page_size": 100,
        "max_retries": 1,
        "connect_timeout_seconds": 5,
        "read_timeout_seconds": 5,
        "cursor": None,
        "known_document_uris": [],
    }
    config.update(overrides)
    return config


def _try_import(import_name: str) -> bool:
    try:
        __import__(import_name)
        return True
    except ImportError:
        return False


class TestWebDAVLiveSmoke:
    @pytest.fixture
    def client(self):
        if not _try_import("httpx"):
            pytest.skip("httpx not installed")
        return WebDAVClient(
            base_url=f"http://localhost:{_WEBDAV_PORT}",
            username="testuser",
            password="testpass",
        )

    def test_list_files_returns_expected_entries(self, client: WebDAVClient) -> None:
        result = client.list_files(root_path="/", cursor=None, page_size=100)
        paths = [f.path for f in result.files]
        assert "guide.md" in paths
        assert "notes.txt" in paths
        assert "binary.bin" in paths

    def test_read_file_returns_expected_content(self, client: WebDAVClient) -> None:
        body = client.read_file(path="guide.md")
        assert b"# Guide" in body

    def test_scanner_applies_filters_and_skips(self, client: WebDAVClient) -> None:
        result = scan_files(
            client,
            config=_live_config("webdav", base_url=f"http://localhost:{_WEBDAV_PORT}"),
        )
        discovered_paths = [c.file_metadata.path for c in result.discovered]
        skipped_reasons = {s.file_metadata.path: s.reason for s in result.skipped}

        assert "guide.md" in discovered_paths
        assert "notes.txt" in discovered_paths
        assert skipped_reasons.get("binary.bin") == "unsupported_extension"


class TestSMBLiveSmoke:
    @pytest.fixture
    def client(self):
        if not _try_import("smbprotocol"):
            pytest.skip("smbprotocol not installed")
        return SMBClient(
            host="localhost",
            share="share",
            username="testuser",
            password="testpass",
            port=_SMB_PORT,
        )

    def test_list_files_returns_expected_entries(self, client: SMBClient) -> None:
        result = client.list_files(root_path="/", cursor=None, page_size=100)
        paths = [f.path for f in result.files]
        assert "guide.md" in paths
        assert "notes.txt" in paths

    def test_read_file_returns_expected_content(self, client: SMBClient) -> None:
        body = client.read_file(path="guide.md")
        assert b"# Guide" in body

    def test_scanner_applies_filters_and_skips(self, client: SMBClient) -> None:
        result = scan_files(
            client,
            config=_live_config(
                "smb",
                host="localhost",
                share="share",
                port=_SMB_PORT,
            ),
        )
        discovered_paths = [c.file_metadata.path for c in result.discovered]
        skipped_reasons = {s.file_metadata.path: s.reason for s in result.skipped}

        assert "guide.md" in discovered_paths
        assert "notes.txt" in discovered_paths
        assert skipped_reasons.get("binary.bin") == "unsupported_extension"


class TestSFTPLiveSmoke:
    @pytest.fixture
    def client(self):
        if not _try_import("paramiko"):
            pytest.skip("paramiko not installed")
        return SFTPClient(
            host="localhost",
            username="testuser",
            password="testpass",
            port=_SFTP_PORT,
        )

    def test_list_files_returns_expected_entries(self, client: SFTPClient) -> None:
        result = client.list_files(root_path="upload", cursor=None, page_size=100)
        paths = [f.path for f in result.files]
        assert "guide.md" in paths
        assert "notes.txt" in paths

    def test_read_file_returns_expected_content(self, client: SFTPClient) -> None:
        body = client.read_file(path="upload/guide.md")
        assert b"# Guide" in body

    def test_scanner_applies_filters_and_skips(self, client: SFTPClient) -> None:
        result = scan_files(
            client,
            config=_live_config(
                "sftp",
                host="localhost",
                port=_SFTP_PORT,
                root_path="upload",
            ),
        )
        discovered_paths = [c.file_metadata.path for c in result.discovered]
        skipped_reasons = {s.file_metadata.path: s.reason for s in result.skipped}

        assert "guide.md" in discovered_paths
        assert "notes.txt" in discovered_paths
        assert skipped_reasons.get("binary.bin") == "unsupported_extension"
