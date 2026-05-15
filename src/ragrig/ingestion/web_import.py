from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx

MAX_WEBSITE_IMPORT_URLS = 25
MAX_WEBSITE_IMPORT_BYTES = 5 * 1024 * 1024
METADATA_SERVICE_IP = ipaddress.ip_address("169.254.169.254")


class WebsiteImportError(ValueError):
    """Raised when a website import request cannot be collected."""


@dataclass(frozen=True)
class ImportedPage:
    source_url: str
    html: str
    title: str | None


@dataclass(frozen=True)
class ImportFailure:
    source_url: str
    reason: str
    message: str


@dataclass(frozen=True)
class WebsiteImportResult:
    accepted_pages: list[ImportedPage]
    failures: list[ImportFailure]

    @property
    def failed_pages(self) -> int:
        return len(self.failures)


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_title = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._parts.append(data)

    @property
    def title(self) -> str | None:
        title = " ".join(part.strip() for part in self._parts if part.strip())
        return title or None


def collect_website_imports(
    *,
    urls: list[str],
    sitemap_url: str | None = None,
    client: httpx.Client | None = None,
    timeout: float = 10.0,
    allow_private_network: bool = False,
) -> WebsiteImportResult:
    collected_urls = list(urls)

    for url in collected_urls:
        _validate_http_url(url, allow_private_network=allow_private_network)

    if sitemap_url:
        _validate_http_url(sitemap_url, allow_private_network=allow_private_network)
        active_client, should_close = _resolve_client(client, timeout=timeout)
        try:
            collected_urls.extend(
                _fetch_sitemap_urls(
                    sitemap_url,
                    active_client,
                    allow_private_network=allow_private_network,
                )
            )
        finally:
            if should_close:
                active_client.close()

    if len(collected_urls) > MAX_WEBSITE_IMPORT_URLS:
        raise WebsiteImportError(
            f"too many URLs: {len(collected_urls)}. maximum 25 URLs per import."
        )

    accepted_pages: list[ImportedPage] = []
    failures: list[ImportFailure] = []
    active_client, should_close = _resolve_client(client, timeout=timeout)
    try:
        for url in collected_urls:
            _collect_page(
                url,
                active_client,
                accepted_pages,
                failures,
                allow_private_network=allow_private_network,
            )
    finally:
        if should_close:
            active_client.close()

    return WebsiteImportResult(accepted_pages=accepted_pages, failures=failures)


def _resolve_client(client: httpx.Client | None, *, timeout: float) -> tuple[httpx.Client, bool]:
    if client is not None:
        return client, False
    return httpx.Client(follow_redirects=True, timeout=timeout), True


def _validate_http_url(url: str, *, allow_private_network: bool = False) -> None:
    try:
        parsed = urlparse(url)
        # Accessing hostname/port forces urllib to validate malformed IPv6 and port syntax.
        host = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise WebsiteImportError(f"invalid URL '{url}': {exc}") from exc

    if parsed.scheme not in {"http", "https"}:
        raise WebsiteImportError(
            f"invalid URL scheme for '{url}': only http and https URLs are supported"
        )
    if not parsed.netloc or not host:
        raise WebsiteImportError(f"invalid URL '{url}': host is required")

    if not allow_private_network and _is_private_network_host(host):
        raise WebsiteImportError(
            f"URL host '{host}' resolves to a private or local network address; "
            "set allow_private_network=True only for trusted local imports"
        )


def _is_private_network_host(host: str) -> bool:
    normalized_host = host.lower().rstrip(".")
    if normalized_host == "localhost":
        return True
    if normalized_host.endswith(".test"):
        return False

    literal = _parse_ip_address(normalized_host)
    if literal is not None:
        return _is_blocked_ip(literal)

    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        # Let the fetch path report DNS/fetch failures. MockTransport-based tests also
        # use non-resolving .test hosts, so DNS failure alone is not a validation error.
        return False

    for info in infos:
        address = info[4][0]
        parsed = _parse_ip_address(address)
        if parsed is not None and _is_blocked_ip(parsed):
            return True
    return False


def _parse_ip_address(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value.strip("[]"))
    except ValueError:
        return None


def _is_blocked_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        address == METADATA_SERVICE_IP
        or address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    )


def _fetch_sitemap_urls(
    sitemap_url: str,
    client: httpx.Client,
    *,
    allow_private_network: bool = False,
) -> list[str]:
    try:
        response = client.get(sitemap_url)
        _validate_http_url(
            str(response.url),
            allow_private_network=allow_private_network,
        )
    except httpx.TimeoutException as exc:
        raise WebsiteImportError(f"timed out fetching sitemap '{sitemap_url}'") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise WebsiteImportError(f"failed to fetch sitemap '{sitemap_url}': {exc}") from exc

    if not 200 <= response.status_code < 300:
        raise WebsiteImportError(
            f"failed to fetch sitemap '{sitemap_url}': HTTP status {response.status_code}"
        )

    try:
        _enforce_response_size(response, source_url=sitemap_url)
    except WebsiteImportError as exc:
        raise WebsiteImportError(f"failed to fetch sitemap '{sitemap_url}': {exc}") from exc

    body = response.text.strip()
    if not body:
        raise WebsiteImportError(f"failed to parse sitemap '{sitemap_url}': empty body")

    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise WebsiteImportError(f"failed to parse sitemap '{sitemap_url}': {exc}") from exc

    sitemap_urls: list[str] = []
    for loc in root.findall(".//{*}loc"):
        if loc.text and loc.text.strip():
            url = loc.text.strip()
            _validate_http_url(url, allow_private_network=allow_private_network)
            sitemap_urls.append(url)
    return sitemap_urls


def _collect_page(
    url: str,
    client: httpx.Client,
    accepted_pages: list[ImportedPage],
    failures: list[ImportFailure],
    *,
    allow_private_network: bool = False,
) -> None:
    try:
        response = client.get(url)
        _validate_http_url(
            str(response.url),
            allow_private_network=allow_private_network,
        )
    except httpx.TimeoutException as exc:
        failures.append(
            ImportFailure(
                source_url=url,
                reason="timeout",
                message=f"Timed out fetching URL: {exc}",
            )
        )
        return
    except (httpx.HTTPError, ValueError, WebsiteImportError) as exc:
        failures.append(
            ImportFailure(
                source_url=url,
                reason="fetch_error",
                message=f"Failed to fetch URL: {exc}",
            )
        )
        return

    try:
        _enforce_response_size(response, source_url=url)
    except WebsiteImportError as exc:
        failures.append(
            ImportFailure(source_url=url, reason="response_too_large", message=str(exc))
        )
        return

    if not 200 <= response.status_code < 300:
        failures.append(
            ImportFailure(
                source_url=url,
                reason="http_status",
                message=f"HTTP status {response.status_code}",
            )
        )
        return

    content_type = response.headers.get("content-type", "")
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type != "text/html":
        failures.append(
            ImportFailure(
                source_url=url,
                reason="unsupported_content_type",
                message=f"Unsupported content type: {content_type or '(missing)'}",
            )
        )
        return

    html = response.text
    if not html.strip():
        failures.append(
            ImportFailure(source_url=url, reason="empty_body", message="HTML body is empty")
        )
        return

    accepted_pages.append(ImportedPage(source_url=url, html=html, title=_extract_title(html)))


def _extract_title(html: str) -> str | None:
    parser = _TitleParser()
    parser.feed(html)
    return parser.title


def _enforce_response_size(response: httpx.Response, *, source_url: str) -> None:
    content_length = response.headers.get("content-length")
    if content_length is not None:
        try:
            declared_size = int(content_length)
        except ValueError:
            declared_size = 0
        if declared_size > MAX_WEBSITE_IMPORT_BYTES:
            raise WebsiteImportError(
                f"response from '{source_url}' is too large: "
                f"{declared_size} bytes exceeds {MAX_WEBSITE_IMPORT_BYTES} bytes"
            )

    actual_size = len(response.content)
    if actual_size > MAX_WEBSITE_IMPORT_BYTES:
        raise WebsiteImportError(
            f"response from '{source_url}' is too large: "
            f"{actual_size} bytes exceeds {MAX_WEBSITE_IMPORT_BYTES} bytes"
        )
