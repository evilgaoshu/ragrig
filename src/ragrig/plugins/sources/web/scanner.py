"""Web source scanner: fetch pages via HTTP with flexible authentication.

Supported auth methods:
  - Cookies (dict of name→value)
  - Bearer token (Authorization: Bearer <token>)
  - Basic auth (username + password)
  - Custom headers (arbitrary key→value pairs)

All secret values may use the ``env:<VAR>`` convention so they are never
stored in plaintext config.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from ragrig.ingestion.web_import import WebsiteImportError, _validate_http_url


@dataclass(frozen=True)
class WebPage:
    url: str
    title: str
    text: str
    content_hash: str
    fetched_at: datetime
    status_code: int
    content_type: str
    links: list[str]


@dataclass(frozen=True)
class WebScanResult:
    fetched: list[WebPage] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    next_cursor: str | None = None
    total_count: int = 0


class WebSourceAuthError(RuntimeError):
    pass


def _resolve_secret(value: str, env: dict[str, str]) -> str:
    if value.startswith("env:"):
        key = value.removeprefix("env:")
        resolved = env.get(key)
        if resolved is None:
            raise WebSourceAuthError(f"Missing required env var: {key}")
        return resolved
    return value


def _build_auth_headers(config: dict[str, Any], env: dict[str, str]) -> dict[str, str]:
    headers: dict[str, str] = {}

    # Custom headers first (lowest precedence)
    for k, v in (config.get("headers") or {}).items():
        headers[k] = _resolve_secret(v, env) if isinstance(v, str) else v

    # Bearer token overrides Authorization header
    bearer = config.get("bearer_token")
    if bearer:
        headers["Authorization"] = f"Bearer {_resolve_secret(bearer, env)}"

    user_agent = config.get("user_agent", "RAGRig-WebSource/1.0")
    headers.setdefault("User-Agent", user_agent)
    return headers


def _build_cookies(config: dict[str, Any], env: dict[str, str]) -> dict[str, str]:
    raw = config.get("cookies") or {}
    return {k: _resolve_secret(v, env) if isinstance(v, str) else v for k, v in raw.items()}


def _build_auth(config: dict[str, Any], env: dict[str, str]) -> httpx.BasicAuth | None:
    username = config.get("basic_auth_username")
    password = config.get("basic_auth_password")
    if username and password:
        return httpx.BasicAuth(
            _resolve_secret(username, env),
            _resolve_secret(password, env),
        )
    return None


def _extract_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


def _html_to_text(html_content: str) -> str:
    # Remove <script> and <style> blocks
    text = re.sub(
        r"<(script|style)[^>]*>.*?</\1>", "", html_content, flags=re.DOTALL | re.IGNORECASE
    )
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_links(html_content: str, base_url: str) -> list[str]:
    hrefs = re.findall(r'<a[^>]+href=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
    links: list[str] = []
    base_parts = urlparse(base_url)
    for href in hrefs:
        href = href.strip()
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("javascript:"):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        # Only follow same-origin links
        if parsed.scheme in ("http", "https") and parsed.netloc == base_parts.netloc:
            links.append(absolute.split("#")[0])
    return list(dict.fromkeys(links))  # deduplicate, preserve order


def _should_include(url: str, includes: list[str], excludes: list[str]) -> bool:
    from fnmatch import fnmatch

    path = urlparse(url).path
    for pat in excludes:
        if fnmatch(path, pat) or fnmatch(url, pat):
            return False
    if not includes:
        return True
    return any(fnmatch(path, pat) or fnmatch(url, pat) for pat in includes)


def scan_web_pages(
    config: dict[str, Any],
    *,
    env: dict[str, str],
    cursor: str | None = None,
    _client: httpx.Client | None = None,
) -> WebScanResult:
    """Fetch web pages and extract their text content.

    Supports cookie-based auth, bearer tokens, basic auth, and custom headers.
    Pass ``_client`` in tests to inject a mock httpx.Client.
    """
    seed_urls: list[str] = list(config.get("urls") or [])
    if not seed_urls:
        return WebScanResult()

    max_depth = int(config.get("max_depth", 1))
    page_size = int(config.get("page_size", 20))
    timeout = float(config.get("timeout_seconds", 15.0))
    includes: list[str] = config.get("include_patterns") or []
    excludes: list[str] = config.get("exclude_patterns") or []
    verify_tls = bool(config.get("verify_tls", True))
    allow_private_network = bool(config.get("allow_private_network", False))

    try:
        auth_headers = _build_auth_headers(config, env)
        cookies = _build_cookies(config, env)
        basic_auth = _build_auth(config, env)
    except WebSourceAuthError as exc:
        return WebScanResult(failed=[(url, str(exc)) for url in seed_urls])

    # Determine which URLs to visit this page
    if cursor:
        try:
            import json as _json

            state = _json.loads(cursor)
            queue: list[tuple[str, int]] = [(u, d) for u, d in state.get("queue", [])]
            visited: set[str] = set(state.get("visited", []))
        except Exception:
            queue = [(u, 1) for u in seed_urls]
            visited = set()
    else:
        # Seeds start at depth=1; max_depth=1 means seeds only (no link following).
        queue = [(u, 1) for u in seed_urls]
        visited = set()

    fetched: list[WebPage] = []
    skipped: list[tuple[str, str]] = []
    failed: list[tuple[str, str]] = []

    own_client = _client is None
    client = _client or httpx.Client(
        headers=auth_headers,
        cookies=cookies,
        auth=basic_auth,
        timeout=timeout,
        follow_redirects=True,
        verify=verify_tls,
    )

    try:
        while queue and len(fetched) < page_size:
            url, depth = queue.pop(0)
            if url in visited:
                skipped.append((url, "already_visited"))
                continue
            visited.add(url)

            if not _should_include(url, includes, excludes):
                skipped.append((url, "excluded"))
                continue

            try:
                _validate_http_url(url, allow_private_network=allow_private_network)
                resp = client.get(url)
                _validate_http_url(str(resp.url), allow_private_network=allow_private_network)
                resp.raise_for_status()
                ct = resp.headers.get("content-type", "")
                if "text/html" not in ct and "text/plain" not in ct:
                    skipped.append((url, f"unsupported_content_type:{ct}"))
                    continue

                html_content = resp.text
                title = _extract_title(html_content)
                text = _html_to_text(html_content)
                content_hash = hashlib.sha256(text.encode()).hexdigest()

                links: list[str] = []
                if depth < max_depth and "text/html" in ct:
                    links = _extract_links(html_content, url)
                    for link in links:
                        try:
                            _validate_http_url(
                                link,
                                allow_private_network=allow_private_network,
                            )
                        except WebsiteImportError:
                            skipped.append((link, "blocked_private_or_invalid_url"))
                            continue
                        if link not in visited:
                            queue.append((link, depth + 1))

                fetched.append(
                    WebPage(
                        url=url,
                        title=title,
                        text=text,
                        content_hash=content_hash,
                        fetched_at=datetime.now(timezone.utc),
                        status_code=resp.status_code,
                        content_type=ct,
                        links=links,
                    )
                )
            except httpx.HTTPStatusError as exc:
                failed.append((url, f"http_{exc.response.status_code}"))
            except WebsiteImportError as exc:
                failed.append((url, f"url_blocked:{exc}"))
            except httpx.RequestError as exc:
                failed.append((url, f"request_error:{type(exc).__name__}"))
    finally:
        if own_client:
            client.close()

    # Build next cursor if queue is non-empty
    next_cursor: str | None = None
    if queue:
        import json as _json

        next_cursor = _json.dumps({"queue": queue, "visited": list(visited)})

    return WebScanResult(
        fetched=fetched,
        skipped=skipped,
        failed=failed,
        next_cursor=next_cursor,
        total_count=len(fetched) + len(skipped) + len(failed),
    )
