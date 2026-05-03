from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path

DEFAULT_INCLUDE_PATTERNS = ("*.md", "*.markdown", "*.txt", "*.text")
DEFAULT_EXCLUDE_DIRS = (".git", "__pycache__", ".venv", ".tox", "node_modules")


@dataclass(frozen=True)
class ScanCandidate:
    path: Path


@dataclass(frozen=True)
class ScanSkip:
    path: Path
    reason: str


@dataclass(frozen=True)
class ScanResult:
    discovered: list[ScanCandidate] = field(default_factory=list)
    skipped: list[ScanSkip] = field(default_factory=list)


def scan_paths(
    root_path: Path,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    max_file_size_bytes: int = 10 * 1024 * 1024,
) -> ScanResult:
    if not root_path.exists() or not root_path.is_dir():
        raise FileNotFoundError(f"scan root does not exist or is not a directory: {root_path}")

    includes = include_patterns or list(DEFAULT_INCLUDE_PATTERNS)
    excludes = exclude_patterns or []
    discovered: list[ScanCandidate] = []
    skipped: list[ScanSkip] = []

    for path in sorted(root_path.rglob("*")):
        relative = path.relative_to(root_path)
        relative_str = relative.as_posix()

        if path.is_dir():
            continue
        if any(part in DEFAULT_EXCLUDE_DIRS for part in relative.parts):
            continue
        if any(
            fnmatch(relative.name, pattern) or fnmatch(relative_str, pattern)
            for pattern in excludes
        ):
            skipped.append(ScanSkip(path=path, reason="excluded"))
            continue
        if not any(
            fnmatch(relative.name, pattern) or fnmatch(relative_str, pattern)
            for pattern in includes
        ):
            skipped.append(ScanSkip(path=path, reason="unsupported_extension"))
            continue
        if path.stat().st_size > max_file_size_bytes:
            skipped.append(ScanSkip(path=path, reason="file_too_large"))
            continue
        if b"\x00" in path.read_bytes()[:8192]:
            skipped.append(ScanSkip(path=path, reason="binary_file"))
            continue

        discovered.append(ScanCandidate(path=path))

    return ScanResult(discovered=discovered, skipped=skipped)
