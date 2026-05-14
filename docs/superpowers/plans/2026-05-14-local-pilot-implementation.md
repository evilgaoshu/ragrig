# Local Pilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first RAGRig Local Pilot vertical slice: document upload, lightweight website import, model health, Gemini answer smoke, indexing, and Web Console orchestration.

**Architecture:** Reuse the existing FastAPI app, repository layer, parser registry, provider registry, indexing pipeline, retrieval API, answer service, and Web Console. Add thin local-pilot boundaries where the current code lacks an explicit user-facing operation, keeping enterprise connector work out of this slice.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy, PostgreSQL/pgvector, optional Qdrant, `pypdf`, `python-docx`, `httpx`, `google-genai`, pytest, existing vanilla HTML/CSS/JS Web Console.

---

## Scope Check

This plan implements the Local Pilot roadmap milestone from `docs/specs/ragrig-local-pilot-spec.md`.

It covers one vertical slice:

- Upload Markdown/TXT/PDF/DOCX.
- Import one URL, sitemap, or explicit docs URL list.
- Keep Postgres/pgvector as the default vector backend.
- Keep Qdrant optional.
- Support local/OpenAI-compatible providers through existing registry paths.
- Add Gemini health and answer smoke.
- Add Web Console wizard orchestration.

It intentionally does not implement enterprise tenant validation, Google Workspace/Microsoft 365 tenant flows, recursive crawling, scanned-PDF OCR, Vertex AI/Bedrock live runtime coverage, SSO, RBAC, or hosted SaaS controls.

## File Map

Create:

- `src/ragrig/ingestion/web_import.py`  
  Fetches one URL, sitemap, or explicit URL list; stores fetched HTML as parser input; returns structured import candidates and failure reasons.
- `src/ragrig/parsers/pdf.py`  
  Text PDF parser using `pypdf`.
- `src/ragrig/parsers/docx.py`  
  DOCX body text parser using `python-docx`.
- `src/ragrig/local_pilot/__init__.py`  
  Package export for local-pilot helpers.
- `src/ragrig/local_pilot/schema.py`  
  Request/response models shared by API and tests.
- `src/ragrig/local_pilot/service.py`  
  Orchestrates upload/import/index/answer-smoke readiness checks without duplicating parser or retrieval logic.
- `tests/test_local_pilot_web_import.py`
- `tests/test_pdf_docx_parsers.py`
- `tests/test_gemini_provider.py`
- `tests/test_local_pilot_api.py`
- `tests/test_web_console_local_pilot.py`

Modify:

- `pyproject.toml`  
  Add `pypdf`, `python-docx`, `httpx`, and optional `google-genai` dependency group.
- `uv.lock`  
  Refresh after dependency changes.
- `src/ragrig/main.py`  
  Add local pilot API endpoints and wire web import route.
- `src/ragrig/parsers/__init__.py`  
  Export PDF and DOCX parsers.
- `src/ragrig/ingestion/pipeline.py`  
  Select PDF/DOCX parsers and support URL-import staged HTML where needed.
- `src/ragrig/formats/supported_formats.yaml`  
  Promote PDF/DOCX from planned to supported or preview with explicit limitations.
- `src/ragrig/providers/cloud.py`  
  Add live Gemini provider implementation while leaving Vertex/Bedrock as catalog/stub entries.
- `src/ragrig/providers/__init__.py`  
  Register Gemini live factory.
- `src/ragrig/answer/provider.py`  
  Pass provider config into registry resolution for live answer smoke.
- `src/ragrig/web_console.py`  
  Add local-pilot status payloads if needed by the UI.
- `src/ragrig/web_console.html`  
  Add Local Pilot Wizard UI and client-side calls.
- `docs/operations/dependency-inventory.md`  
  Record new SDKs and supply-chain rationale.
- `docs/specs/ragrig-local-pilot-spec.md`  
  Mark implementation notes after the work lands.
- `README.md`
- `README.zh-CN.md`

## Task 1: Add PDF and DOCX Parser Support

**Files:**

- Create: `src/ragrig/parsers/pdf.py`
- Create: `src/ragrig/parsers/docx.py`
- Modify: `src/ragrig/parsers/__init__.py`
- Modify: `src/ragrig/ingestion/pipeline.py`
- Modify: `src/ragrig/formats/supported_formats.yaml`
- Modify: `pyproject.toml`
- Test: `tests/test_pdf_docx_parsers.py`

- [ ] **Step 1: Add failing parser tests**

Create `tests/test_pdf_docx_parsers.py` with these tests first:

```python
from pathlib import Path

import pytest

from ragrig.parsers.docx import DocxParser
from ragrig.parsers.pdf import PdfParser, PdfParserError


def test_docx_parser_extracts_paragraphs(tmp_path: Path):
    from docx import Document

    path = tmp_path / "pilot.docx"
    doc = Document()
    doc.add_heading("Pilot Guide", level=1)
    doc.add_paragraph("RAGRig imports DOCX text for the local pilot.")
    doc.save(path)

    result = DocxParser().parse(path)

    assert result.parser_name == "docx"
    assert result.mime_type.endswith("wordprocessingml.document")
    assert "Pilot Guide" in result.extracted_text
    assert "local pilot" in result.extracted_text
    assert result.metadata["status"] == "success"
    assert result.metadata["paragraph_count"] >= 2


def test_pdf_parser_reports_image_only_pdf_as_degraded(tmp_path: Path):
    path = tmp_path / "blank.pdf"
    path.write_bytes(
        b"%PDF-1.4\n1 0 obj<<>>endobj\n"
        b"2 0 obj<< /Type /Catalog /Pages 3 0 R >>endobj\n"
        b"3 0 obj<< /Type /Pages /Kids [] /Count 0 >>endobj\n"
        b"trailer<< /Root 2 0 R >>\n%%EOF"
    )

    with pytest.raises(PdfParserError, match="no extractable text"):
        PdfParser().parse(path)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
uv run pytest tests/test_pdf_docx_parsers.py -v
```

Expected: fail because `ragrig.parsers.pdf` and `ragrig.parsers.docx` do not exist.

- [ ] **Step 3: Add dependencies**

Modify `pyproject.toml`:

```toml
dependencies = [
  # keep existing entries
  "pypdf>=5.0.0",
  "python-docx>=1.1.2",
]
```

Then run:

```bash
uv lock
```

- [ ] **Step 4: Implement PDF parser**

Create `src/ragrig/parsers/pdf.py`:

```python
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from ragrig.parsers.base import ParseResult
from ragrig.parsers.sanitizer import sanitize_text_summary


class PdfParserError(ValueError):
    """Raised when a PDF cannot produce pilot-ready text."""


class PdfParser:
    parser_name = "pdf"
    mime_type = "application/pdf"

    def parse(self, path: Path) -> ParseResult:
        raw_bytes = path.read_bytes()
        try:
            reader = PdfReader(str(path))
        except Exception as exc:
            raise PdfParserError(f"PDF parse failed: {exc}") from exc

        if reader.is_encrypted:
            raise PdfParserError("encrypted PDF is not supported in the local pilot")

        page_texts: list[str] = []
        degraded_pages: list[int] = []
        for index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                page_texts.append(f"<!-- page:{index} -->\n{text}")
            else:
                degraded_pages.append(index)

        extracted_text = "\n\n".join(page_texts).strip()
        if not extracted_text:
            raise PdfParserError("PDF has no extractable text; OCR is not part of the local pilot")

        summary, redactions = sanitize_text_summary(extracted_text)
        metadata: dict[str, Any] = {
            "parser_id": "parser.pdf",
            "status": "degraded" if degraded_pages else "success",
            "page_count": len(reader.pages),
            "degraded_pages": degraded_pages,
            "char_count": len(extracted_text),
            "byte_count": len(raw_bytes),
            "text_summary": summary,
            "redaction_count": redactions,
        }
        if degraded_pages:
            metadata["degraded_reason"] = "Some pages had no extractable text."

        return ParseResult(
            extracted_text=extracted_text,
            content_hash=sha256(raw_bytes).hexdigest(),
            mime_type=self.mime_type,
            parser_name=self.parser_name,
            metadata=metadata,
        )
```

- [ ] **Step 5: Implement DOCX parser**

Create `src/ragrig/parsers/docx.py`:

```python
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from docx import Document

from ragrig.parsers.base import ParseResult
from ragrig.parsers.sanitizer import sanitize_text_summary


class DocxParserError(ValueError):
    """Raised when a DOCX cannot produce pilot-ready text."""


class DocxParser:
    parser_name = "docx"
    mime_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    def parse(self, path: Path) -> ParseResult:
        raw_bytes = path.read_bytes()
        try:
            document = Document(str(path))
        except Exception as exc:
            raise DocxParserError(f"DOCX parse failed: {exc}") from exc

        paragraphs = [item.text.strip() for item in document.paragraphs if item.text.strip()]
        extracted_text = "\n\n".join(paragraphs).strip()
        if not extracted_text:
            raise DocxParserError("DOCX has no extractable body text")

        summary, redactions = sanitize_text_summary(extracted_text)
        metadata: dict[str, Any] = {
            "parser_id": "parser.docx",
            "status": "success",
            "paragraph_count": len(paragraphs),
            "char_count": len(extracted_text),
            "byte_count": len(raw_bytes),
            "text_summary": summary,
            "redaction_count": redactions,
            "limitations": [
                "Images, comments, tracked changes, and complex tables are not extracted."
            ],
        }

        return ParseResult(
            extracted_text=extracted_text,
            content_hash=sha256(raw_bytes).hexdigest(),
            mime_type=self.mime_type,
            parser_name=self.parser_name,
            metadata=metadata,
        )
```

- [ ] **Step 6: Wire parser selection**

Modify `src/ragrig/parsers/__init__.py`:

```python
from ragrig.parsers.docx import DocxParser, DocxParserError
from ragrig.parsers.pdf import PdfParser, PdfParserError
```

Modify `_select_parser` in `src/ragrig/ingestion/pipeline.py`:

```python
from ragrig.parsers import CsvParser, DocxParser, HtmlParser, MarkdownParser, PdfParser, PlainTextParser


def _select_parser(path: Path):
    get_plugin_registry()
    ext = path.suffix.lower()
    if ext in {".md", ".markdown"}:
        return MarkdownParser()
    if ext == ".csv":
        return CsvParser()
    if ext in {".html", ".htm"}:
        return HtmlParser()
    if ext == ".pdf":
        return PdfParser()
    if ext == ".docx":
        return DocxParser()
    return PlainTextParser()
```

- [ ] **Step 7: Promote supported formats**

In `src/ragrig/formats/supported_formats.yaml`, change `.pdf` and `.docx` to `status: "supported"` with capabilities:

```yaml
capabilities:
  - parse
  - chunk
  - embed
```

Set PDF limitations to:

```yaml
limitations: "Text-based PDFs only. Encrypted and image-only PDFs fail with an explicit reason; OCR is out of scope for Local Pilot."
```

Set DOCX limitations to:

```yaml
limitations: "Extracts body text, headings, and lists. Images, comments, tracked changes, and complex tables are not extracted."
```

- [ ] **Step 8: Verify parser tests**

Run:

```bash
uv run pytest tests/test_pdf_docx_parsers.py -v
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml uv.lock src/ragrig/parsers src/ragrig/ingestion/pipeline.py src/ragrig/formats/supported_formats.yaml tests/test_pdf_docx_parsers.py
git commit -m "feat: add local pilot pdf and docx parsers"
```

## Task 2: Add Lightweight Website Import

**Files:**

- Create: `src/ragrig/ingestion/web_import.py`
- Modify: `src/ragrig/main.py`
- Test: `tests/test_local_pilot_web_import.py`

- [ ] **Step 1: Add failing web import tests**

Create `tests/test_local_pilot_web_import.py`:

```python
import httpx
import pytest

from ragrig.ingestion.web_import import (
    WebsiteImportError,
    WebsiteImportRequest,
    collect_website_imports,
)


def test_collect_single_page_import():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://example.test/page"
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><head><title>Pilot</title></head><body><main>Hello RAGRig</main></body></html>",
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    request = WebsiteImportRequest(urls=["https://example.test/page"])

    result = collect_website_imports(request, client=client)

    assert len(result.pages) == 1
    assert result.pages[0].source_url == "https://example.test/page"
    assert "Hello RAGRig" in result.pages[0].html
    assert result.failures == []


def test_rejects_non_html_content():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/json"}, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    request = WebsiteImportRequest(urls=["https://example.test/data"])

    result = collect_website_imports(request, client=client)

    assert result.pages == []
    assert result.failures[0].reason == "unsupported_content_type"


def test_caps_imported_pages():
    request = WebsiteImportRequest(urls=[f"https://example.test/{i}" for i in range(26)])

    with pytest.raises(WebsiteImportError, match="Maximum 25 URLs"):
        collect_website_imports(request, client=httpx.Client())
```

- [ ] **Step 2: Run tests and verify they fail**

```bash
uv run pytest tests/test_local_pilot_web_import.py -v
```

Expected: fail because `ragrig.ingestion.web_import` does not exist.

- [ ] **Step 3: Add dependency**

Add `httpx` to default dependencies in `pyproject.toml` if not already present:

```toml
"httpx>=0.28.0",
```

Run:

```bash
uv lock
```

- [ ] **Step 4: Implement web import collector**

Create `src/ragrig/ingestion/web_import.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx


MAX_PAGES_PER_IMPORT = 25


class WebsiteImportError(ValueError):
    """Raised when the website import request is invalid."""


@dataclass(frozen=True)
class WebsiteImportRequest:
    urls: list[str] = field(default_factory=list)
    sitemap_url: str | None = None


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
    pages: list[ImportedPage]
    failures: list[ImportFailure]


def _validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WebsiteImportError(f"unsupported URL: {url}")


def _extract_title(html: str) -> str | None:
    import re

    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    return " ".join(match.group(1).split())


def _sitemap_urls(sitemap_text: str) -> list[str]:
    root = ElementTree.fromstring(sitemap_text.encode("utf-8"))
    urls: list[str] = []
    for loc in root.findall(".//{*}loc"):
        if loc.text:
            urls.append(loc.text.strip())
    return urls


def collect_website_imports(
    request: WebsiteImportRequest,
    *,
    client: httpx.Client | None = None,
    timeout_seconds: float = 10.0,
) -> WebsiteImportResult:
    close_client = client is None
    http = client or httpx.Client(timeout=timeout_seconds, follow_redirects=True)
    try:
        urls = list(request.urls)
        if request.sitemap_url:
            _validate_url(request.sitemap_url)
            sitemap_response = http.get(request.sitemap_url)
            sitemap_response.raise_for_status()
            urls.extend(_sitemap_urls(sitemap_response.text))

        if len(urls) > MAX_PAGES_PER_IMPORT:
            raise WebsiteImportError(f"Maximum {MAX_PAGES_PER_IMPORT} URLs per import run")

        pages: list[ImportedPage] = []
        failures: list[ImportFailure] = []
        for url in urls:
            _validate_url(url)
            try:
                response = http.get(url)
                if response.status_code < 200 or response.status_code >= 300:
                    failures.append(
                        ImportFailure(url, "http_status", f"HTTP {response.status_code}")
                    )
                    continue
                content_type = response.headers.get("content-type", "")
                if "text/html" not in content_type:
                    failures.append(
                        ImportFailure(url, "unsupported_content_type", content_type or "missing")
                    )
                    continue
                if not response.text.strip():
                    failures.append(ImportFailure(url, "empty_body", "HTML response body is empty"))
                    continue
                pages.append(ImportedPage(url, response.text, _extract_title(response.text)))
            except httpx.TimeoutException:
                failures.append(ImportFailure(url, "timeout", "URL fetch timed out"))
            except httpx.HTTPError as exc:
                failures.append(ImportFailure(url, "fetch_error", str(exc)))

        return WebsiteImportResult(pages=pages, failures=failures)
    finally:
        if close_client:
            http.close()
```

- [ ] **Step 5: Add API endpoint**

Add request model in `src/ragrig/main.py`:

```python
class WebsiteImportApiRequest(BaseModel):
    urls: list[str] = Field(default_factory=list, max_length=25)
    sitemap_url: str | None = None
```

Add route after upload route:

```python
@app.post("/knowledge-bases/{kb_name}/website-import", response_model=None)
def website_import(
    kb_name: str,
    request: WebsiteImportApiRequest,
    session: Annotated[Session, Depends(get_session)],
) -> JSONResponse:
    from ragrig.ingestion.web_import import WebsiteImportRequest, collect_website_imports

    kb = get_knowledge_base_by_name(session, kb_name)
    if kb is None:
        return JSONResponse(status_code=404, content={"error": f"knowledge base '{kb_name}' not found"})

    result = collect_website_imports(
        WebsiteImportRequest(urls=request.urls, sitemap_url=request.sitemap_url)
    )
    # Persisting pages is implemented in Task 3 via the local_pilot service.
    return JSONResponse(
        status_code=202,
        content={
            "accepted_pages": len(result.pages),
            "failed_pages": len(result.failures),
            "failures": [failure.__dict__ for failure in result.failures],
        },
    )
```

Task 3 replaces the comment with persistence and pipeline run tracking.

- [ ] **Step 6: Verify web import tests**

```bash
uv run pytest tests/test_local_pilot_web_import.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src/ragrig/ingestion/web_import.py src/ragrig/main.py tests/test_local_pilot_web_import.py
git commit -m "feat: add lightweight website import collector"
```

## Task 3: Add Local Pilot Orchestration API

**Files:**

- Create: `src/ragrig/local_pilot/__init__.py`
- Create: `src/ragrig/local_pilot/schema.py`
- Create: `src/ragrig/local_pilot/service.py`
- Modify: `src/ragrig/main.py`
- Test: `tests/test_local_pilot_api.py`

- [ ] **Step 1: Add failing API/service tests**

Create `tests/test_local_pilot_api.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from ragrig.main import create_app
from ragrig.config import Settings


def test_local_pilot_status_lists_required_capabilities(tmp_path: Path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'pilot.db'}")
    app = create_app(settings=settings)
    client = TestClient(app)

    response = client.get("/local-pilot/status")

    assert response.status_code == 200
    body = response.json()
    assert body["upload"]["max_file_size_mb"] == 50
    assert ".pdf" in body["upload"]["extensions"]
    assert ".docx" in body["upload"]["extensions"]
    assert body["website_import"]["max_pages"] == 25
    assert "model.google_gemini" in body["models"]["required"]
```

- [ ] **Step 2: Run test and verify it fails**

```bash
uv run pytest tests/test_local_pilot_api.py::test_local_pilot_status_lists_required_capabilities -v
```

Expected: fail with 404 for `/local-pilot/status`.

- [ ] **Step 3: Implement schema**

Create `src/ragrig/local_pilot/schema.py`:

```python
from __future__ import annotations

from pydantic import BaseModel


class LocalPilotUploadStatus(BaseModel):
    extensions: list[str]
    max_file_size_mb: int


class LocalPilotWebsiteStatus(BaseModel):
    max_pages: int
    modes: list[str]


class LocalPilotModelStatus(BaseModel):
    required: list[str]
    local_first: list[str]
    cloud_supported: list[str]


class LocalPilotStatus(BaseModel):
    upload: LocalPilotUploadStatus
    website_import: LocalPilotWebsiteStatus
    models: LocalPilotModelStatus
```

- [ ] **Step 4: Implement service**

Create `src/ragrig/local_pilot/service.py`:

```python
from __future__ import annotations

from ragrig.ingestion.web_import import MAX_PAGES_PER_IMPORT
from ragrig.local_pilot.schema import (
    LocalPilotModelStatus,
    LocalPilotStatus,
    LocalPilotUploadStatus,
    LocalPilotWebsiteStatus,
)


def build_local_pilot_status() -> LocalPilotStatus:
    return LocalPilotStatus(
        upload=LocalPilotUploadStatus(
            extensions=[".md", ".markdown", ".txt", ".text", ".pdf", ".docx"],
            max_file_size_mb=50,
        ),
        website_import=LocalPilotWebsiteStatus(
            max_pages=MAX_PAGES_PER_IMPORT,
            modes=["single_url", "sitemap", "docs_url_list"],
        ),
        models=LocalPilotModelStatus(
            required=["model.google_gemini"],
            local_first=["model.ollama", "model.lm_studio", "model.openai_compatible"],
            cloud_supported=["model.openai", "model.openrouter", "model.google_gemini"],
        ),
    )
```

Create `src/ragrig/local_pilot/__init__.py`:

```python
from ragrig.local_pilot.service import build_local_pilot_status

__all__ = ["build_local_pilot_status"]
```

- [ ] **Step 5: Add status endpoint**

Modify `src/ragrig/main.py` imports:

```python
from ragrig.local_pilot import build_local_pilot_status
```

Add route near `/system/status`:

```python
@app.get("/local-pilot/status", response_model=None)
def local_pilot_status() -> dict[str, Any]:
    return build_local_pilot_status().model_dump()
```

- [ ] **Step 6: Verify API test**

```bash
uv run pytest tests/test_local_pilot_api.py -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/ragrig/local_pilot src/ragrig/main.py tests/test_local_pilot_api.py
git commit -m "feat: add local pilot status api"
```

## Task 4: Persist Website Imports as Pipeline Runs

**Files:**

- Modify: `src/ragrig/local_pilot/service.py`
- Modify: `src/ragrig/main.py`
- Test: `tests/test_local_pilot_api.py`

- [ ] **Step 1: Add failing persistence test**

Append to `tests/test_local_pilot_api.py`:

```python
def test_website_import_persists_pipeline_run(monkeypatch, tmp_path: Path):
    from ragrig.db.models import Base
    from ragrig.db.engine import create_db_engine
    from ragrig.db.session import create_session_factory
    from ragrig.ingestion.web_import import ImportedPage, WebsiteImportResult
    from ragrig.repositories import get_or_create_knowledge_base

    db_path = tmp_path / "pilot.db"
    settings = Settings(database_url=f"sqlite:///{db_path}")
    engine = create_db_engine(settings.database_url)
    Base.metadata.create_all(engine)
    SessionLocal = create_session_factory(engine)
    with SessionLocal() as session:
        get_or_create_knowledge_base(session, "pilot")
        session.commit()

    def fake_collect(request):
        return WebsiteImportResult(
            pages=[ImportedPage("https://example.test/doc", "<main>Hello RAGRig</main>", "Doc")],
            failures=[],
        )

    monkeypatch.setattr("ragrig.local_pilot.service.collect_website_imports", fake_collect)

    app = create_app(settings=settings, session_factory=SessionLocal)
    client = TestClient(app)
    response = client.post(
        "/knowledge-bases/pilot/website-import",
        json={"urls": ["https://example.test/doc"]},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["accepted_pages"] == 1
    assert body["pipeline_run_id"]
```

- [ ] **Step 2: Run test and verify it fails**

```bash
uv run pytest tests/test_local_pilot_api.py::test_website_import_persists_pipeline_run -v
```

Expected: fail because website route does not persist pages.

- [ ] **Step 3: Implement persistence helper**

Add to `src/ragrig/local_pilot/service.py`:

```python
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy.orm import Session

from ragrig.db.models import DocumentVersion
from ragrig.ingestion.pipeline import _select_parser
from ragrig.ingestion.web_import import WebsiteImportRequest, collect_website_imports
from ragrig.parsers.base import parse_with_timeout
from ragrig.repositories import (
    create_pipeline_run,
    create_pipeline_run_item,
    get_next_version_number,
    get_or_create_document,
    get_or_create_source,
)


def import_website_pages(
    session: Session,
    *,
    knowledge_base,
    request: WebsiteImportRequest,
) -> dict[str, object]:
    result = collect_website_imports(request)
    source = get_or_create_source(
        session,
        knowledge_base_id=knowledge_base.id,
        uri=request.sitemap_url or (request.urls[0] if request.urls else "website-import"),
        config_json={"kind": "website_import", "urls": request.urls, "sitemap_url": request.sitemap_url},
    )
    run = create_pipeline_run(
        session,
        knowledge_base_id=knowledge_base.id,
        source_id=source.id,
        run_type="website_import",
        config_snapshot_json={"source": "website_import", "max_pages": 25},
    )

    success_count = 0
    failure_count = len(result.failures)
    with TemporaryDirectory(prefix="ragrig-web-import-") as tmp:
        root = Path(tmp)
        for index, page in enumerate(result.pages, start=1):
            path = root / f"page-{index}.html"
            path.write_text(page.html, encoding="utf-8")
            document = None
            try:
                parser = _select_parser(path)
                parsed = parse_with_timeout(parser, path, timeout_seconds=30.0)
                document, _ = get_or_create_document(
                    session,
                    knowledge_base_id=knowledge_base.id,
                    source_id=source.id,
                    uri=page.source_url,
                    content_hash=parsed.content_hash,
                    mime_type=parsed.mime_type,
                    metadata_json={**parsed.metadata, "source_url": page.source_url, "title": page.title},
                )
                version = DocumentVersion(
                    document_id=document.id,
                    version_number=get_next_version_number(session, document_id=document.id),
                    content_hash=parsed.content_hash,
                    parser_name=parsed.parser_name,
                    parser_config_json={"plugin_id": "parser.html"},
                    extracted_text=parsed.extracted_text,
                    metadata_json={**parsed.metadata, "source_url": page.source_url, "title": page.title},
                )
                session.add(version)
                session.flush()
                create_pipeline_run_item(
                    session,
                    pipeline_run_id=run.id,
                    document_id=document.id,
                    status="success",
                    metadata_json={"source_url": page.source_url, "version_number": version.version_number},
                )
                success_count += 1
            except Exception as exc:
                failure_count += 1
                if document is None:
                    document, _ = get_or_create_document(
                        session,
                        knowledge_base_id=knowledge_base.id,
                        source_id=source.id,
                        uri=page.source_url,
                        content_hash="failed",
                        mime_type="text/html",
                        metadata_json={"failure_reason": str(exc), "source_url": page.source_url},
                    )
                create_pipeline_run_item(
                    session,
                    pipeline_run_id=run.id,
                    document_id=document.id,
                    status="failed",
                    error_message=str(exc),
                    metadata_json={"source_url": page.source_url},
                )

    for failure in result.failures:
        failed_document, _ = get_or_create_document(
            session,
            knowledge_base_id=knowledge_base.id,
            source_id=source.id,
            uri=failure.source_url,
            content_hash=f"failed:{failure.reason}",
            mime_type="text/html",
            metadata_json={"failure_reason": failure.reason, "source_url": failure.source_url},
        )
        create_pipeline_run_item(
            session,
            pipeline_run_id=run.id,
            document_id=failed_document.id,
            status="failed",
            error_message=failure.message,
            metadata_json={"source_url": failure.source_url, "failure_reason": failure.reason},
        )

    run.total_items = len(result.pages) + len(result.failures)
    run.success_count = success_count
    run.failure_count = failure_count
    run.status = "completed_with_failures" if failure_count else "completed"
    run.finished_at = datetime.now(timezone.utc)
    session.commit()
    return {
        "pipeline_run_id": str(run.id),
        "accepted_pages": success_count,
        "failed_pages": failure_count,
        "failures": [failure.__dict__ for failure in result.failures],
    }
```

- [ ] **Step 4: Wire API endpoint to service**

Replace the provisional website route body in `src/ragrig/main.py`:

```python
from ragrig.ingestion.web_import import WebsiteImportRequest
from ragrig.local_pilot.service import import_website_pages

result = import_website_pages(
    session,
    knowledge_base=kb,
    request=WebsiteImportRequest(urls=request.urls, sitemap_url=request.sitemap_url),
)
return JSONResponse(status_code=202, content=result)
```

- [ ] **Step 5: Verify persistence test**

```bash
uv run pytest tests/test_local_pilot_api.py::test_website_import_persists_pipeline_run -v
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add src/ragrig/local_pilot/service.py src/ragrig/main.py tests/test_local_pilot_api.py
git commit -m "feat: persist local pilot website imports"
```

## Task 5: Add Gemini Provider Health and Answer Smoke

**Files:**

- Modify: `src/ragrig/providers/cloud.py`
- Modify: `src/ragrig/providers/__init__.py`
- Modify: `src/ragrig/answer/provider.py`
- Modify: `pyproject.toml`
- Test: `tests/test_gemini_provider.py`

- [ ] **Step 1: Add failing Gemini provider tests**

Create `tests/test_gemini_provider.py`:

```python
from ragrig.providers import ProviderCapability
from ragrig.providers.cloud import GeminiProvider


class FakeGeminiModels:
    def __init__(self):
        self.calls = []

    def generate_content(self, *, model, contents):
        self.calls.append((model, contents))

        class Response:
            text = "Grounded answer [cit-1]"

        return Response()


class FakeGeminiClient:
    def __init__(self):
        self.models = FakeGeminiModels()


def test_gemini_provider_health_ready_with_client():
    provider = GeminiProvider(api_key="secret", model_name="gemini-2.5-flash", client=FakeGeminiClient())

    health = provider.health_check()

    assert health.status == "healthy"
    assert health.metrics["model"] == "gemini-2.5-flash"


def test_gemini_provider_chat_returns_openai_like_shape():
    provider = GeminiProvider(api_key="secret", model_name="gemini-2.5-flash", client=FakeGeminiClient())

    result = provider.chat([{"role": "user", "content": "Question with [cit-1] evidence"}])

    assert result["choices"][0]["message"]["content"] == "Grounded answer [cit-1]"
    assert ProviderCapability.CHAT in provider.metadata.capabilities
```

- [ ] **Step 2: Run tests and verify they fail**

```bash
uv run pytest tests/test_gemini_provider.py -v
```

Expected: fail because `GeminiProvider` does not exist.

- [ ] **Step 3: Add optional SDK dependency**

Use Google's current official Gemini SDK package, `google-genai`.

Modify `pyproject.toml` optional dependencies:

```toml
[project.optional-dependencies]
cloud-google = [
  "google-genai>=1.0.0",
]
```

Run:

```bash
uv lock
```

- [ ] **Step 4: Implement Gemini provider**

Add to `src/ragrig/providers/cloud.py`:

```python
import os


class GeminiProvider(BaseProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model_name: str = "gemini-2.5-flash",
        client: Any | None = None,
    ) -> None:
        self.metadata = GOOGLE_GEMINI_METADATA
        self._api_key = api_key or os.getenv("GEMINI_API_KEY")
        self._model_name = model_name
        self._client = client

    def _resolve_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ProviderError(
                "GEMINI_API_KEY is required for Gemini",
                code="missing_required_secret",
                retryable=False,
                details={"provider": "model.google_gemini", "secret": "GEMINI_API_KEY"},
            )
        try:
            from google import genai
        except Exception as exc:
            raise _optional_dependency_error(
                provider="model.google_gemini",
                dependencies=["google-genai"],
            ) from exc
        self._client = genai.Client(api_key=self._api_key)
        return self._client

    def health_check(self) -> ProviderHealth:
        try:
            self._resolve_client()
        except ProviderError as exc:
            return ProviderHealth(status="unavailable", detail=str(exc), metrics=exc.details)
        return ProviderHealth(
            status="healthy",
            detail="Gemini client is configured",
            metrics={"provider": "model.google_gemini", "model": self._model_name},
        )

    def chat(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        prompt = "\n\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages)
        response = self._resolve_client().models.generate_content(
            model=self._model_name,
            contents=prompt,
        )
        text = getattr(response, "text", "") or ""
        return {"choices": [{"message": {"content": text}}]}

    def generate(self, prompt: str) -> str:
        response = self._resolve_client().models.generate_content(
            model=self._model_name,
            contents=prompt,
        )
        return getattr(response, "text", "") or ""
```

Ensure `GOOGLE_GEMINI_METADATA` uses:

```python
required_secrets=["GEMINI_API_KEY"]
```

and capabilities include `CHAT` and `GENERATE`.

- [ ] **Step 5: Register Gemini live factory**

In `src/ragrig/providers/__init__.py`, import `GeminiProvider` and register:

```python
registry.register(
    GOOGLE_GEMINI_METADATA,
    lambda **config: GeminiProvider(
        api_key=config.get("api_key"),
        model_name=config.get("model_name", "gemini-2.5-flash"),
    ),
)
```

Keep Vertex AI and Bedrock registered through `create_cloud_stub_provider`.

- [ ] **Step 6: Allow answer provider config**

Modify `get_answer_provider` in `src/ragrig/answer/provider.py`:

```python
def get_answer_provider(
    provider_name: str,
    model: str | None = None,
    provider_config: dict[str, Any] | None = None,
) -> AnswerProvider:
    if provider_name == "deterministic-local":
        return DeterministicAnswerProvider()

    registry = get_provider_registry()
    config = dict(provider_config or {})
    if model is not None:
        config.setdefault("model_name", model)
    base = registry.get(provider_name, **config)
    ...
```

Then pass `provider_config` from the answer smoke endpoint in Task 6.

- [ ] **Step 7: Verify Gemini tests**

```bash
uv run pytest tests/test_gemini_provider.py -v
```

Expected: all tests pass without network access.

- [ ] **Step 8: Update supply-chain docs**

Add `google-genai`, `pypdf`, `python-docx`, and `httpx` to `docs/operations/dependency-inventory.md` with:

- package name
- reason
- default vs optional install
- upstream/project link
- live-network requirement, if any

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml uv.lock src/ragrig/providers src/ragrig/answer/provider.py tests/test_gemini_provider.py docs/operations/dependency-inventory.md
git commit -m "feat: add gemini local pilot provider smoke"
```

## Task 6: Add Local Pilot Health and Answer Smoke API

**Files:**

- Modify: `src/ragrig/local_pilot/schema.py`
- Modify: `src/ragrig/local_pilot/service.py`
- Modify: `src/ragrig/main.py`
- Test: `tests/test_local_pilot_api.py`

- [ ] **Step 1: Add failing smoke API test**

Append:

```python
def test_local_pilot_answer_smoke_reports_unavailable_without_secret(tmp_path: Path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'pilot.db'}")
    app = create_app(settings=settings)
    client = TestClient(app)

    response = client.post(
        "/local-pilot/answer-smoke",
        json={"provider": "model.google_gemini", "model": "gemini-2.5-flash"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "model.google_gemini"
    assert body["status"] in {"unavailable", "degraded"}
    assert "GEMINI_API_KEY" in body["detail"]
```

- [ ] **Step 2: Run and verify failure**

```bash
uv run pytest tests/test_local_pilot_api.py::test_local_pilot_answer_smoke_reports_unavailable_without_secret -v
```

Expected: fail with 404.

- [ ] **Step 3: Add schema**

Add to `src/ragrig/local_pilot/schema.py`:

```python
class LocalPilotAnswerSmokeRequest(BaseModel):
    provider: str
    model: str | None = None


class LocalPilotAnswerSmokeReport(BaseModel):
    provider: str
    model: str | None
    status: str
    detail: str
```

- [ ] **Step 4: Add service function**

Add to `src/ragrig/local_pilot/service.py`:

```python
from ragrig.answer.provider import get_answer_provider
from ragrig.answer.schema import EvidenceChunk


def run_answer_smoke(*, provider: str, model: str | None = None) -> dict[str, object]:
    evidence = [
        EvidenceChunk(
            citation_id="cit-1",
            document_uri="local-pilot://smoke",
            chunk_id="smoke",
            chunk_index=0,
            text="RAGRig Local Pilot verifies grounded answers with citations.",
            score=1.0,
            distance=0.0,
        )
    ]
    try:
        answer_provider = get_answer_provider(provider, model=model)
        answer, citation_ids = answer_provider.generate("What does Local Pilot verify?", evidence)
    except Exception as exc:
        return {"provider": provider, "model": model, "status": "unavailable", "detail": str(exc)}

    status = "healthy" if "cit-1" in citation_ids or "[cit-1]" in answer else "degraded"
    return {"provider": provider, "model": model, "status": status, "detail": answer[:240]}
```

- [ ] **Step 5: Add endpoint**

In `src/ragrig/main.py`:

```python
class LocalPilotAnswerSmokeApiRequest(BaseModel):
    provider: str
    model: str | None = None


@app.post("/local-pilot/answer-smoke", response_model=None)
def local_pilot_answer_smoke(request: LocalPilotAnswerSmokeApiRequest) -> dict[str, Any]:
    from ragrig.local_pilot.service import run_answer_smoke

    return run_answer_smoke(provider=request.provider, model=request.model)
```

- [ ] **Step 6: Verify smoke tests**

```bash
uv run pytest tests/test_local_pilot_api.py::test_local_pilot_answer_smoke_reports_unavailable_without_secret -v
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add src/ragrig/local_pilot src/ragrig/main.py tests/test_local_pilot_api.py
git commit -m "feat: add local pilot answer smoke api"
```

## Task 7: Add Web Console Local Pilot Wizard

**Files:**

- Modify: `src/ragrig/web_console.html`
- Modify: `src/ragrig/web_console.py` if a server-side summary helper is needed
- Test: `tests/test_web_console_local_pilot.py`

- [ ] **Step 1: Add failing HTML contract test**

Create `tests/test_web_console_local_pilot.py`:

```python
from pathlib import Path


def test_console_contains_local_pilot_wizard():
    html = Path("src/ragrig/web_console.html").read_text(encoding="utf-8")

    assert "Local Pilot" in html
    assert "data-local-pilot-wizard" in html
    assert "/local-pilot/status" in html
    assert "/knowledge-bases/" in html
    assert "/website-import" in html
    assert "/local-pilot/answer-smoke" in html
```

- [ ] **Step 2: Run and verify failure**

```bash
uv run pytest tests/test_web_console_local_pilot.py -v
```

Expected: fail because wizard markers do not exist.

- [ ] **Step 3: Add wizard markup**

In `src/ragrig/web_console.html`, add a panel near the top of the Overview content:

```html
<section class="panel" data-local-pilot-wizard>
  <div class="panel-head">
    <div>
      <h2>Local Pilot</h2>
      <p>Upload files or import a small docs URL set, then test retrieval and answers.</p>
    </div>
  </div>
  <div class="form-grid">
    <label>
      Knowledge base
      <input id="pilot-kb-name" value="local-pilot">
    </label>
    <label>
      Website URL / sitemap
      <input id="pilot-url" aria-label="Website URL or sitemap" value="">
    </label>
    <label>
      Model provider
      <select id="pilot-provider">
        <option value="deterministic-local">deterministic-local</option>
        <option value="model.ollama">Ollama</option>
        <option value="model.lm_studio">LM Studio</option>
        <option value="model.openai">OpenAI</option>
        <option value="model.openrouter">OpenRouter</option>
        <option value="model.google_gemini">Gemini</option>
      </select>
    </label>
  </div>
  <div class="actions">
    <button class="button" id="pilot-refresh-status">Check Pilot Status</button>
    <button class="button" id="pilot-import-url">Import URL</button>
    <button class="button" id="pilot-answer-smoke">Run Answer Smoke</button>
  </div>
  <pre id="pilot-output" class="code-output"></pre>
</section>
```

- [ ] **Step 4: Add JavaScript calls**

Add functions in the existing script block:

```javascript
async function refreshLocalPilotStatus() {
  const data = await fetchJson("/local-pilot/status");
  document.querySelector("#pilot-output").textContent = JSON.stringify(data, null, 2);
}

async function importPilotUrl() {
  const kb = document.querySelector("#pilot-kb-name").value || "local-pilot";
  const url = document.querySelector("#pilot-url").value;
  const data = await fetchJson(`/knowledge-bases/${encodeURIComponent(kb)}/website-import`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({urls: [url]}),
  });
  document.querySelector("#pilot-output").textContent = JSON.stringify(data, null, 2);
}

async function runPilotAnswerSmoke() {
  const provider = document.querySelector("#pilot-provider").value;
  const data = await fetchJson("/local-pilot/answer-smoke", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({provider}),
  });
  document.querySelector("#pilot-output").textContent = JSON.stringify(data, null, 2);
}

document.querySelector("#pilot-refresh-status")?.addEventListener("click", refreshLocalPilotStatus);
document.querySelector("#pilot-import-url")?.addEventListener("click", importPilotUrl);
document.querySelector("#pilot-answer-smoke")?.addEventListener("click", runPilotAnswerSmoke);
```

- [ ] **Step 5: Verify HTML test**

```bash
uv run pytest tests/test_web_console_local_pilot.py -v
```

Expected: pass.

- [ ] **Step 6: Run Web Console smoke**

```bash
make web-check
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add src/ragrig/web_console.html tests/test_web_console_local_pilot.py
git commit -m "feat: add local pilot console wizard"
```

## Task 8: Add End-to-End Local Pilot Smoke

**Files:**

- Create: `scripts/local_pilot_smoke.py`
- Modify: `Makefile`
- Test: `tests/test_local_pilot_api.py`

- [ ] **Step 1: Add script**

Create `scripts/local_pilot_smoke.py`:

```python
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from ragrig.main import create_app


def main() -> None:
    client = TestClient(create_app())
    status = client.get("/local-pilot/status")
    status.raise_for_status()
    smoke = client.post(
        "/local-pilot/answer-smoke",
        json={"provider": "deterministic-local"},
    )
    smoke.raise_for_status()
    print(json.dumps({"status": status.json(), "answer_smoke": smoke.json()}, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Add Make target**

Modify `Makefile`:

```make
.PHONY: local-pilot-smoke
local-pilot-smoke:
	uv run python -m scripts.local_pilot_smoke
```

- [ ] **Step 3: Run smoke**

```bash
make local-pilot-smoke
```

Expected: command prints JSON with `/local-pilot/status` and deterministic answer smoke results.

- [ ] **Step 4: Commit**

```bash
git add scripts/local_pilot_smoke.py Makefile
git commit -m "test: add local pilot smoke command"
```

## Task 9: Documentation and Supply-Chain Update

**Files:**

- Modify: `README.md`
- Modify: `README.zh-CN.md`
- Modify: `docs/specs/ragrig-local-pilot-spec.md`
- Modify: `docs/operations/dependency-inventory.md`
- Modify: `docs/operations/supply-chain.md`

- [ ] **Step 1: Update README quick start**

Add this under Quick Start in both READMEs:

```bash
make local-pilot-smoke
```

Describe that the full Web Console wizard is available at `/console` and that Gemini smoke requires `GEMINI_API_KEY`.

- [ ] **Step 2: Update Local Pilot spec**

In `docs/specs/ragrig-local-pilot-spec.md`, add an implementation status section:

```markdown
## Implementation Status

- PDF/DOCX parser support: implemented for text extraction boundaries.
- Website import: implemented for single URL, sitemap, and explicit URL list with a 25-page cap.
- Gemini: implemented with `google-genai` health check and answer smoke.
- Web Console: Local Pilot Wizard implemented for status, URL import, and answer smoke.
```

- [ ] **Step 3: Update supply-chain docs**

Record:

- `pypdf`: PDF text extraction, default dependency, no network.
- `python-docx`: DOCX text extraction, default dependency, no network.
- `httpx`: URL/sitemap fetch, default dependency, network only during website import.
- `google-genai`: Gemini API, optional `cloud-google`, network only during explicit live smoke.

- [ ] **Step 4: Run doc checks**

```bash
git diff --check
rg -n "T[B]D|T[O]DO|F[I]XME|Open Questions" README.md README.zh-CN.md docs/specs/ragrig-local-pilot-spec.md docs/operations
```

Expected: `git diff --check` exits 0; `rg` returns no matches.

- [ ] **Step 5: Commit**

```bash
git add README.md README.zh-CN.md docs/specs/ragrig-local-pilot-spec.md docs/operations/dependency-inventory.md docs/operations/supply-chain.md
git commit -m "docs: update local pilot usage and supply chain"
```

## Task 10: Final Verification and PR

**Files:**

- No planned source changes.

- [ ] **Step 1: Run focused tests**

```bash
uv run pytest \
  tests/test_pdf_docx_parsers.py \
  tests/test_local_pilot_web_import.py \
  tests/test_gemini_provider.py \
  tests/test_local_pilot_api.py \
  tests/test_web_console_local_pilot.py \
  -v
```

Expected: pass.

- [ ] **Step 2: Run default checks**

```bash
make lint
make test
make coverage
make web-check
make dependency-inventory
```

Expected: pass. Coverage must continue to satisfy the core 100% policy.

- [ ] **Step 3: Run local pilot smoke**

```bash
make local-pilot-smoke
```

Expected: pass with deterministic provider. Gemini live smoke is not required unless `GEMINI_API_KEY` is explicitly configured.

- [ ] **Step 4: Inspect git status**

```bash
git status --short --branch
```

Expected: clean branch ahead of `origin/main`.

- [ ] **Step 5: Push and open PR**

```bash
git push -u origin codex/local-pilot-implementation
gh pr create \
  --title "Implement RAGRig Local Pilot vertical slice" \
  --body "Implements the Local Pilot roadmap milestone: PDF/DOCX upload, lightweight website import, Gemini health and answer smoke, Web Console wizard, and local pilot smoke verification."
```

## Self-Review

Spec coverage:

- Document upload: Tasks 1, 3, 7, 8, 9.
- Website import: Tasks 2, 4, 7, 8, 9.
- Model support and Gemini smoke: Tasks 5, 6, 7, 8, 9.
- Web Console hybrid surface: Task 7.
- Health and failure states: Tasks 2, 4, 5, 6, 7.
- Supply-chain documentation: Tasks 5 and 9.
- Verification: Task 10.

Known sequencing constraints:

- Task 4 depends on Task 2 and Task 3.
- Task 6 depends on Task 5.
- Task 7 depends on Tasks 3, 4, and 6.
- Task 8 depends on Tasks 3 and 6.

The plan keeps Vertex AI and Bedrock as provider catalog/roadmap entries and does not promote them to live Local Pilot blockers.
