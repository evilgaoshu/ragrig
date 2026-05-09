from __future__ import annotations

import pytest

from ragrig.ingestion.scanner import scan_paths

pytestmark = pytest.mark.unit


def test_scan_paths_discovers_supported_text_files_and_reports_skips(tmp_path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    nested = docs / "nested"
    nested.mkdir()

    markdown_path = docs / "guide.md"
    text_path = nested / "notes.txt"
    empty_path = docs / "empty.txt"
    binary_path = docs / "binary.bin"
    ignored_dir = docs / ".git"
    ignored_dir.mkdir()
    ignored_path = ignored_dir / "ignored.md"

    markdown_path.write_text("# Guide\n", encoding="utf-8")
    text_path.write_text("notes\n", encoding="utf-8")
    empty_path.write_text("", encoding="utf-8")
    binary_path.write_bytes(b"\x00\x01\x02")
    ignored_path.write_text("# ignored\n", encoding="utf-8")

    result = scan_paths(root_path=docs)

    discovered_paths = sorted(item.path.relative_to(docs).as_posix() for item in result.discovered)
    skipped = {item.path.relative_to(docs).as_posix(): item.reason for item in result.skipped}

    assert discovered_paths == ["empty.txt", "guide.md", "nested/notes.txt"]
    assert skipped["binary.bin"] == "unsupported_extension"
    assert "ignored.md" not in discovered_paths


def test_scan_paths_honors_include_exclude_and_size_limit(tmp_path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()

    included = docs / "keep.md"
    excluded = docs / "skip.md"
    too_large = docs / "large.txt"

    included.write_text("keep", encoding="utf-8")
    excluded.write_text("skip", encoding="utf-8")
    too_large.write_text("0123456789", encoding="utf-8")

    result = scan_paths(
        root_path=docs,
        include_patterns=["*.md", "*.txt"],
        exclude_patterns=["skip.*"],
        max_file_size_bytes=5,
    )

    discovered_paths = [item.path.relative_to(docs).as_posix() for item in result.discovered]
    skipped = {item.path.relative_to(docs).as_posix(): item.reason for item in result.skipped}

    assert discovered_paths == ["keep.md"]
    assert skipped["large.txt"] == "file_too_large"
    assert skipped["skip.md"] == "excluded"


def test_scan_paths_skips_binary_content_even_with_supported_extension(tmp_path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()

    binary_text = docs / "binary.txt"
    binary_text.write_bytes(b"\x00\x01binary")

    result = scan_paths(root_path=docs)

    assert result.discovered == []
    assert [(item.path.relative_to(docs).as_posix(), item.reason) for item in result.skipped] == [
        ("binary.txt", "binary_file")
    ]


def test_scan_paths_rejects_missing_root_path(tmp_path) -> None:
    missing = tmp_path / "missing"

    try:
        scan_paths(root_path=missing)
    except FileNotFoundError:
        pass
    else:  # pragma: no cover - defensive branch for explicit failure message
        raise AssertionError("expected FileNotFoundError for missing root path")
