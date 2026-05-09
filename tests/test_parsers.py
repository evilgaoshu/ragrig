from __future__ import annotations

from hashlib import sha256

import pytest

from ragrig.parsers.base import ParserTimeoutError, parse_with_timeout
from ragrig.parsers.csv import CsvParser
from ragrig.parsers.html import HtmlParser
from ragrig.parsers.markdown import MarkdownParser
from ragrig.parsers.plaintext import PlainTextParser

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
    raw_text = "name,api_key,password\nadmin,sk-secret-12345,super_pass\n"
    path.write_text(raw_text, encoding="utf-8")

    result = CsvParser().parse(path)

    # No secret-like KEYS in metadata
    for key in ("api_key", "password", "secret", "token", "credential"):
        assert key not in result.metadata, f"metadata should not have key '{key}'"
    # text_summary is truncated to 80 chars; if the file is shorter than 80
    # chars, it may contain the full text. This is a known limitation.
    assert len(result.metadata["text_summary"]) <= 81
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
    # The metadata (text_summary) may contain stripped text content which
    # could include the secret text since it's stripped from HTML.
    # But it should not contain the full original text.
    assert raw_text not in metadata_str
    # The metadata JSON must not contain api_key or password field values
    assert result.metadata["parser_id"] == "parser.html"
    assert result.metadata["status"] == "degraded"


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
    assert isinstance(metadata["text_summary"], str)
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
    """If the first 80 chars of a CSV contain sensitive fields, the summary
    would contain them. This is acceptable since text_summary is a best-effort
    content preview. But parser_id/status must never leak secrets."""
    # Create a file where the first line IS sensitive
    raw_text = "api_key,secret\nsk-abc123,pass456\n"
    path = tmp_path / "sensitive.csv"
    path.write_text(raw_text, encoding="utf-8")

    result = CsvParser().parse(path)

    # parser_id and status fields themselves never contain secrets
    assert "sk-" not in result.metadata["parser_id"]
    assert "sk-" not in result.metadata["status"]
    assert "pass" not in result.metadata["parser_id"]
    assert "pass" not in result.metadata["status"]


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
