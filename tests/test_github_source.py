"""Unit tests for the GitHub source connector."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
from unittest.mock import MagicMock, patch

import pytest

from ragrig.plugins.sources.github.config import GithubSourceConfig
from ragrig.plugins.sources.github.connector import (
    _build_headers,
    _fetch_file_content,
    _fetch_tree,
    _matches_patterns,
    _resolve_token,
    ingest_github_source,
)
from ragrig.plugins.sources.github.errors import (
    GithubAuthError,
    GithubConfigError,
    GithubSourceError,
)

pytestmark = pytest.mark.unit


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_tree_item(path: str, *, size: int = 100, item_type: str = "blob") -> dict[str, Any]:
    return {"path": path, "type": item_type, "size": size, "sha": "abc123"}


def _make_transport(responses: dict[str, tuple[int, dict[str, Any]]]):
    """Build a stub transport that matches by URL substring."""

    def transport(
        method: str,
        url: str,
        headers: Mapping[str, str],
        params: Mapping[str, object] | None,
    ) -> tuple[int, dict[str, Any]]:
        for key, (status, body) in responses.items():
            if key in url:
                return status, body
        return 404, {"message": f"no stub for {url}"}

    return transport


# ── Error hierarchy ───────────────────────────────────────────────────────────


def test_error_hierarchy() -> None:
    assert issubclass(GithubAuthError, GithubSourceError)
    assert issubclass(GithubConfigError, GithubSourceError)


# ── Config tests ──────────────────────────────────────────────────────────────


def test_config_from_dict_valid() -> None:
    cfg = GithubSourceConfig.from_dict(
        {
            "repo": "owner/myrepo",
            "token": "env:GITHUB_TOKEN",
            "branch": "develop",
            "path": "docs",
            "include_patterns": ["*.md"],
            "exclude_patterns": ["*.tmp"],
            "max_file_size_mb": 5.0,
            "page_size": 50,
        }
    )
    assert cfg.repo == "owner/myrepo"
    assert cfg.token == "env:GITHUB_TOKEN"
    assert cfg.branch == "develop"
    assert cfg.path == "docs"
    assert cfg.include_patterns == ["*.md"]
    assert cfg.exclude_patterns == ["*.tmp"]
    assert cfg.max_file_size_mb == 5.0
    assert cfg.page_size == 50


def test_config_defaults() -> None:
    cfg = GithubSourceConfig.from_dict({"repo": "owner/repo"})
    assert cfg.branch == "main"
    assert cfg.path == ""
    assert cfg.include_patterns == ["*.md", "*.txt", "*.rst", "*.py"]
    assert cfg.exclude_patterns == []
    assert cfg.max_file_size_mb == 10.0
    assert cfg.page_size == 100


def test_config_missing_repo_raises() -> None:
    with pytest.raises(GithubConfigError, match="repo is required"):
        GithubSourceConfig.from_dict({})


def test_config_invalid_repo_format_raises() -> None:
    with pytest.raises(GithubConfigError, match="owner/repo format"):
        GithubSourceConfig.from_dict({"repo": "justreponame"})


# ── Token resolution ──────────────────────────────────────────────────────────


def test_resolve_token_env_ref() -> None:
    assert _resolve_token("env:GITHUB_TOKEN", {"GITHUB_TOKEN": "ghp_abc"}) == "ghp_abc"


def test_resolve_token_missing_env_raises() -> None:
    with pytest.raises(GithubAuthError, match="GITHUB_TOKEN"):
        _resolve_token("env:GITHUB_TOKEN", {})


def test_resolve_token_literal_empty() -> None:
    assert _resolve_token("", {}) == ""


def test_resolve_token_literal_value() -> None:
    assert _resolve_token("ghp_literal", {}) == "ghp_literal"


# ── Header building ───────────────────────────────────────────────────────────


def test_build_headers_with_token() -> None:
    headers = _build_headers("ghp_abc123")
    assert headers["Authorization"] == "Bearer ghp_abc123"
    assert "application/vnd.github" in headers["Accept"]


def test_build_headers_without_token() -> None:
    headers = _build_headers("")
    assert "Authorization" not in headers


# ── Pattern matching ──────────────────────────────────────────────────────────


def test_matches_patterns_include_md() -> None:
    assert _matches_patterns("docs/readme.md", ["*.md"], []) is True


def test_matches_patterns_not_in_include() -> None:
    assert _matches_patterns("src/binary.exe", ["*.md", "*.txt"], []) is False


def test_matches_patterns_excluded() -> None:
    assert _matches_patterns("docs/readme.md", ["*.md"], ["readme.md"]) is False


def test_matches_patterns_full_path_glob() -> None:
    assert _matches_patterns("vendor/lib/util.py", ["*.py"], ["vendor/*"]) is False


# ── Tree fetching ─────────────────────────────────────────────────────────────


def test_fetch_tree_success() -> None:
    tree_body = {
        "tree": [
            _make_tree_item("README.md"),
            _make_tree_item("src/main.py"),
            _make_tree_item("src", item_type="tree"),
        ]
    }
    transport = _make_transport({"git/trees": (200, tree_body)})
    headers = _build_headers("token")
    items = _fetch_tree("owner", "repo", "main", headers=headers, transport=transport)
    assert len(items) == 3


def test_fetch_tree_auth_error() -> None:
    transport = _make_transport({"git/trees": (401, {"message": "Bad credentials"})})
    with pytest.raises(GithubAuthError, match="HTTP 401"):
        _fetch_tree("owner", "repo", "main", headers={}, transport=transport)


def test_fetch_tree_not_found() -> None:
    transport = _make_transport({"git/trees": (404, {"message": "Not Found"})})
    with pytest.raises(GithubConfigError, match="not found"):
        _fetch_tree("owner", "repo", "bad-branch", headers={}, transport=transport)


def test_fetch_tree_server_error() -> None:
    transport = _make_transport({"git/trees": (500, {"message": "Internal Server Error"})})
    with pytest.raises(GithubConfigError, match="GitHub API error"):
        _fetch_tree("owner", "repo", "main", headers={}, transport=transport)


# ── File content fetching ─────────────────────────────────────────────────────


def test_fetch_file_content_success() -> None:
    import base64

    encoded = base64.b64encode(b"hello world").decode()
    transport = _make_transport({"contents/": (200, {"content": encoded})})
    content = _fetch_file_content("owner", "repo", "README.md", headers={}, transport=transport)
    assert content == b"hello world"


def test_fetch_file_content_auth_error() -> None:
    transport = _make_transport({"contents/": (403, {"message": "Forbidden"})})
    with pytest.raises(GithubAuthError, match="HTTP 403"):
        _fetch_file_content("owner", "repo", "secret.txt", headers={}, transport=transport)


def test_fetch_file_content_not_found() -> None:
    transport = _make_transport({"contents/": (404, {"message": "Not Found"})})
    with pytest.raises(GithubConfigError, match="not found"):
        _fetch_file_content("owner", "repo", "missing.md", headers={}, transport=transport)


# ── Full ingest_github_source ─────────────────────────────────────────────────


def test_ingest_github_source_calls_pipeline(tmp_path) -> None:
    """ingest_github_source downloads files and calls ingest_local_directory."""
    import base64

    md_content = base64.b64encode(b"# Hello\n").decode()
    tree_body = {
        "tree": [
            {"path": "README.md", "type": "blob", "size": 100, "sha": "abc"},
        ]
    }
    contents_body = {"content": md_content}

    def transport(method, url, headers, params):
        if "git/trees" in url:
            return 200, tree_body
        if "contents/" in url:
            return 200, contents_body
        return 404, {}

    session = MagicMock()

    from ragrig.ingestion.pipeline import IngestionReport

    fake_report = IngestionReport(
        pipeline_run_id="test-run",
        created_documents=1,
        created_versions=1,
        skipped_count=0,
        failed_count=0,
    )

    with patch("ragrig.plugins.sources.github.connector.ingest_local_directory") as mock_ingest:
        mock_ingest.return_value = fake_report
        report = ingest_github_source(
            session,
            knowledge_base_name="test-kb",
            config={"repo": "owner/repo", "token": "ghp_fake"},
            transport=transport,
        )

    assert report is fake_report
    mock_ingest.assert_called_once()
    call_kwargs = mock_ingest.call_args.kwargs
    assert call_kwargs["knowledge_base_name"] == "test-kb"
    # Verify the temp directory was passed
    assert isinstance(call_kwargs["root_path"], Path)


def test_ingest_github_source_env_token(tmp_path) -> None:
    """Token is resolved from environment when using env:VAR."""
    import base64

    tree_body = {"tree": [{"path": "note.txt", "type": "blob", "size": 10, "sha": "abc"}]}
    contents_body = {"content": base64.b64encode(b"hi").decode()}

    def transport(method, url, headers, params):
        if "git/trees" in url:
            return 200, tree_body
        if "contents/" in url:
            return 200, contents_body
        return 404, {}

    session = MagicMock()

    from ragrig.ingestion.pipeline import IngestionReport

    fake_report = IngestionReport("r", 1, 1, 0, 0)

    with patch("ragrig.plugins.sources.github.connector.ingest_local_directory") as mock_ingest:
        mock_ingest.return_value = fake_report
        report = ingest_github_source(
            session,
            knowledge_base_name="kb",
            config={"repo": "owner/repo", "token": "env:MY_TOKEN"},
            env={"MY_TOKEN": "ghp_resolved"},
            transport=transport,
        )

    assert report is fake_report


def test_ingest_github_source_missing_env_token_raises() -> None:
    session = MagicMock()
    with pytest.raises(GithubAuthError, match="MY_TOKEN"):
        ingest_github_source(
            session,
            knowledge_base_name="kb",
            config={"repo": "owner/repo", "token": "env:MY_TOKEN"},
            env={},
            transport=lambda *a, **kw: (200, {}),
        )


def test_ingest_github_source_size_filter(tmp_path) -> None:
    """Files exceeding max_file_size_mb are excluded."""
    import base64

    tree_body = {
        "tree": [
            {"path": "big.md", "type": "blob", "size": 20 * 1024 * 1024, "sha": "abc"},
            {"path": "small.md", "type": "blob", "size": 100, "sha": "def"},
        ]
    }
    contents_body = {"content": base64.b64encode(b"small").decode()}
    downloaded: list[str] = []

    def transport(method, url, headers, params):
        if "git/trees" in url:
            return 200, tree_body
        if "contents/small.md" in url:
            downloaded.append("small.md")
            return 200, contents_body
        if "contents/big.md" in url:
            downloaded.append("big.md")
            return 200, {"content": base64.b64encode(b"x" * 100).decode()}
        return 404, {}

    session = MagicMock()

    from ragrig.ingestion.pipeline import IngestionReport

    fake_report = IngestionReport("r", 1, 1, 0, 0)

    with patch("ragrig.plugins.sources.github.connector.ingest_local_directory") as mock_ingest:
        mock_ingest.return_value = fake_report
        ingest_github_source(
            session,
            knowledge_base_name="kb",
            config={"repo": "owner/repo", "max_file_size_mb": 10.0},
            transport=transport,
        )

    # big.md should not be downloaded
    assert "big.md" not in downloaded
    assert "small.md" in downloaded


def test_ingest_github_source_path_filter(tmp_path) -> None:
    """Only files under the configured path prefix are ingested."""
    import base64

    tree_body = {
        "tree": [
            {"path": "docs/guide.md", "type": "blob", "size": 100, "sha": "a"},
            {"path": "src/main.py", "type": "blob", "size": 200, "sha": "b"},
        ]
    }
    contents_body = {"content": base64.b64encode(b"content").decode()}
    fetched: list[str] = []

    def transport(method, url, headers, params):
        if "git/trees" in url:
            return 200, tree_body
        if "contents/" in url:
            for p in ["docs/guide.md", "src/main.py"]:
                if p in url:
                    fetched.append(p)
            return 200, contents_body
        return 404, {}

    session = MagicMock()

    from ragrig.ingestion.pipeline import IngestionReport

    fake_report = IngestionReport("r", 1, 1, 0, 0)

    with patch("ragrig.plugins.sources.github.connector.ingest_local_directory") as mock_ingest:
        mock_ingest.return_value = fake_report
        ingest_github_source(
            session,
            knowledge_base_name="kb",
            config={
                "repo": "owner/repo",
                "path": "docs",
                "include_patterns": ["*.md", "*.py"],
            },
            transport=transport,
        )

    assert "docs/guide.md" in fetched
    assert "src/main.py" not in fetched
