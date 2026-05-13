from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ragrig.plugins.sources.google_workspace.errors import (
    GoogleWorkspaceConfigError,
    GoogleWorkspaceCredentialError,
)


@dataclass(frozen=True)
class GoogleDriveItem:
    item_id: str
    name: str
    mime_type: str
    modified_at: datetime
    etag: str
    version: str | None
    parent_path: str
    web_view_link: str | None
    size_bytes: int | None


@dataclass(frozen=True)
class GoogleWorkspaceScanResult:
    discovered: list[GoogleDriveItem] = field(default_factory=list)
    skipped: list[tuple[GoogleDriveItem, str]] = field(default_factory=list)
    next_cursor: str | None = None
    total_count: int = 0


def _resolve_credential(config: dict[str, Any], env: dict[str, str]) -> str:
    value = config.get("service_account_json")
    if not isinstance(value, str) or not value.startswith("env:"):
        raise GoogleWorkspaceConfigError("service_account_json must use env: reference")
    env_name = value.removeprefix("env:")
    resolved = env.get(env_name)
    if resolved is None:
        raise GoogleWorkspaceCredentialError(f"missing required secret env: {env_name}")
    try:
        parsed = json.loads(resolved)
    except json.JSONDecodeError as exc:
        raise GoogleWorkspaceCredentialError(f"invalid JSON in service account: {exc}") from exc
    if not isinstance(parsed, dict):
        raise GoogleWorkspaceCredentialError("service account JSON must be an object")
    return resolved


def scan_drive_items(
    config: dict[str, Any],
    *,
    env: dict[str, str],
    cursor: str | None = None,
) -> GoogleWorkspaceScanResult:
    try:
        _resolve_credential(config, env)
    except GoogleWorkspaceCredentialError:
        return GoogleWorkspaceScanResult(
            discovered=[],
            skipped=[],
            next_cursor=None,
            total_count=0,
        )

    # Dry-run fixture generation
    items = _generate_fixture_items(cursor)
    next_cursor = _generate_next_cursor(items, int(config.get("page_size", 100)))

    discovered: list[GoogleDriveItem] = []
    skipped: list[tuple[GoogleDriveItem, str]] = []

    includes = config.get("include_patterns") or ["*.pdf", "*.txt", "*.docx"]
    excludes = config.get("exclude_patterns") or []

    from fnmatch import fnmatch

    for item in items:
        if any(fnmatch(item.name, pattern) for pattern in excludes):
            skipped.append((item, "excluded"))
            continue
        if not any(
            fnmatch(item.name, pattern) or fnmatch(item.name.rsplit("/", 1)[-1], pattern)
            for pattern in includes
        ):
            skipped.append((item, "unsupported_extension"))
            continue
        discovered.append(item)

    return GoogleWorkspaceScanResult(
        discovered=discovered,
        skipped=skipped,
        next_cursor=next_cursor,
        total_count=len(items),
    )


def _generate_fixture_items(cursor: str | None) -> list[GoogleDriveItem]:
    ts = datetime(2026, 5, 13, 10, 0, 0, tzinfo=timezone.utc)

    drive_file = GoogleDriveItem(
        item_id="drive-001",
        name="Project Proposal.pdf",
        mime_type="application/pdf",
        modified_at=ts,
        etag='"abc123def456"',
        version="1",
        parent_path="/My Drive/Projects",
        web_view_link="https://drive.google.com/file/d/drive-001/view",
        size_bytes=102400,
    )

    docs_document = GoogleDriveItem(
        item_id="docs-001",
        name="Meeting Notes.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        modified_at=ts,
        etag='"xyz789uvw012"',
        version="3",
        parent_path="/My Drive/Notes",
        web_view_link="https://docs.google.com/document/d/docs-001/edit",
        size_bytes=51200,
    )

    items = [drive_file, docs_document]

    if cursor == "page2":
        return []
    if cursor == "page1":
        return items[1:]
    return items


def _generate_next_cursor(items: list[GoogleDriveItem], page_size: int) -> str | None:
    if len(items) >= page_size:
        return "page1"
    return None


def deduplicate_items(items: list[GoogleDriveItem]) -> list[GoogleDriveItem]:
    seen: set[str] = set()
    result: list[GoogleDriveItem] = []
    for item in items:
        if item.item_id not in seen:
            seen.add(item.item_id)
            result.append(item)
    return result
