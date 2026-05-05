from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

from ragrig.plugins.sources.fileshare.errors import (
    FileshareConfigError,
    FilesharePermanentError,
)


@dataclass(frozen=True)
class FileshareFileMetadata:
    path: str
    modified_at: datetime
    size: int
    content_type: str | None
    sample_bytes: bytes = b""
    owner: str | None = None
    group: str | None = None
    permissions: str | None = None


@dataclass(frozen=True)
class FileshareListResult:
    files: list[FileshareFileMetadata]
    next_cursor: str | None = None


@dataclass(frozen=True)
class FakeFileshareObject:
    path: str
    body: bytes
    modified_at: datetime
    content_type: str | None = None
    owner: str | None = None
    group: str | None = None
    permissions: str | None = None


class FileshareClientProtocol(Protocol):
    protocol: str

    def list_files(
        self,
        *,
        root_path: str,
        cursor: str | None,
        page_size: int,
    ) -> FileshareListResult: ...

    def read_file(self, *, path: str) -> bytes: ...


@dataclass
class FakeFileshareClient:
    protocol: str
    host: str | None = None
    share: str | None = None
    base_url: str | None = None
    objects: list[FakeFileshareObject] = field(default_factory=list)
    list_error: Exception | None = None
    read_failures: dict[str, list[Exception]] = field(default_factory=dict)

    def list_files(
        self,
        *,
        root_path: str,
        cursor: str | None,
        page_size: int,
    ) -> FileshareListResult:
        del root_path
        if self.list_error is not None:
            raise self.list_error
        filtered = sorted(self.objects, key=lambda item: item.path)
        if cursor is not None:
            filtered = [item for item in filtered if item.modified_at.isoformat() >= cursor]
        next_cursor = None
        if filtered:
            next_cursor = max(item.modified_at.isoformat() for item in filtered)
        return FileshareListResult(
            files=[
                FileshareFileMetadata(
                    path=item.path,
                    modified_at=item.modified_at,
                    size=len(item.body),
                    content_type=item.content_type,
                    sample_bytes=item.body[:8192],
                    owner=item.owner,
                    group=item.group,
                    permissions=item.permissions,
                )
                for item in filtered
            ],
            next_cursor=next_cursor,
        )

    def read_file(self, *, path: str) -> bytes:
        failures = self.read_failures.get(path, [])
        if failures:
            raise failures.pop(0)
        for item in self.objects:
            if item.path == path:
                return item.body
        raise FilesharePermanentError(f"file not found: {path}")


@dataclass
class MountedPathClient:
    root_path: Path
    protocol: str = "nfs_mounted"

    def list_files(
        self,
        *,
        root_path: str,
        cursor: str | None,
        page_size: int,
    ) -> FileshareListResult:
        del root_path, cursor, page_size
        if not self.root_path.exists() or not self.root_path.is_dir():
            raise FileshareConfigError(
                f"scan root does not exist or is not a directory: {self.root_path}"
            )
        files = []
        for path in sorted(self.root_path.rglob("*")):
            if not path.is_file():
                continue
            stat = path.stat()
            files.append(
                FileshareFileMetadata(
                    path=path.relative_to(self.root_path).as_posix(),
                    modified_at=datetime.fromtimestamp(stat.st_mtime),
                    size=stat.st_size,
                    content_type=None,
                    sample_bytes=path.read_bytes()[:8192],
                )
            )
        next_cursor = max((item.modified_at.isoformat() for item in files), default=None)
        return FileshareListResult(files=files, next_cursor=next_cursor)

    def read_file(self, *, path: str) -> bytes:
        return (self.root_path / path).read_bytes()
