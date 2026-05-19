"""GitHub source connector.

Ingests files from a GitHub repository via the GitHub REST API. No git clone
is required — all content is fetched over HTTPS using ``httpx``.

Authentication uses a personal access token (PAT) supplied via an ``env:VAR``
reference. Unauthenticated requests are allowed but are rate-limited to
60 requests/hour.

The connector:
1. Resolves the branch to a recursive tree using the Git Trees API.
2. Filters blobs by include/exclude patterns and file-size limit.
3. Downloads each file's base64-encoded content via the Contents API.
4. Writes files to a temporary directory and calls ``ingest_local_directory``.
"""

from __future__ import annotations

import base64
import fnmatch
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

from sqlalchemy.orm import Session

from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.plugins.sources.github.config import GithubSourceConfig
from ragrig.plugins.sources.github.errors import GithubAuthError, GithubConfigError

# HTTP transport type: (method, url, headers, params) -> (status_code, json_body)
HttpTransport = Callable[
    [str, str, Mapping[str, str], Mapping[str, object] | None],
    tuple[int, dict[str, Any]],
]


def _resolve_token(token: str, env: Mapping[str, str]) -> str:
    """Resolve an env:VAR reference or return the value as-is (may be empty)."""
    if token.startswith("env:"):
        name = token.removeprefix("env:")
        resolved = env.get(name)
        if resolved is None:
            raise GithubAuthError(f"missing required environment variable: {name}")
        return resolved
    return token


def _default_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    params: Mapping[str, object] | None,
) -> tuple[int, dict[str, Any]]:  # pragma: no cover - real HTTP path
    import httpx

    resp = httpx.request(
        method.upper(),
        url,
        headers=dict(headers),
        params=dict(params) if params else None,
        timeout=30,
    )
    return resp.status_code, resp.json() if resp.content else {}


def _build_headers(token: str) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _matches_patterns(path: str, include: list[str], exclude: list[str]) -> bool:
    """Return True if path matches any include pattern and no exclude pattern."""
    filename = Path(path).name
    # Check include patterns (match against both full path and filename)
    included = any(fnmatch.fnmatch(filename, pat) or fnmatch.fnmatch(path, pat) for pat in include)
    if not included:
        return False
    # Check exclude patterns
    excluded = any(fnmatch.fnmatch(filename, pat) or fnmatch.fnmatch(path, pat) for pat in exclude)
    return not excluded


def _fetch_tree(
    owner: str,
    repo: str,
    branch: str,
    *,
    headers: dict[str, str],
    transport: HttpTransport,
) -> list[dict[str, Any]]:
    """Fetch the recursive git tree for a branch."""
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
    status, body = transport("GET", url, headers, None)
    if status in (401, 403):
        raise GithubAuthError(f"GitHub authentication failed: HTTP {status}")
    if status == 404:
        raise GithubConfigError(f"Repository or branch not found: {owner}/{repo}@{branch}")
    if status >= 400:
        raw_msg = body.get("message") if isinstance(body, dict) else None
        message = raw_msg or f"HTTP {status}"
        raise GithubConfigError(f"GitHub API error: {message}")
    tree = body.get("tree") or []
    return [item for item in tree if isinstance(item, dict)]


def _fetch_file_content(
    owner: str,
    repo: str,
    path: str,
    *,
    headers: dict[str, str],
    transport: HttpTransport,
) -> bytes:
    """Fetch a file's content from the GitHub Contents API (base64-decoded)."""
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
    status, body = transport("GET", url, headers, None)
    if status in (401, 403):
        raise GithubAuthError(f"GitHub authentication failed fetching {path}: HTTP {status}")
    if status == 404:
        raise GithubConfigError(f"File not found on GitHub: {path}")
    if status >= 400:
        raw_msg = body.get("message") if isinstance(body, dict) else None
        message = raw_msg or f"HTTP {status}"
        raise GithubConfigError(f"GitHub API error fetching {path}: {message}")
    encoded = str(body.get("content") or "").replace("\n", "")
    return base64.b64decode(encoded)


def ingest_github_source(
    session: Session,
    *,
    knowledge_base_name: str,
    config: dict[str, object] | GithubSourceConfig,
    env: Mapping[str, str] | None = None,
    transport: HttpTransport | None = None,
) -> object:
    """Ingest files from a GitHub repository into a knowledge base.

    Downloads all matching files to a temporary directory and runs them
    through the standard local-directory ingestion pipeline.

    Returns an ``IngestionReport``.
    """
    if isinstance(config, dict):
        cfg = GithubSourceConfig.from_dict(config)
    else:
        cfg = config

    _env = env if env is not None else os.environ
    token = _resolve_token(cfg.token, _env)
    fetch = transport or _default_transport
    headers = _build_headers(token)

    if "/" not in cfg.repo:
        raise GithubConfigError("repo must be in owner/repo format")
    owner, repo = cfg.repo.split("/", 1)

    tree_items = _fetch_tree(owner, repo, cfg.branch, headers=headers, transport=fetch)

    # Filter to blobs only
    max_size_bytes = int(cfg.max_file_size_mb * 1024 * 1024)
    candidates = []
    for item in tree_items:
        if item.get("type") != "blob":
            continue
        item_path = str(item.get("path") or "")
        # Filter by path prefix if configured
        path_prefix = cfg.path.rstrip("/") + "/"
        if cfg.path and not item_path.startswith(path_prefix) and item_path != cfg.path:
            continue
        # Filter by size
        item_size = int(item.get("size") or 0)
        if item_size > max_size_bytes:
            continue
        # Filter by include/exclude patterns
        if not _matches_patterns(item_path, cfg.include_patterns, cfg.exclude_patterns):
            continue
        candidates.append(item_path)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_root = Path(tmp_dir)
        for file_path in candidates:
            content = _fetch_file_content(owner, repo, file_path, headers=headers, transport=fetch)
            dest = tmp_root / file_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)

        report = ingest_local_directory(
            session,
            knowledge_base_name=knowledge_base_name,
            root_path=tmp_root,
        )

    return report
