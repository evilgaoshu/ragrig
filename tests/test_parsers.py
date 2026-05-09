from __future__ import annotations

from hashlib import sha256

import pytest

from ragrig.parsers.base import ParserTimeoutError, parse_with_timeout
from ragrig.parsers.csv import CsvParser
from ragrig.parsers.html import HtmlParser
from ragrig.parsers.markdown import MarkdownParser
from ragrig.parsers.plaintext import PlainTextParser
from ragrig.parsers.sanitizer import sanitize_text_summary

pytestmark = pytest.mark.unit


def test_markdown_parser_returns_expected_content_hash_and_metadata(tmp_path) -> None:
    path = tmp_path / "guide.md"
    raw_text = "# Hello\n\nThis is markdown.\n"
    path.write_text(raw_text, encoding="utf-8")

    result = MarkdownParser().parse(path)

    assert result.extracted_text == raw_text
    assert result.content_hash == sha256(raw_text.encode("utf-8")).hexdigest()
    assert result.mime_type == "text/markdown"
    assert result.parser_name == "markdown"
    assert result.metadata["extension"] == ".md"
    assert result.metadata["line_count"] == 3
    assert result.metadata["char_count"] == len(raw_text)
    assert result.metadata["encoding"] == "utf-8"
    assert result.metadata["parser_id"] == "parser.markdown"
    assert result.metadata["status"] == "success"
    assert result.metadata["byte_count"] > 0
    assert "text_summary" in result.metadata
    # text_summary must not exceed 81 chars (80 + optional ellipsis)
    assert len(result.metadata["text_summary"]) <= 81


def test_plaintext_parser_returns_expected_content_hash_and_metadata(tmp_path) -> None:
    path = tmp_path / "notes.txt"
    raw_text = "plain text\nsecond line\n"
    path.write_text(raw_text, encoding="utf-8")

    result = PlainTextParser().parse(path)

    assert result.extracted_text == raw_text
    assert result.content_hash == sha256(raw_text.encode("utf-8")).hexdigest()
    assert result.mime_type == "text/plain"
    assert result.parser_name == "plaintext"
    assert result.metadata["extension"] == ".txt"
    assert result.metadata["line_count"] == 2
    assert result.metadata["char_count"] == len(raw_text)
    assert result.metadata["encoding"] == "utf-8"
    assert result.metadata["parser_id"] == "parser.text"
    assert result.metadata["status"] == "success"
    assert result.metadata["byte_count"] > 0
    assert "text_summary" in result.metadata


def test_plaintext_parser_counts_single_line_without_trailing_newline(tmp_path) -> None:
    path = tmp_path / "single.txt"
    path.write_text("single line", encoding="utf-8")

    result = PlainTextParser().parse(path)

    assert result.metadata["line_count"] == 1


def test_csv_parser_extracts_text_and_metadata(tmp_path) -> None:
    path = tmp_path / "data.csv"
    raw_text = "col1,col2\na,b\nc,d\n"
    path.write_text(raw_text, encoding="utf-8")

    result = CsvParser().parse(path)

    assert result.extracted_text == raw_text
    assert result.mime_type == "text/csv"
    assert result.parser_name == "csv"
    assert result.metadata["extension"] == ".csv"
    assert result.metadata["line_count"] == 3
    assert result.metadata["row_count"] == 3
    assert result.metadata["col_count"] == 2
    assert "degraded_reason" in result.metadata
    assert result.metadata["parser_id"] == "parser.csv"
    assert result.metadata["status"] == "degraded"
    assert result.metadata["byte_count"] > 0
    assert "text_summary" in result.metadata


def test_csv_parser_gracefully_handles_malformed_csv(tmp_path) -> None:
    path = tmp_path / "bad.csv"
    raw_text = 'a,b\n"unclosed'
    path.write_text(raw_text, encoding="utf-8")

    result = CsvParser().parse(path)

    assert result.extracted_text == raw_text
    assert result.parser_name == "csv"
    # Should not raise; row_count may be 0 or best-effort
    assert "row_count" in result.metadata


def test_csv_parser_handles_empty_file(tmp_path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")

    result = CsvParser().parse(path)

    assert result.extracted_text == ""
    assert result.metadata["line_count"] == 0
    assert result.metadata["row_count"] == 0
    assert result.metadata["col_count"] == 0


def test_html_parser_handles_empty_file(tmp_path) -> None:
    path = tmp_path / "empty.html"
    path.write_text("", encoding="utf-8")

    result = HtmlParser().parse(path)

    assert result.extracted_text == ""
    assert result.metadata["line_count"] == 0
    assert result.metadata["stripped_char_count"] == 0


def test_csv_parser_gracefully_handles_reader_exception(tmp_path, monkeypatch) -> None:
    path = tmp_path / "data.csv"
    path.write_text("a,b", encoding="utf-8")

    def _broken_reader(*args, **kwargs):
        raise RuntimeError("simulated csv failure")

    monkeypatch.setattr("ragrig.parsers.csv.csv.reader", _broken_reader)

    result = CsvParser().parse(path)

    assert result.extracted_text == "a,b"
    assert result.metadata["row_count"] == 0
    assert result.metadata["col_count"] == 0


def test_html_parser_strips_tags_and_returns_metadata(tmp_path) -> None:
    path = tmp_path / "page.html"
    raw_text = "<html><body><h1>Title</h1> <p>Hello world</p></body></html>"
    path.write_text(raw_text, encoding="utf-8")

    result = HtmlParser().parse(path)

    assert result.extracted_text == "Title Hello world"
    assert result.mime_type == "text/html"
    assert result.parser_name == "html"
    assert result.metadata["extension"] == ".html"
    assert result.metadata["stripped_char_count"] == 17
    assert "degraded_reason" in result.metadata
    assert result.metadata["parser_id"] == "parser.html"
    assert result.metadata["status"] == "degraded"
    assert result.metadata["byte_count"] > 0
    assert "text_summary" in result.metadata


def test_parse_with_timeout_returns_result_for_fast_parser(tmp_path) -> None:
    path = tmp_path / "fast.txt"
    path.write_text("hello", encoding="utf-8")

    result = parse_with_timeout(PlainTextParser(), path, timeout_seconds=5.0)

    assert result.extracted_text == "hello"
    assert result.parser_name == "plaintext"


def test_parse_with_timeout_raises_on_slow_parser(tmp_path) -> None:
    path = tmp_path / "slow.txt"
    path.write_text("hello", encoding="utf-8")

    class SlowParser(PlainTextParser):
        parser_name = "slow"

        def parse(self, path):
            import time

            time.sleep(2)
            return super().parse(path)

    with pytest.raises(ParserTimeoutError, match="timed out"):
        parse_with_timeout(SlowParser(), path, timeout_seconds=0.1)


# ── Fixture Corpus Tests: CSV ──


def test_csv_parser_empty_file_metadata_is_stable(tmp_path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")

    result = CsvParser().parse(path)

    assert result.extracted_text == ""
    assert result.metadata["parser_id"] == "parser.csv"
    assert result.metadata["status"] == "degraded"
    assert "degraded_reason" in result.metadata
    assert result.metadata["line_count"] == 0
    assert result.metadata["char_count"] == 0
    assert result.metadata["byte_count"] == 0
    assert result.metadata["row_count"] == 0
    assert result.metadata["col_count"] == 0
    assert result.metadata["text_summary"] == ""


def test_csv_parser_garbled_utf8_encoding_raises(tmp_path) -> None:
    path = tmp_path / "garbled.csv"
    # Write raw bytes that are not valid UTF-8
    path.write_bytes(b"col1,col2\n" + b"\x80\x81\xfe\xff\n")

    with pytest.raises(UnicodeDecodeError):
        CsvParser().parse(path)


def test_csv_parser_oversized_line_is_handled(tmp_path) -> None:
    path = tmp_path / "oversized.csv"
    # Create a file with a very long single line
    long_value = "x" * 500_000
    raw_text = f"id,data\n1,{long_value}\n"
    path.write_text(raw_text, encoding="utf-8")

    result = CsvParser().parse(path)

    assert result.parser_name == "csv"
    assert result.metadata["char_count"] == len(raw_text)
    assert result.metadata["line_count"] == 2
    assert result.metadata["row_count"] == 2
    assert result.metadata["col_count"] == 2
    # text_summary should be truncated, not the full 500K line
    assert len(result.metadata["text_summary"]) <= 81
    # extracted_text IS full (it's the parse output, not metadata)
    assert result.extracted_text == raw_text


def test_csv_parser_sensitive_fields_not_leaked_in_metadata(tmp_path) -> None:
    path = tmp_path / "sensitive.csv"
    raw_text = "name,api_key,password\nadmin,sk-secret-12345,sk-pass-abcdefghij\n"
    path.write_text(raw_text, encoding="utf-8")

    result = CsvParser().parse(path)

    # No secret-like KEYS in metadata
    for key in ("api_key", "password", "secret", "token", "credential"):
        assert key not in result.metadata, f"metadata should not have key '{key}'"
    # text_summary is truncated to 80 chars
    assert len(result.metadata["text_summary"]) <= 81
    # Sensitive values must not appear in text_summary
    summary = result.metadata["text_summary"]
    assert "sk-secret-12345" not in summary
    assert "sk-pass-abcdefghij" not in summary
    assert result.metadata["redaction_count"] >= 2
    # Non-summary metadata fields must never contain the full text
    for key, value in result.metadata.items():
        if key == "text_summary":
            continue
        if isinstance(value, str):
            assert raw_text not in value, f"metadata key '{key}' contains full raw text"


def test_csv_parser_handles_single_column(tmp_path) -> None:
    path = tmp_path / "single.csv"
    raw_text = "only_col\nval1\nval2\n"
    path.write_text(raw_text, encoding="utf-8")

    result = CsvParser().parse(path)

    assert result.metadata["row_count"] == 3
    assert result.metadata["col_count"] == 1
    assert result.metadata["parser_id"] == "parser.csv"
    assert result.metadata["status"] == "degraded"


def test_csv_parser_malformed_csv_tracks_parse_error(tmp_path, monkeypatch) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("col1,col2\na,b\n", encoding="utf-8")

    def _broken_reader(*args, **kwargs):
        raise RuntimeError("simulated csv failure")

    monkeypatch.setattr("ragrig.parsers.csv.csv.reader", _broken_reader)

    result = CsvParser().parse(path)

    # Still gets the text and counts
    assert result.extracted_text != ""
    assert result.metadata["row_count"] == 0
    assert result.metadata["col_count"] == 0
    assert result.metadata["parser_id"] == "parser.csv"
    assert result.metadata["status"] == "degraded"
    # csv_parse_error should be present when csv.reader fails
    assert "csv_parse_error" in result.metadata


# ── Fixture Corpus Tests: HTML ──


def test_html_parser_empty_file_metadata_is_stable(tmp_path) -> None:
    path = tmp_path / "empty.html"
    path.write_text("", encoding="utf-8")

    result = HtmlParser().parse(path)

    assert result.extracted_text == ""
    assert result.metadata["parser_id"] == "parser.html"
    assert result.metadata["status"] == "degraded"
    assert "degraded_reason" in result.metadata
    assert result.metadata["line_count"] == 0
    assert result.metadata["char_count"] == 0
    assert result.metadata["stripped_char_count"] == 0
    assert result.metadata["text_summary"] == ""


def test_html_parser_garbled_encoding_raises(tmp_path) -> None:
    path = tmp_path / "garbled.html"
    path.write_bytes(b"<html><body>" + b"\xff\xfe\x00" + b"</body></html>")

    with pytest.raises(UnicodeDecodeError):
        HtmlParser().parse(path)


def test_html_parser_malformed_html_is_handled_gracefully(tmp_path) -> None:
    path = tmp_path / "malformed.html"
    raw_text = (
        "<html><body><h1>Title"
        "<p>unclosed para"
        "<script>if(x<5){alert('xss')}</script>"
        "<div>no close"
        "<!-- unclosed comment"
    )
    path.write_text(raw_text, encoding="utf-8")

    result = HtmlParser().parse(path)

    # Should not raise; should strip what it can
    assert result.parser_name == "html"
    assert result.metadata["parser_id"] == "parser.html"
    assert result.metadata["status"] == "degraded"
    # Stripped text should not contain tags
    assert "<script>" not in result.extracted_text
    assert "</script>" not in result.extracted_text
    # But the js code text may remain (tag-stripping doesn't parse JS)
    assert "text_summary" in result.metadata
    assert "degraded_reason" in result.metadata


def test_html_parser_xss_script_tags_are_stripped(tmp_path) -> None:
    path = tmp_path / "xss.html"
    raw_text = (
        '<html><body><script>alert("XSS")</script><p onclick="evil()">Clickable</p></body></html>'
    )
    path.write_text(raw_text, encoding="utf-8")

    result = HtmlParser().parse(path)

    assert "<script>" not in result.extracted_text
    assert "</script>" not in result.extracted_text
    assert result.metadata["parser_id"] == "parser.html"
    assert result.metadata["status"] == "degraded"


def test_html_parser_sensitive_fields_not_leaked_in_metadata(tmp_path) -> None:
    path = tmp_path / "sensitive.html"
    raw_text = (
        "<html><body>"
        '<script>const SECRET="sk-abc-123";</script>'
        "<pre>password: admin123</pre>"
        "</body></html>"
    )
    path.write_text(raw_text, encoding="utf-8")

    result = HtmlParser().parse(path)

    # Metadata should not leak extracted secret patterns
    metadata_str = str(result.metadata)
    assert raw_text not in metadata_str
    # The text_summary must not contain raw secret values
    summary = result.metadata["text_summary"]
    assert "sk-abc-123" not in summary
    assert "admin123" not in summary
    assert result.metadata["parser_id"] == "parser.html"
    assert result.metadata["status"] == "degraded"
    assert result.metadata["redaction_count"] >= 1


def test_html_parser_large_document_is_handled(tmp_path) -> None:
    path = tmp_path / "large.html"
    # Create a large HTML document
    body_content = "<p>Paragraph content.</p>" * 10_000
    raw_text = f"<html><body>{body_content}</body></html>"
    path.write_text(raw_text, encoding="utf-8")

    result = HtmlParser().parse(path)

    assert result.parser_name == "html"
    assert result.metadata["char_count"] == len(raw_text)
    assert result.metadata["stripped_char_count"] < len(raw_text)
    # text_summary must be truncated
    assert len(result.metadata["text_summary"]) <= 81
    assert result.metadata["parser_id"] == "parser.html"
    assert result.metadata["status"] == "degraded"


# ── Parser Metadata Schema Tests ──

STABLE_METADATA_FIELDS = frozenset(
    {
        "parser_id",
        "status",
        "degraded_reason",
    }
)

METADATA_NO_SECRET_PATTERNS = frozenset(
    {
        "api_key",
        "password",
        "secret",
        "token",
        "credential",
    }
)


def _assert_stable_metadata(metadata: dict, expected_parser_id: str, expected_status: str) -> None:
    assert metadata["parser_id"] == expected_parser_id
    assert metadata["status"] == expected_status
    assert "extension" in metadata
    assert "line_count" in metadata
    assert "char_count" in metadata
    assert "byte_count" in metadata
    assert "text_summary" in metadata
    assert "redaction_count" in metadata
    assert isinstance(metadata["text_summary"], str)
    assert isinstance(metadata["redaction_count"], int)
    assert metadata["redaction_count"] >= 0
    # text_summary is at most 81 chars (80 + optional ellipsis)
    assert len(metadata["text_summary"]) <= 81
    # metadata must not contain secret-like keys
    for key in METADATA_NO_SECRET_PATTERNS:
        assert key not in metadata, f"metadata should not contain '{key}'"


@pytest.mark.parametrize(
    "parser_cls,expected_parser_id,expected_status",
    [
        (MarkdownParser, "parser.markdown", "success"),
        (PlainTextParser, "parser.text", "success"),
        (CsvParser, "parser.csv", "degraded"),
        (HtmlParser, "parser.html", "degraded"),
    ],
)
def test_parser_returns_stable_metadata_schema(
    tmp_path, parser_cls, expected_parser_id, expected_status
) -> None:
    ext = ".csv" if parser_cls is CsvParser else ".html" if parser_cls is HtmlParser else ".md"
    path = tmp_path / f"test{ext}"
    path.write_text("sample content\nsecond line\n", encoding="utf-8")

    result = parser_cls().parse(path)

    _assert_stable_metadata(result.metadata, expected_parser_id, expected_status)


def test_all_parsers_metadata_never_contains_full_text(tmp_path) -> None:
    """Ensure no parser returns the full original text inside the metadata dict."""
    raw_text = "This is the full document content that should NOT appear in metadata.\n" * 10
    parsers = [
        (MarkdownParser(), "guide.md"),
        (PlainTextParser(), "notes.txt"),
        (CsvParser(), "data.csv"),
        (HtmlParser(), "page.html"),
    ]

    for parser, filename in parsers:
        path = tmp_path / filename
        path.write_text(raw_text, encoding="utf-8")

        result = parser.parse(path)

        # The full text must NOT appear in any metadata field value
        for key, value in result.metadata.items():
            if isinstance(value, str) and len(value) > 100:
                assert raw_text not in value, (
                    f"Parser {parser.parser_name}: metadata field '{key}' contains full text"
                )


def test_parser_text_summary_no_secrets_in_summary(tmp_path) -> None:
    """The summary sanitizer must redact sensitive key=value patterns and
    standalone API key values so they never appear in text_summary."""
    raw_text = "api_key,secret\nsk-abc12345,sk-xyz98765\n"
    path = tmp_path / "sensitive.csv"
    path.write_text(raw_text, encoding="utf-8")

    result = CsvParser().parse(path)

    # parser_id and status fields themselves never contain secrets
    assert "sk-" not in result.metadata["parser_id"]
    assert "sk-" not in result.metadata["status"]

    # The text_summary must never contain raw secret values
    summary = result.metadata["text_summary"]
    assert "sk-abc12345" not in summary
    assert "sk-xyz98765" not in summary
    # parser fields themselves must be pristine
    assert "sk-" not in str(result.metadata["parser_id"])

    # redaction_count must reflect the detected secrets
    assert result.metadata["redaction_count"] >= 2


def test_csv_parser_malformed_csv_sets_csv_parse_error_in_metadata(tmp_path, monkeypatch) -> None:
    """When csv.reader throws, the error is captured in metadata."""
    path = tmp_path / "bad.csv"
    path.write_text("col1,col2\na,b\n", encoding="utf-8")

    def _broken_reader(*args, **kwargs):
        raise ValueError("NUL byte in CSV")

    monkeypatch.setattr("ragrig.parsers.csv.csv.reader", _broken_reader)

    result = CsvParser().parse(path)

    assert "csv_parse_error" in result.metadata
    assert result.metadata["csv_parse_error"] == "NUL byte in CSV"
    assert result.metadata["status"] == "degraded"


# ── Summary Sanitizer Tests ──


class TestSanitizeTextSummary:
    def test_empty_text_returns_empty(self):
        summary, redactions = sanitize_text_summary("")
        assert summary == ""
        assert redactions == 0

    def test_clean_text_passes_through(self):
        summary, redactions = sanitize_text_summary("Hello world")
        assert summary == "Hello world"
        assert redactions == 0

    def test_truncates_long_text(self):
        long_text = "x" * 200
        summary, redactions = sanitize_text_summary(long_text)
        assert len(summary) == 81  # 80 + "…"
        assert summary.endswith("…")
        assert redactions == 0

    def test_redacts_api_key_env_var(self):
        summary, redactions = sanitize_text_summary("api_key=sk-abc123secretkey")
        assert "sk-abc123secretkey" not in summary
        assert "api_key=[REDACTED]" in summary
        assert redactions == 1

    def test_redacts_api_key_with_colon(self):
        summary, redactions = sanitize_text_summary("export API_KEY: my-secret-token")
        assert "my-secret-token" not in summary
        assert "[REDACTED]" in summary
        assert redactions == 1

    def test_redacts_password_assignment(self):
        summary, redactions = sanitize_text_summary("password=super_secret_pass123")
        assert "super_secret_pass123" not in summary
        assert "password=[REDACTED]" in summary
        assert redactions == 1

    def test_redacts_token_assignment(self):
        summary, redactions = sanitize_text_summary(
            "token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        )
        assert "eyJhbGciOiJIUzI1NiJ9" not in summary
        assert "token=[REDACTED]" in summary
        assert redactions == 1

    def test_redacts_secret_assignment(self):
        summary, redactions = sanitize_text_summary("secret=my-super-secret-key")
        assert "my-super-secret-key" not in summary
        assert "secret=[REDACTED]" in summary
        assert redactions == 1

    def test_redacts_bearer_token(self):
        summary, redactions = sanitize_text_summary(
            "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.abc.def"
        )
        assert "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9" not in summary
        assert "Bearer [REDACTED]" in summary
        assert redactions >= 1

    def test_redacts_private_key_block(self):
        summary, redactions = sanitize_text_summary(
            """-----BEGIN RSA PRIVATE KEY-----
MIIEpAIBAAKCAQEA...
-----END RSA PRIVATE KEY-----"""
        )
        assert "MIIEpA" not in summary
        assert "[PRIVATE KEY REDACTED]" in summary
        assert redactions >= 1

    def test_redacts_multiple_patterns(self):
        text = "api_key=sk-abc123\npassword=pass456\nBearer token789\n"
        summary, redactions = sanitize_text_summary(text)
        assert "sk-abc123" not in summary
        assert "pass456" not in summary
        assert "token789" not in summary
        assert redactions >= 3

    def test_redacts_access_token_variant(self):
        summary, redactions = sanitize_text_summary("access_token=ghp_1234567890abcdef")
        assert "ghp_1234567890abcdef" not in summary
        assert "token=[REDACTED]" in summary
        assert redactions == 1

    def test_sk_api_key_standalone_redacted(self):
        """Standalone sk- prefixed keys are redacted even without key= prefix."""
        summary, redactions = sanitize_text_summary(
            "Using key sk-proj-abcdefghijklmnopqrstuvwxyz123456 for auth"
        )
        assert "sk-proj-abcdefghijklmnopqrstuvwxyz123456" not in summary
        assert "[API KEY REDACTED]" in summary
        assert redactions >= 1

    def test_redaction_count_zero_for_clean_text(self):
        summary, redactions = sanitize_text_summary(
            "# Project Documentation\n\nThis is a clean markdown file."
        )
        assert redactions == 0
        assert "[REDACTED]" not in summary

    def test_case_insensitive_key_matching(self):
        summary, redactions = sanitize_text_summary("API_KEY=prod-secret")
        assert "prod-secret" not in summary
        assert "[REDACTED]" in summary
        assert redactions >= 1

    def test_case_insensitive_bearer(self):
        summary, redactions = sanitize_text_summary("bearer mytoken123")
        assert "mytoken123" not in summary
        assert "Bearer [REDACTED]" in summary
        assert redactions >= 1


# ── Sensitive Fixture Corpus Tests ──

SENSITIVE_FIXTURES = {
    "api_key_env": ("API_KEY=sk-live-1234567890abcdefghij", CsvParser),
    "bearer_token": ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc.def", PlainTextParser),
    "password_config": ("db_password=super_secure_db_pass_123", PlainTextParser),
    "token_header": ('{"token": "ghp_abcdef1234567890"}', PlainTextParser),
    "secret_yaml": ("secret: prod-api-secret-key-2024", MarkdownParser),
    "private_key": (
        """-----BEGIN EC PRIVATE KEY-----
MHcCAQEEI...
-----END EC PRIVATE KEY-----""",
        PlainTextParser,
    ),
    "multiple_creds": (
        "api_key=sk-abc\npassword=pass123\ntoken=secret456",
        CsvParser,
    ),
}


@pytest.mark.parametrize(
    "fixture_name,text,parser_cls",
    [(name, text, parser_cls) for name, (text, parser_cls) in SENSITIVE_FIXTURES.items()],
)
def test_sensitive_fixture_no_secret_in_summary(tmp_path, fixture_name, text, parser_cls) -> None:
    ext_map = {
        CsvParser: ".csv",
        HtmlParser: ".html",
        PlainTextParser: ".txt",
        MarkdownParser: ".md",
    }
    ext = ext_map[parser_cls]
    path = tmp_path / f"{fixture_name}{ext}"
    path.write_text(text, encoding="utf-8")

    result = parser_cls().parse(path)
    summary = result.metadata["text_summary"]
    assert result.metadata["redaction_count"] >= 1, (
        f"Fixture '{fixture_name}': redaction_count must be >= 1"
    )
    # Raw secret fragments must not appear in summary
    for fragment in (
        "sk-live",
        "eyJhbGciOiJIUzI1NiJ9",
        "super_secure_db_pass_123",
        "ghp_abcdef",
        "prod-api-secret-key-2024",
        "MHcCAQEEI",
    ):
        assert fragment not in summary, (
            f"Fixture '{fixture_name}': secret fragment '{fragment}' leaked in summary"
        )


def test_all_parsers_share_same_sanitizer(tmp_path) -> None:
    """CSV/HTML/plaintext/markdown all produce redacted summaries for the same
    sensitive content."""
    sensitive_text = "api_key=sk-top-secret-1234567890"
    parsers = [
        (CsvParser(), "data.csv"),
        (HtmlParser(), "page.html"),
        (PlainTextParser(), "notes.txt"),
        (MarkdownParser(), "guide.md"),
    ]

    for parser, filename in parsers:
        path = tmp_path / filename
        path.write_text(sensitive_text, encoding="utf-8")
        result = parser.parse(path)
        summary = result.metadata["text_summary"]
        assert "sk-top-secret-1234567890" not in summary, (
            f"Parser '{parser.parser_name}' leaked secret in summary"
        )
        assert "[REDACTED]" in summary, f"Parser '{parser.parser_name}' did not redact summary"
        assert result.metadata["redaction_count"] >= 1, (
            f"Parser '{parser.parser_name}' redaction_count is 0"
        )


def test_sensitive_fixture_pipeline_run_items_queryable(tmp_path) -> None:
    """Verify that when a sensitive fixture is parsed, the resulting metadata
    (key/value/summary) can be queried without leaking raw secret values."""
    sensitive_text = "api_key=sk-secret-12345\npassword=admin_pass\n"
    path = tmp_path / "creds.csv"
    path.write_text(sensitive_text, encoding="utf-8")

    result = CsvParser().parse(path)
    metadata = result.metadata

    # All metadata string values must not contain raw secret fragments
    for key, value in metadata.items():
        if isinstance(value, str):
            assert "sk-secret-12345" not in value, f"metadata['{key}'] contains API key value"
            assert "admin_pass" not in value, f"metadata['{key}'] contains password value"

    # Redaction markers present
    assert "[REDACTED]" in metadata["text_summary"]
    assert metadata["redaction_count"] >= 2


def test_empty_and_edge_case_files_preserve_diagnostics(tmp_path) -> None:
    """Empty files, garbled text, and oversized lines must still produce
    valid status/degraded_reason and bounded summary length."""
    # Empty file
    empty_path = tmp_path / "empty.csv"
    empty_path.write_text("", encoding="utf-8")
    empty_result = CsvParser().parse(empty_path)
    assert empty_result.metadata["text_summary"] == ""
    assert empty_result.metadata["redaction_count"] == 0
    assert empty_result.metadata["status"] == "degraded"
    assert "degraded_reason" in empty_result.metadata

    # Oversized line
    big_path = tmp_path / "big.csv"
    big_path.write_text(f"id,data\n1,{'x' * 500_000}\n", encoding="utf-8")
    big_result = CsvParser().parse(big_path)
    assert len(big_result.metadata["text_summary"]) <= 81
    assert big_result.metadata["redaction_count"] == 0

    # Malformed HTML
    html_path = tmp_path / "bad.html"
    html_path.write_text("<html><body><h1>Title<p>unclosed<script>alert(1)", encoding="utf-8")
    html_result = HtmlParser().parse(html_path)
    assert html_result.metadata["status"] == "degraded"
    assert "degraded_reason" in html_result.metadata
    assert len(html_result.metadata["text_summary"]) <= 81
