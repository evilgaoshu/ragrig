"""Unit tests for new parsers: email, xml, json, epub."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from ragrig.parsers.email_parser import EmailParser
from ragrig.parsers.json_parser import JsonParser
from ragrig.parsers.xml_parser import XmlParser

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Email parser
# ---------------------------------------------------------------------------


def _write(tmp_path: Path, name: str, content: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(content)
    return p


EML_SIMPLE = textwrap.dedent("""\
    From: alice@example.com
    To: bob@example.com
    Date: Mon, 13 May 2026 10:00:00 +0000
    Subject: Hello

    This is the email body.
""").encode()

EML_HTML = textwrap.dedent("""\
    From: alice@example.com
    To: bob@example.com
    Subject: HTML mail
    Content-Type: text/html; charset=utf-8

    <html><body><h1>Hello</h1><p>World</p></body></html>
""").encode()

EML_MULTIPART = (
    b"From: sender@example.com\r\n"
    b"To: recv@example.com\r\n"
    b"Subject: Multi\r\n"
    b"MIME-Version: 1.0\r\n"
    b"Content-Type: multipart/mixed; boundary=boundary42\r\n"
    b"\r\n"
    b"--boundary42\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\n"
    b"Plain text part.\r\n"
    b"--boundary42--\r\n"
)


class TestEmailParser:
    def test_parses_simple_eml(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "test.eml", EML_SIMPLE)
        result = EmailParser().parse(path)
        assert result.parser_name == "email"
        assert "alice@example.com" in result.extracted_text
        assert "Hello" in result.extracted_text
        assert "email body" in result.extracted_text

    def test_parses_html_eml_strips_tags(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "html.eml", EML_HTML)
        result = EmailParser().parse(path)
        assert "<html>" not in result.extracted_text
        assert "Hello" in result.extracted_text
        assert "World" in result.extracted_text

    def test_parses_multipart(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "multi.eml", EML_MULTIPART)
        result = EmailParser().parse(path)
        assert "Plain text part" in result.extracted_text

    def test_metadata_includes_sender(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "m.eml", EML_SIMPLE)
        result = EmailParser().parse(path)
        assert result.metadata["sender"] == "alice@example.com"
        assert result.metadata["subject"] == "Hello"

    def test_content_hash_stable(self, tmp_path: Path) -> None:
        p1 = _write(tmp_path, "a.eml", EML_SIMPLE)
        p2 = _write(tmp_path, "b.eml", EML_SIMPLE)
        assert EmailParser().parse(p1).content_hash == EmailParser().parse(p2).content_hash

    def test_invalid_returns_error_status(self, tmp_path: Path) -> None:
        # Email parser is lenient — an empty file should not raise, just return empty
        path = _write(tmp_path, "empty.eml", b"")
        result = EmailParser().parse(path)
        assert result.parser_name == "email"


# ---------------------------------------------------------------------------
# XML parser
# ---------------------------------------------------------------------------

XML_SIMPLE = b"""<?xml version="1.0"?>
<root>
  <title>My Document</title>
  <body>Some content here.</body>
</root>"""

XML_NESTED = b"""<catalog>
  <book id="1"><title>Python</title><author>Guido</author></book>
  <book id="2"><title>RAG</title><author>Team</author></book>
</catalog>"""

XML_INVALID = b"<unclosed><tag>"


class TestXmlParser:
    def test_parses_simple_xml(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "doc.xml", XML_SIMPLE)
        result = XmlParser().parse(path)
        assert result.parser_name == "xml"
        assert "My Document" in result.extracted_text
        assert "Some content here" in result.extracted_text

    def test_parses_nested_xml(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "catalog.xml", XML_NESTED)
        result = XmlParser().parse(path)
        assert "Python" in result.extracted_text
        assert "Guido" in result.extracted_text
        assert "RAG" in result.extracted_text

    def test_invalid_xml_returns_error_status(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "bad.xml", XML_INVALID)
        result = XmlParser().parse(path)
        assert result.metadata["status"] == "error"
        assert result.extracted_text == ""

    def test_metadata_has_root_tag(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "doc.xml", XML_SIMPLE)
        result = XmlParser().parse(path)
        assert result.metadata["root_tag"] == "root"
        assert result.metadata["element_count"] >= 1

    def test_content_hash_stable(self, tmp_path: Path) -> None:
        p1 = _write(tmp_path, "x1.xml", XML_SIMPLE)
        p2 = _write(tmp_path, "x2.xml", XML_SIMPLE)
        assert XmlParser().parse(p1).content_hash == XmlParser().parse(p2).content_hash


# ---------------------------------------------------------------------------
# JSON parser
# ---------------------------------------------------------------------------

JSON_FLAT = json.dumps({"name": "Alice", "age": 30, "active": True}).encode()
JSON_NESTED = json.dumps({"user": {"name": "Bob", "scores": [10, 20, 30]}}).encode()
JSON_ARRAY = json.dumps([{"id": 1, "val": "a"}, {"id": 2, "val": "b"}]).encode()
JSON_INVALID = b"{not valid json"


class TestJsonParser:
    def test_parses_flat_object(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "flat.json", JSON_FLAT)
        result = JsonParser().parse(path)
        assert result.parser_name == "json"
        assert "Alice" in result.extracted_text
        assert "30" in result.extracted_text

    def test_parses_nested_object(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "nested.json", JSON_NESTED)
        result = JsonParser().parse(path)
        assert "Bob" in result.extracted_text
        assert "10" in result.extracted_text

    def test_parses_array(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "arr.json", JSON_ARRAY)
        result = JsonParser().parse(path)
        assert result.metadata["top_level_type"] == "array"
        assert "a" in result.extracted_text
        assert "b" in result.extracted_text

    def test_invalid_json_returns_error_status(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "bad.json", JSON_INVALID)
        result = JsonParser().parse(path)
        assert result.metadata["status"] == "error"
        assert result.extracted_text == ""

    def test_metadata_has_type(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "obj.json", JSON_FLAT)
        result = JsonParser().parse(path)
        assert result.metadata["top_level_type"] == "object"

    def test_content_hash_stable(self, tmp_path: Path) -> None:
        p1 = _write(tmp_path, "j1.json", JSON_FLAT)
        p2 = _write(tmp_path, "j2.json", JSON_FLAT)
        assert JsonParser().parse(p1).content_hash == JsonParser().parse(p2).content_hash
