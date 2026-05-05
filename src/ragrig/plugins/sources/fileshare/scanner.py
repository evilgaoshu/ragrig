from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch

from ragrig.ingestion.scanner import DEFAULT_INCLUDE_PATTERNS
from ragrig.plugins.sources.fileshare.client import FileshareClientProtocol, FileshareFileMetadata


@dataclass(frozen=True)
class FileshareScanCandidate:
    file_metadata: FileshareFileMetadata


@dataclass(frozen=True)
class FileshareScanSkip:
    file_metadata: FileshareFileMetadata
    reason: str


@dataclass(frozen=True)
class FileshareDeletePlaceholder:
    uri: str


@dataclass(frozen=True)
class FileshareScanResult:
    discovered: list[FileshareScanCandidate] = field(default_factory=list)
    skipped: list[FileshareScanSkip] = field(default_factory=list)
    deleted: list[FileshareDeletePlaceholder] = field(default_factory=list)
    next_cursor: str | None = None


def scan_files(
    client: FileshareClientProtocol, *, config: dict[str, object]
) -> FileshareScanResult:
    includes = config.get("include_patterns") or list(DEFAULT_INCLUDE_PATTERNS)
    excludes = config.get("exclude_patterns") or []
    max_bytes = int(float(config["max_file_size_mb"]) * 1024 * 1024)
    listed = client.list_files(
        root_path=str(config["root_path"]),
        cursor=str(config.get("cursor") or "") or None,
        page_size=int(config["page_size"]),
    )
    discovered: list[FileshareScanCandidate] = []
    skipped: list[FileshareScanSkip] = []
    seen_uris: set[str] = set()

    for file_metadata in listed.files:
        path = file_metadata.path
        basename = path.rsplit("/", 1)[-1]
        normalized_path = _normalize_remote_path(str(config["root_path"]), path)
        seen_uris.add(_document_uri(config, normalized_path))
        if any(fnmatch(path, pattern) or fnmatch(basename, pattern) for pattern in excludes):
            skipped.append(FileshareScanSkip(file_metadata=file_metadata, reason="excluded"))
            continue
        if not any(fnmatch(path, pattern) or fnmatch(basename, pattern) for pattern in includes):
            skipped.append(
                FileshareScanSkip(file_metadata=file_metadata, reason="unsupported_extension")
            )
            continue
        if file_metadata.size > max_bytes:
            skipped.append(FileshareScanSkip(file_metadata=file_metadata, reason="file_too_large"))
            continue
        if b"\x00" in file_metadata.sample_bytes:
            skipped.append(FileshareScanSkip(file_metadata=file_metadata, reason="binary_file"))
            continue
        discovered.append(FileshareScanCandidate(file_metadata=file_metadata))

    known_document_uris = {str(item) for item in config.get("known_document_uris") or []}
    deleted = [
        FileshareDeletePlaceholder(uri=uri) for uri in sorted(known_document_uris - seen_uris)
    ]
    return FileshareScanResult(
        discovered=discovered,
        skipped=skipped,
        deleted=deleted,
        next_cursor=listed.next_cursor,
    )


def _document_uri(config: dict[str, object], path: str) -> str:
    protocol = str(config["protocol"])
    root_path = str(config["root_path"]).strip("/")
    if protocol == "webdav":
        base_url = str(config["base_url"] or "").rstrip("/")
        prefix = f"{base_url}/{root_path}".rstrip("/")
        return f"webdav://{prefix.removeprefix('https://').removeprefix('http://')}/{path}"
    if protocol == "nfs_mounted":
        return f"nfs://mounted/{root_path}/{path}".replace("//", "/").replace("nfs:/", "nfs://")
    host = str(config.get("host") or "")
    share = str(config.get("share") or "").strip("/")
    prefix = f"{protocol}://{host}/{share}"
    if root_path:
        prefix = f"{prefix}/{root_path}"
    return f"{prefix}/{path}"


def _normalize_remote_path(root_path: str, path: str) -> str:
    normalized_root = root_path.strip("/")
    normalized_path = path.strip("/")
    if normalized_root and normalized_path.startswith(f"{normalized_root}/"):
        return normalized_path.removeprefix(f"{normalized_root}/")
    return normalized_path
