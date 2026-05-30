"""Unit tests for source.web scanner."""

from __future__ import annotations

import pytest

from ragrig.plugins.sources.web.scanner import (
    WebSourceAuthError,
    _build_auth,
    _build_auth_headers,
    _build_cookies,
    _extract_links,
    _extract_title,
    _html_to_text,
    _should_include,
    scan_web_pages,
)

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SIMPLE_HTML = """<html>
<head><title>Test Page</title></head>
<body>
  <h1>Hello World</h1>
  <p>Some content here.</p>
  <a href="/page2">Link</a>
  <a href="https://external.com/page">External</a>
</body>
</html>"""

SCRIPT_HTML = """<html><head></head><body>
  <script>var x = 1;</script>
  <style>.foo { color: red; }</style>
  <p>Actual content.</p>
</body></html>"""


def _mock_client(
    responses: dict[str, tuple[int, str, str]] | None = None,
) -> "MockClient":
    """Returns a mock httpx.Client that serves canned responses."""
    return MockClient(responses or {})


class MockResponse:
    def __init__(
        self,
        status_code: int,
        text: str,
        content_type: str = "text/html",
        url: str = "https://example.com/",
    ):
        self.status_code = status_code
        self.text = text
        self.headers = {"content-type": content_type}
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError(
                f"{self.status_code}",
                request=httpx.Request("GET", self.url),
                response=self,  # type: ignore[arg-type]
            )


class MockClient:
    def __init__(self, responses: dict[str, tuple[int, str, str]]):
        self._responses = responses
        self.requests: list[str] = []

    def get(self, url: str, **kwargs: object) -> MockResponse:
        self.requests.append(url)
        if url in self._responses:
            code, body, ct = self._responses[url]
            return MockResponse(code, body, ct, url)
        return MockResponse(200, SIMPLE_HTML, url=url)

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHtmlToText:
    def test_strips_tags(self) -> None:
        text = _html_to_text("<p>Hello <b>World</b></p>")
        assert "<" not in text
        assert "Hello" in text
        assert "World" in text

    def test_removes_scripts(self) -> None:
        text = _html_to_text(SCRIPT_HTML)
        assert "var x" not in text
        assert "color: red" not in text
        assert "Actual content" in text


class TestExtractTitle:
    def test_extracts_title(self) -> None:
        assert _extract_title("<title>My Page</title>") == "My Page"

    def test_returns_empty_when_no_title(self) -> None:
        assert _extract_title("<html><body>no title</body></html>") == ""


class TestExtractLinks:
    def test_extracts_same_origin_links(self) -> None:
        links = _extract_links(SIMPLE_HTML, "https://example.com/")
        assert "https://example.com/page2" in links

    def test_excludes_external_links(self) -> None:
        links = _extract_links(SIMPLE_HTML, "https://example.com/")
        assert not any("external.com" in link for link in links)

    def test_deduplicates_links(self) -> None:
        html = '<a href="/a">1</a><a href="/a">2</a>'
        links = _extract_links(html, "https://x.com")
        assert links.count("https://x.com/a") == 1


class TestShouldInclude:
    def test_no_filters_includes_all(self) -> None:
        assert _should_include("https://x.com/any", [], []) is True

    def test_exclude_pattern(self) -> None:
        assert _should_include("https://x.com/admin/page", [], ["/admin/*"]) is False

    def test_include_pattern(self) -> None:
        assert _should_include("https://x.com/docs/api", ["/docs/*"], []) is True
        assert _should_include("https://x.com/blog/post", ["/docs/*"], []) is False


class TestAuthBuilders:
    def test_bearer_token_plain(self) -> None:
        headers = _build_auth_headers({"bearer_token": "my-token"}, {})
        assert headers["Authorization"] == "Bearer my-token"

    def test_bearer_token_from_env(self) -> None:
        headers = _build_auth_headers({"bearer_token": "env:MY_TOKEN"}, {"MY_TOKEN": "secret"})
        assert headers["Authorization"] == "Bearer secret"

    def test_missing_env_var_raises(self) -> None:
        with pytest.raises(WebSourceAuthError, match="MY_TOKEN"):
            _build_auth_headers({"bearer_token": "env:MY_TOKEN"}, {})

    def test_custom_headers_included(self) -> None:
        headers = _build_auth_headers({"headers": {"X-Custom": "val"}}, {})
        assert headers["X-Custom"] == "val"

    def test_user_agent_default(self) -> None:
        headers = _build_auth_headers({}, {})
        assert "RAGRig" in headers["User-Agent"]

    def test_cookies_from_env(self) -> None:
        cookies = _build_cookies({"cookies": {"session": "env:SESSION"}}, {"SESSION": "abc123"})
        assert cookies["session"] == "abc123"

    def test_basic_auth_from_env(self) -> None:
        auth = _build_auth(
            {
                "basic_auth_username": "env:USER",
                "basic_auth_password": "env:PASS",
            },
            {"USER": "alice", "PASS": "secret"},
        )
        assert auth is not None

    def test_no_basic_auth_returns_none(self) -> None:
        assert _build_auth({}, {}) is None


# ---------------------------------------------------------------------------
# scan_web_pages integration
# ---------------------------------------------------------------------------


class TestScanWebPages:
    def test_empty_urls_returns_empty(self) -> None:
        result = scan_web_pages({"urls": []}, env={})
        assert result.fetched == []
        assert result.total_count == 0

    def test_fetches_single_page(self) -> None:
        client = _mock_client({"https://example.com/": (200, SIMPLE_HTML, "text/html")})
        result = scan_web_pages(
            {"urls": ["https://example.com/"], "allow_private_network": True},
            env={},
            _client=client,
        )
        assert len(result.fetched) == 1
        assert result.fetched[0].url == "https://example.com/"
        assert result.fetched[0].title == "Test Page"
        assert "Hello World" in result.fetched[0].text

    def test_skips_non_html_content_type(self) -> None:
        client = _mock_client(
            {"https://example.com/file.pdf": (200, b"%PDF".decode(), "application/pdf")}
        )
        result = scan_web_pages(
            {"urls": ["https://example.com/file.pdf"], "allow_private_network": True},
            env={},
            _client=client,
        )
        assert result.fetched == []
        assert len(result.skipped) == 1

    def test_blocks_private_network_url_by_default(self) -> None:
        client = _mock_client({"http://127.0.0.1/private": (200, SIMPLE_HTML, "text/html")})
        result = scan_web_pages({"urls": ["http://127.0.0.1/private"]}, env={}, _client=client)
        assert result.fetched == []
        assert result.failed
        assert result.failed[0][1].startswith("url_blocked:")
        assert client.requests == []

    def test_http_error_is_not_indexed(self) -> None:
        client = _mock_client({"https://example.com/missing": (404, SIMPLE_HTML, "text/html")})
        result = scan_web_pages(
            {"urls": ["https://example.com/missing"], "allow_private_network": True},
            env={},
            _client=client,
        )
        assert result.fetched == []
        assert result.failed == [("https://example.com/missing", "http_404")]

    def test_missing_env_secret_returns_failed(self) -> None:
        result = scan_web_pages({"urls": ["https://x.com"], "bearer_token": "env:MISSING"}, env={})
        assert len(result.failed) == 1

    def test_page_size_limits_fetch(self) -> None:
        client = _mock_client()
        result = scan_web_pages(
            {
                "urls": [
                    "https://example.com/1",
                    "https://example.com/2",
                    "https://example.com/3",
                ],
                "page_size": 2,
                "allow_private_network": True,
            },
            env={},
            _client=client,
        )
        assert len(result.fetched) == 2

    def test_depth_1_does_not_follow_links(self) -> None:
        client = _mock_client()
        result = scan_web_pages(
            {"urls": ["https://example.com/"], "max_depth": 1},
            env={},
            _client=client,
        )
        fetched_urls = {p.url for p in result.fetched}
        # depth=1 means do not follow links (links are at depth 2)
        assert "https://example.com/page2" not in fetched_urls

    def test_exclude_pattern_skips_url(self) -> None:
        client = _mock_client()
        result = scan_web_pages(
            {
                "urls": ["https://example.com/admin/secret"],
                "exclude_patterns": ["/admin/*"],
            },
            env={},
            _client=client,
        )
        assert result.fetched == []
        assert len(result.skipped) == 1
        assert result.skipped[0][1] == "excluded"

    def test_content_hash_populated(self) -> None:
        client = _mock_client()
        result = scan_web_pages(
            {"urls": ["https://example.com/"], "allow_private_network": True},
            env={},
            _client=client,
        )
        assert result.fetched[0].content_hash
        assert len(result.fetched[0].content_hash) == 64  # sha256 hex

    def test_next_cursor_set_when_more_pages(self) -> None:
        client = _mock_client()
        result = scan_web_pages(
            {
                "urls": [
                    "https://example.com/a",
                    "https://example.com/b",
                    "https://example.com/c",
                ],
                "page_size": 1,
                "allow_private_network": True,
            },
            env={},
            _client=client,
        )
        assert result.next_cursor is not None

    def test_no_cursor_when_all_fetched(self) -> None:
        client = _mock_client()
        result = scan_web_pages({"urls": ["https://example.com/only"]}, env={}, _client=client)
        assert result.next_cursor is None
