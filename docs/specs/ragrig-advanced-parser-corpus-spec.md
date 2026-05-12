# Advanced Parser Corpus SPEC

**Version**: 1.0.0
**Status**: Draft
**Author**: RAGRig Dev Team
**Created**: 2026-05-12

## 1. Purpose

Define a reproducible fixture corpus and quality gate for PDF, DOCX, PPTX, and XLSX document parsing with OCR fallback, degradation strategies, and artifact integrity verification. This enables safe iteration on `parser.advanced_documents`.

## 2. Supported Formats

| Format | Extension | MIME Type | Fixture | Parser ID | Status |
|--------|-----------|-----------|---------|-----------|--------|
| PDF | .pdf | application/pdf | sample.pdf | parser.advanced_documents | preview |
| DOCX | .docx | application/vnd.openxmlformats-officedocument.wordprocessingml.document | sample.docx | parser.advanced_documents | preview |
| PPTX | .pptx | application/vnd.openxmlformats-officedocument.presentationml.presentation | sample.pptx | parser.advanced_documents | preview |
| XLSX | .xlsx | application/vnd.openxmlformats-officedocument.spreadsheetml.sheet | sample.xlsx | parser.advanced_documents | preview |

## 3. Fixture Source

All fixtures are generated programmatically by `scripts/generate_advanced_fixtures.py` using only Python standard library modules (no external dependencies). They reside in `tests/fixtures/advanced_documents/`.

### 3.1 Fixture Generation

- PDF: Hand-crafted minimal PDF with a single page and text content
- DOCX: OOXML package (ZIP) with minimal `word/document.xml`
- PPTX: OOXML package with 2 slides
- XLSX: OOXML package with 1 worksheet containing header and data row

### 3.2 Reproducibility

Fixtures are deterministic — same input text always produces identical binary output. Each fixture is registered in the ArtifactSchema by SHA-256 content hash.

## 4. Parser Adapter Contract

```python
class AdvancedParserAdapter(ABC):
    parser_name: str

    @abstractmethod
    def can_parse(self, path: Path) -> bool: ...
    @abstractmethod
    def parse(self, path: Path) -> AdvancedParseResult: ...
    @abstractmethod
    def check_dependencies(self) -> bool: ...
```

### 4.1 AdvancedParseResult Schema

| Field | Type | Description |
|-------|------|-------------|
| format | str | File format extension (pdf, docx, pptx, xlsx) |
| fixture_id | str | Fixture filename without extension |
| parser | str | Adapter name that processed the file |
| status | ParserStatus | healthy, degraded, skip, failure |
| text_length | int | Number of characters extracted |
| table_count | int | Number of tables detected |
| page_or_slide_count | int | Number of pages or slides |
| degraded_reason | str or null | Why status is not healthy |
| extracted_text | str | Full extracted text content |
| metadata | dict | Adapter-specific metadata |

### 4.2 ParserStatus Enum

- `healthy` — Full parse succeeded with all features
- `degraded` — Parse completed but with limitations (OCR fallback, best-effort)
- `skip` — Parser not available (missing dependencies)
- `failure` — Parser encountered an error

### 4.3 DegradedReason Enum

| Reason | Meaning |
|--------|---------|
| missing_dependency | Required library not installed |
| corrupt_artifact | Fixture file is empty, truncated, or unreadable |
| stale_artifact | Fixture content hash does not match artifact schema record |
| parser_timeout | Parser exceeded execution time limit |
| parser_error | Parser raised an unexpected exception |
| ocr_fallback | Primary parser returned empty text, OCR attempted |
| unsupported_format | No adapter registered for this file format |

## 5. OCR Fallback

The `OcrFallbackHandler` manages OCR orchestration:

1. If OCR is **disabled** and primary parser returns empty text, result is marked `degraded` with reason `ocr_fallback` and metadata `ocr_available=False`
2. If OCR is **enabled** but `pytesseract`/`Pillow` are not installed, result is marked `degraded` with `ocr_available=False`
3. If OCR is **enabled** and dependencies present, OCR is applied and result is marked `degraded` with `ocr_applied=True`

No real cloud OCR is performed. OCR invocation is a best-effort pass only.

## 6. Artifact Schema

The `ArtifactSchema` tracks fixture metadata:

```json
{
  "version": "1.0.0",
  "artifacts": [
    {
      "fixture_id": "sample",
      "format": "pdf",
      "path": "tests/fixtures/advanced_documents/sample.pdf",
      "content_hash": "sha256hex...",
      "size_bytes": 549,
      "created_at": "2026-05-12T08:00:00Z"
    }
  ],
  "generated_at": "2026-05-12T08:00:00Z"
}
```

## 7. Corpus Check (`make advanced-parser-corpus-check`)

### 7.1 Entry Point

```bash
python -m scripts.advanced_parser_corpus_check \
    --json-output docs/operations/artifacts/advanced-parser-corpus.json \
    --markdown-output docs/operations/artifacts/advanced-parser-corpus.md
```

### 7.2 Output Format (JSON)

```json
{
  "generated_at": "2026-05-12T08:00:00Z",
  "total_fixtures": 4,
  "healthy": 0,
  "degraded": 0,
  "skipped": 4,
  "failed": 0,
  "results": [
    {
      "format": "pdf",
      "fixture_id": "sample",
      "parser": "advanced.docling",
      "status": "skip",
      "text_length": 0,
      "table_count": 0,
      "page_or_slide_count": 0,
      "degraded_reason": "missing_dependency"
    }
  ],
  "report_path": null
}
```

### 7.3 Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All fixtures healthy or skipped (missing optional deps) |
| 1 | Any fixture degraded or failed |
| 2 | Corrupt artifact detected |

## 8. Quality Gates

| Gate | Command | Required |
|------|---------|----------|
| Lint | `make lint` | Pass |
| Test | `make test` | Pass |
| Coverage | `make coverage` | >= 90% |
| Web Check | `make web-check` | Pass |
| Corpus Check | `make advanced-parser-corpus-check` | Exit 0 |

## 9. Copyright and Secret Boundaries

- All fixtures contain only synthetic text (e.g. "Hello from RAGRig PDF fixture")
- No real documents, trademarks, or copyrighted content
- Fixtures are generated from code, not derived from external sources
- Secret-like patterns (API keys, tokens, passwords) are explicitly avoided in fixture content
- The `sanitize_text_summary` pipeline ensures metadata never contains raw secret values
- Parser output never includes raw prompts, credentials, or personal identifiable information

## 10. Provider Adapter Stubs

| Adapter | Parser Name | Library | Status |
|---------|-------------|---------|--------|
| DoclingAdapter | advanced.docling | docling | stub |
| MinerUAdapter | advanced.mineru | magic_pdf | stub |
| UnstructuredAdapter | advanced.unstructured | unstructured | stub |

Each adapter:
- Implements the `AdvancedParserAdapter` abstract contract
- Checks dependency availability via `check_dependencies()`
- Returns `skip` with `missing_dependency` reason when library not installed
- Returns `failure` with `parser_error` reason on parse exceptions
- Is ready for real implementation once the respective library is added to `doc-parsers` extras

## 11. Out of Scope

- Real cloud OCR (Google Vision, AWS Textract, Azure AI)
- Large binary fixtures (>100 KB)
- Heavyweight parser library installation in default CI
- Changes to existing Markdown/Text ingestion main path
