from __future__ import annotations

from hashlib import sha256

import pytest

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
