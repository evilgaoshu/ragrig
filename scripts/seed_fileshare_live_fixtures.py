#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _container_name(service: str) -> str:
    result = subprocess.run(
        ["docker", "compose", "ps", "-q", service],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _copy_fixtures(service: str, container_path: str, fixture_dir: Path) -> None:
    container = _container_name(service)
    if not container:
        print(f"ERROR: {service} container is not running", file=sys.stderr)
        sys.exit(1)
    for path in fixture_dir.iterdir():
        dest = f"{container}:{container_path}/{path.name}"
        subprocess.run(
            ["docker", "cp", str(path), dest],
            check=True,
        )
        print(f"  seeded {path.name} -> {service}:{container_path}")


def main() -> int:
    repo_root = Path(__file__).parent.parent
    fixtures = repo_root / "tests" / "fixtures" / "fileshare_live"

    print("Seeding fileshare live test fixtures...")

    print("\n[samba]")
    _copy_fixtures("samba", "/mnt/share", fixtures / "samba")

    print("\n[webdav]")
    _copy_fixtures("webdav", "/var/lib/dav/data", fixtures / "webdav")

    print("\n[sftp]")
    _copy_fixtures("sftp", "/home/testuser/upload", fixtures / "sftp")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
