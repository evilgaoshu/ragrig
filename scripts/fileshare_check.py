from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from ragrig.plugins import get_plugin_registry
from ragrig.plugins.sources.fileshare.client import FakeFileshareClient, FakeFileshareObject
from ragrig.plugins.sources.fileshare.scanner import scan_files

_FIXTURE_TIME = datetime(2026, 5, 5, tzinfo=timezone.utc)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an offline fileshare plugin smoke check.")
    parser.add_argument(
        "--mounted-root",
        default="tests/fixtures/local_ingestion",
        help="Mounted local/NFS path to validate in dry-run mode.",
    )
    return parser


def build_payload(*, mounted_root: Path) -> dict[str, object]:
    registry_item = next(
        item
        for item in get_plugin_registry().list_discovery()
        if item["plugin_id"] == "source.fileshare"
    )
    fake_results = {}
    for protocol in ("smb", "webdav", "sftp"):
        result = scan_files(
            FakeFileshareClient(
                protocol=protocol,
                host="files.example.internal",
                share="knowledge",
                base_url="https://files.example.internal/webdav",
                objects=[
                    FakeFileshareObject(
                        path="guide.md",
                        body=b"# Guide\n",
                        modified_at=_FIXTURE_TIME,
                        content_type="text/markdown",
                        owner="alice",
                        group="engineering",
                        permissions="rw-r-----",
                    )
                ],
            ),
            config={
                "protocol": protocol,
                "host": "files.example.internal",
                "share": "knowledge",
                "base_url": "https://files.example.internal/webdav",
                "root_path": "/docs",
                "include_patterns": ["*.md", "*.txt"],
                "exclude_patterns": [],
                "max_file_size_mb": 10,
                "page_size": 100,
                "max_retries": 1,
                "connect_timeout_seconds": 5,
                "read_timeout_seconds": 5,
                "cursor": None,
                "known_document_uris": [],
            },
        )
        fake_results[protocol] = {
            "discovered": [item.file_metadata.path for item in result.discovered],
            "skipped": [item.reason for item in result.skipped],
        }
    mounted_files = sorted(
        path.relative_to(mounted_root).as_posix()
        for path in mounted_root.rglob("*")
        if path.is_file()
    )
    return {
        "plugin": registry_item,
        "mounted_path": {
            "root": str(mounted_root),
            "exists": mounted_root.exists(),
            "files": mounted_files,
        },
        "fake_protocols": fake_results,
    }


def main() -> int:
    args = build_parser().parse_args()
    payload = build_payload(mounted_root=Path(args.mounted_root))
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
