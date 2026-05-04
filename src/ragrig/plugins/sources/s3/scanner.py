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


def scan_objects(client: S3ClientProtocol, *, config: dict[str, object]) -> S3ScanResult:
    includes = config.get("include_patterns") or list(DEFAULT_INCLUDE_PATTERNS)
    excludes = config.get("exclude_patterns") or []
    max_bytes = int(float(config["max_object_size_mb"]) * 1024 * 1024)
    continuation_token: str | None = None
    discovered: list[S3ScanCandidate] = []
    skipped: list[S3ScanSkip] = []

    while True:
        result = client.list_objects(
            bucket=str(config["bucket"]),
            prefix=str(config.get("prefix") or ""),
            continuation_token=continuation_token,
            max_keys=int(config["page_size"]),
        )
        for object_metadata in result.objects:
            key = object_metadata.key
            if any(fnmatch(key, pattern) for pattern in excludes):
                skipped.append(S3ScanSkip(object_metadata=object_metadata, reason="excluded"))
                continue
            if not any(
                fnmatch(key, pattern) or fnmatch(key.rsplit("/", 1)[-1], pattern)
                for pattern in includes
            ):
                skipped.append(
                    S3ScanSkip(object_metadata=object_metadata, reason="unsupported_extension")
                )
                continue
            if object_metadata.size > max_bytes:
                skipped.append(
                    S3ScanSkip(object_metadata=object_metadata, reason="object_too_large")
                )
                continue
            discovered.append(S3ScanCandidate(object_metadata=object_metadata))
        if result.next_token is None:
            break
        continuation_token = result.next_token

    return S3ScanResult(discovered=discovered, skipped=skipped)
