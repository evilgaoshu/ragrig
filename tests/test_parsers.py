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
