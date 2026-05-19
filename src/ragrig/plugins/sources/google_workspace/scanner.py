from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
from typing import Any

from ragrig.plugins.sources.google_workspace.errors import (
    GoogleWorkspaceConfigError,
    GoogleWorkspaceCredentialError,
)

try:
    from google.oauth2.service_account import Credentials as _SACredentials
    from googleapiclient.discovery import build as _build_service

    _GOOGLE_AVAILABLE = True
except ImportError:
    _GOOGLE_AVAILABLE = False

_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


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


def _build_drive_service(cred_json: str) -> Any:
    creds = _SACredentials.from_service_account_info(
        json.loads(cred_json), scopes=_DRIVE_SCOPES
    )
    return _build_service("drive", "v3", credentials=creds, cache_discovery=False)


def _resolve_parent_names(service: Any, parent_ids: set[str]) -> dict[str, str]:
    names: dict[str, str] = {}
    for pid in parent_ids:
        try:
            result = service.files().get(fileId=pid, fields="name").execute()
            names[pid] = result.get("name", pid)
        except Exception:
            names[pid] = pid
    return names


def _parse_item(raw: dict[str, Any], parent_names: dict[str, str]) -> GoogleDriveItem:
    parents = raw.get("parents") or []
    if parents:
        parent_label = parent_names.get(parents[0], parents[0])
        parent_path = "/" + parent_label
    else:
        parent_path = "/"

    try:
        modified_at = datetime.fromisoformat(raw["modifiedTime"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        modified_at = datetime.now(timezone.utc)

    size_raw = raw.get("size")
    return GoogleDriveItem(
        item_id=raw["id"],
        name=raw.get("name", ""),
        mime_type=raw.get("mimeType", ""),
        modified_at=modified_at,
        etag=raw.get("etag", ""),
        version=raw.get("version"),
        parent_path=parent_path,
        web_view_link=raw.get("webViewLink"),
        size_bytes=int(size_raw) if size_raw else None,
    )


def scan_drive_items(
    config: dict[str, Any],
    *,
    env: dict[str, str],
    cursor: str | None = None,
    _service: Any = None,
) -> GoogleWorkspaceScanResult:
    """List files from Google Drive using the Drive v3 API.

    Pass ``_service`` in tests to inject a mock Drive service object.
    """
    if not _GOOGLE_AVAILABLE and _service is None:
        return GoogleWorkspaceScanResult()

    try:
        cred_json = _resolve_credential(config, env)
    except (GoogleWorkspaceConfigError, GoogleWorkspaceCredentialError):
        return GoogleWorkspaceScanResult()

    service = _service if _service is not None else _build_drive_service(cred_json)

    page_size = min(int(config.get("page_size", 100)), 1000)
    folder_id = config.get("folder_id")

    q_parts = ["trashed = false"]
    if folder_id:
        q_parts.append(f"'{folder_id}' in parents")

    list_kwargs: dict[str, Any] = dict(
        pageSize=page_size,
        fields=(
            "nextPageToken,"
            "files(id,name,mimeType,modifiedTime,etag,version,parents,webViewLink,size)"
        ),
        q=" and ".join(q_parts),
    )
    if cursor:
        list_kwargs["pageToken"] = cursor

    resp = service.files().list(**list_kwargs).execute()
    raw_files: list[dict[str, Any]] = resp.get("files", [])
    next_page_token: str | None = resp.get("nextPageToken")

    # Resolve parent folder names in one pass
    parent_ids: set[str] = set()
    for f in raw_files:
        parent_ids.update(f.get("parents") or [])
    parent_names = _resolve_parent_names(service, parent_ids)

    includes: list[str] = config.get("include_patterns") or ["*.pdf", "*.txt", "*.docx"]
    excludes: list[str] = config.get("exclude_patterns") or []

    discovered: list[GoogleDriveItem] = []
    skipped: list[tuple[GoogleDriveItem, str]] = []

    for raw in raw_files:
        item = _parse_item(raw, parent_names)
        if any(fnmatch(item.name, pat) for pat in excludes):
            skipped.append((item, "excluded"))
            continue
        if not any(fnmatch(item.name, pat) for pat in includes):
            skipped.append((item, "unsupported_extension"))
            continue
        discovered.append(item)

    return GoogleWorkspaceScanResult(
        discovered=discovered,
        skipped=skipped,
        next_cursor=next_page_token,
        total_count=len(raw_files),
    )


def deduplicate_items(items: list[GoogleDriveItem]) -> list[GoogleDriveItem]:
    seen: set[str] = set()
    result: list[GoogleDriveItem] = []
    for item in items:
        if item.item_id not in seen:
            seen.add(item.item_id)
            result.append(item)
    return result
