from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch

from ragrig.ingestion.scanner import DEFAULT_INCLUDE_PATTERNS
from ragrig.plugins.sources.s3.client import S3ClientProtocol, S3ObjectMetadata


@dataclass(frozen=True)
class S3ScanCandidate:
    object_metadata: S3ObjectMetadata


@dataclass(frozen=True)
class S3ScanSkip:
    object_metadata: S3ObjectMetadata
    reason: str


@dataclass(frozen=True)
class S3ScanResult:
    discovered: list[S3ScanCandidate] = field(default_factory=list)
    skipped: list[S3ScanSkip] = field(default_factory=list)


def scan_objects(
    *,
    client: S3ClientProtocol,
    bucket: str,
    prefix: str,
    include_patterns: list[str] | None,
    exclude_patterns: list[str] | None,
    max_object_size_bytes: int,
    page_size: int,
) -> S3ScanResult:
    includes = include_patterns or list(DEFAULT_INCLUDE_PATTERNS)
    excludes = exclude_patterns or []
    discovered: list[S3ScanCandidate] = []
    skipped: list[S3ScanSkip] = []
    continuation_token: str | None = None

    while True:
        page = client.list_objects(
            bucket=bucket,
            prefix=prefix,
            continuation_token=continuation_token,
            page_size=page_size,
        )
        for object_metadata in page.objects:
            if object_metadata.key.endswith("/"):
                continue
            if _matches(object_metadata.key, excludes):
                skipped.append(S3ScanSkip(object_metadata=object_metadata, reason="excluded"))
                continue
            if not _matches(object_metadata.key, includes):
                skipped.append(
                    S3ScanSkip(object_metadata=object_metadata, reason="unsupported_extension")
                )
                continue
            if object_metadata.size > max_object_size_bytes:
                skipped.append(
                    S3ScanSkip(object_metadata=object_metadata, reason="object_too_large")
                )
                continue
            discovered.append(S3ScanCandidate(object_metadata=object_metadata))
        if page.continuation_token is None:
            break
        continuation_token = page.continuation_token

    return S3ScanResult(discovered=discovered, skipped=skipped)


def _matches(key: str, patterns: list[str]) -> bool:
    file_name = key.rsplit("/", 1)[-1]
    return any(fnmatch(file_name, pattern) or fnmatch(key, pattern) for pattern in patterns)
