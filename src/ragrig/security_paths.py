from __future__ import annotations

from pathlib import Path
from typing import Iterable

from ragrig.config import Settings

DEFAULT_LOCAL_INGESTION_ROOTS = (Path("data"), Path("docs"), Path("uploads"))


class PathPolicyError(ValueError):
    pass


def split_path_roots(raw_roots: str) -> tuple[Path, ...]:
    return tuple(Path(value.strip()) for value in raw_roots.split(",") if value.strip())


def resolve_under_roots(
    path: str | Path,
    *,
    allowed_roots: Iterable[Path],
    label: str,
) -> Path:
    resolved = Path(path).resolve()
    roots = tuple(allowed_roots)
    for root in roots:
        root_resolved = root.resolve()
        if resolved == root_resolved or root_resolved in resolved.parents:
            return resolved
    allowed = ", ".join(str(root) for root in roots) or "(none configured)"
    raise PathPolicyError(f"{label} path must be under one of: {allowed}")


def local_ingestion_allowed_roots(settings: Settings) -> tuple[Path, ...]:
    return DEFAULT_LOCAL_INGESTION_ROOTS + split_path_roots(
        settings.ragrig_ingestion_extra_allowed_roots
    )


def resolve_local_ingestion_root(path: str | Path, *, settings: Settings) -> Path:
    return resolve_under_roots(
        path,
        allowed_roots=local_ingestion_allowed_roots(settings),
        label="local ingestion root",
    )
