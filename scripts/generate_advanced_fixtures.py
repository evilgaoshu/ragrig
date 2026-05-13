"""Generate small, reproducible fixture files for the advanced parser corpus.

Produces minimal PDF, DOCX, PPTX, and XLSX files with known content.
Uses only Python standard library modules — no external dependencies required.

Output directory: tests/fixtures/advanced_documents/
"""

from __future__ import annotations

import hashlib
import zipfile
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "advanced_documents"


def _make_zip(entries: dict[str, bytes]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _content_types_xml(overrides: dict[str, str] | None = None) -> bytes:
    defaults = {
        ".xml": "application/xml",
        ".rels": "application/vnd.openxmlformats-package.relationships+xml",
    }
    if overrides:
        defaults.update(overrides)
    parts = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    parts += '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    for ext, ct in defaults.items():
        parts += f'<Default Extension="{ext.lstrip(".")}" ContentType="{xml_escape(ct)}"/>'
    parts += "</Types>"
    return parts.encode("utf-8")


def _rels_xml(*parts: tuple[str, str, str]) -> bytes:
    xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    xml += '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    for _idx, (rel_id, rel_type, target) in enumerate(parts, 1):
        xml += f'<Relationship Id="{rel_id}" Type="{xml_escape(rel_type)}" Target="{xml_escape(target)}"/>'  # noqa: E501
    xml += "</Relationships>"
    return xml.encode("utf-8")


DOCX_REL_TYPES = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
)
XLSX_REL_TYPES = DOCX_REL_TYPES
PPTX_REL_TYPES = DOCX_REL_TYPES


def generate_docx(text: str) -> bytes:
    return _make_zip(
        {
            "[Content_Types].xml": _content_types_xml(
                {
                    ".xml": "application/xml",
                    ".rels": "application/vnd.openxmlformats-package.relationships+xml",
                }
            ),
            "_rels/.rels": _rels_xml(("rId1", DOCX_REL_TYPES, "word/document.xml")),
            "word/document.xml": (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body>"
                f"<w:p><w:r><w:t>{xml_escape(text)}</w:t></w:r></w:p>"
                "</w:body>"
                "</w:document>"
            ).encode("utf-8"),
            "word/_rels/document.xml.rels": _rels_xml(),
        }
    )


def generate_xlsx(text: str) -> bytes:
    return _make_zip(
        {
            "[Content_Types].xml": _content_types_xml(
                {
                    ".xml": "application/xml",
                    ".rels": "application/vnd.openxmlformats-package.relationships+xml",
                }
            ),
            "_rels/.rels": _rels_xml(("rId1", XLSX_REL_TYPES, "xl/workbook.xml")),
            "xl/workbook.xml": (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
                "</sheets>"
                "</workbook>"
            ).encode("utf-8"),
            "xl/_rels/workbook.xml.rels": _rels_xml(
                (
                    "rId1",
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
                    "worksheets/sheet1.xml",
                )
            ),
            "xl/worksheets/sheet1.xml": (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                "<sheetData>"
                '<row r="1"><c r="A1" t="inlineStr"><is><t>Data</t></is></c></row>'
                '<row r="2"><c r="A2" t="inlineStr"><is><t>'
                f"{xml_escape(text)}</t></is></c></row>"
                "</sheetData>"
                "</worksheet>"
            ).encode("utf-8"),
        }
    )


def generate_pptx(text: str) -> bytes:
    return _make_zip(
        {
            "[Content_Types].xml": _content_types_xml(
                {
                    ".xml": "application/xml",
                    ".rels": "application/vnd.openxmlformats-package.relationships+xml",
                }
            ),
            "_rels/.rels": _rels_xml(("rId1", PPTX_REL_TYPES, "ppt/presentation.xml")),
            "ppt/presentation.xml": (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                '<p:sldIdLst><p:sldId id="256" r:id="rId2"/>'
                '<p:sldId id="257" r:id="rId3"/></p:sldIdLst>'
                '<p:sldSz cx="9144000" cy="6858000"/>'
                "</p:presentation>"
            ).encode("utf-8"),
            "ppt/_rels/presentation.xml.rels": _rels_xml(
                (
                    "rId2",
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
                    "slides/slide1.xml",
                ),
                (
                    "rId3",
                    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
                    "slides/slide2.xml",
                ),
            ),
            "ppt/slides/slide1.xml": (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                '<p:cSld><p:spTree><p:nvGrpSpPr><p:nvPr/><p:cNvPr id="1" name=""/>'
                "<p:nvGrpSpPr/></p:nvGrpSpPr>"
                '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Title 1"/>'
                "<p:nvSpPr/><p:prstTxWarp/></p:nvSpPr>"
                '<p:spPr/><p:txBody><a:p xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                f"<a:r><a:t>{xml_escape(text)}</a:t></a:r></a:p></p:txBody></p:sp>"
                "</p:spTree></p:cSld>"
                "</p:sld>"
            ).encode("utf-8"),
            "ppt/slides/slide2.xml": (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                '<p:cSld><p:spTree><p:nvGrpSpPr><p:nvPr/><p:cNvPr id="1" name=""/>'
                "<p:nvGrpSpPr/></p:nvGrpSpPr>"
                '<p:sp><p:nvSpPr><p:cNvPr id="2" name="Title 2"/>'
                "<p:nvSpPr/><p:prstTxWarp/></p:nvSpPr>"
                '<p:spPr/><p:txBody><a:p xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
                "<a:r><a:t>Slide two</a:t></a:r></a:p></p:txBody></p:sp>"
                "</p:spTree></p:cSld>"
                "</p:sld>"
            ).encode("utf-8"),
        }
    )


def generate_pdf(text: str) -> bytes:
    content = "1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj "
    content += "2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj "
    content += (
        "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R"
        "/Resources<</Font<</F1 5 0 R>>>>>>endobj "
    )  # noqa: E501
    content += (
        f"4 0 obj<</Length 44>>stream BT /F1 12 Tf 72 720 Td "
        f"({xml_escape(text)}) Tj ET endstream endobj "
    )  # noqa: E501
    content += "5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj "
    content += (
        "xref 0 6 0000000000 65535 f 0000000009 00000 n 0000000058 00000 n "
        "0000000115 00000 n 0000000266 00000 n 0000000364 00000 n "
        "trailer<</Size 6/Root 1 0 R>>startxref 414 %%EOF"
    )
    return f"%PDF-1.4\n{content}".encode("latin-1")


FIXTURE_SPECS = [
    ("sample.pdf", generate_pdf, "Hello from RAGRig PDF fixture"),
    ("sample.docx", generate_docx, "Hello from RAGRig DOCX fixture"),
    ("sample.pptx", generate_pptx, "Hello from RAGRig PPTX fixture"),
    ("sample.xlsx", generate_xlsx, "Hello from RAGRig XLSX fixture"),
]


def main() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for filename, generator, content in FIXTURE_SPECS:
        data = generator(content)
        path = FIXTURES_DIR / filename
        path.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        hashes[filename] = digest
        print(f"  ✓ {filename}  ({len(data)} bytes)  sha256={digest[:16]}...")

    print(f"\nGenerated {len(FIXTURE_SPECS)} fixtures in {FIXTURES_DIR}")


if __name__ == "__main__":
    main()
