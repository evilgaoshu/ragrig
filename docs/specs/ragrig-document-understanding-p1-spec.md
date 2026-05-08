# RAGRig DocumentUnderstanding P1 Spec

Date: 2026-05-08
Status: Implemented

## 1. Goal

Implement single-document DocumentUnderstanding capability: for a specified
`document_version`, generate traceable, reproducible, and evaluable structured
understanding results including summary, table of contents, key entities, key
claims, and limitations/risk notes.

## 2. Scope

### In Scope (P1)

- `DocumentUnderstanding` data model with DB persistence, linked to
  `document_version_id`, `profile_id`, provider/model, input hash, status,
  `result_json`, error, and timestamps.
- Structured result schema: `summary`, `table_of_contents`, `entities`,
  `key_claims`, `limitations`, `source_spans`.
- Service layer: read `extracted_text`, select provider/profile, generate
  understanding, persist result.
- Deterministic/fake test provider for CI and local validation.
- API endpoints:
  - `POST /document-versions/{id}/understand`
  - `GET /document-versions/{id}/understanding`
- Web Console document preview panel shows understanding state:
  - not_generated (real empty state)
  - processing / failed / completed
  - Summary, TOC, entities, key claims when available.
- Alembic migration for `document_understandings` table.
- 100% test coverage for `ragrig.understanding` module.

### Out of Scope

- Cross-document term glossary, synonym mapping, concept deduplication.
- Knowledge map / relationship graph visualization.
- Background queue or distributed task runner.
- Cloud LLM live smoke tests (cloud providers remain optional/manual).

## 3. Data Model

### SQLAlchemy

```python
class DocumentUnderstanding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_understandings"
    document_version_id: Mapped[uuid.UUID]
    profile_id: Mapped[str]
    provider: Mapped[str]
    model: Mapped[str]
    input_hash: Mapped[str]
    status: Mapped[str]  # processing | completed | failed
    result_json: Mapped[dict[str, Any]]
    error: Mapped[str | None]
```

Unique constraint on `(document_version_id, profile_id)`.

### Result Schema (Pydantic)

```python
class UnderstandingResult(BaseModel):
    summary: str | None
    table_of_contents: list[TocEntry]
    entities: list[Entity]
    key_claims: list[KeyClaim]
    limitations: list[str]
    source_spans: list[SourceSpan]
```

## 4. Provider Architecture

- `deterministic-local`: Returns structured output derived from text statistics
  (heading extraction, capitalized word entities, word/line counts). No LLM
  call. Used for CI and local validation.
- `LLMUnderstandingProvider`: Wraps any `BaseProvider` with `chat` or `generate`
  capability. Sends a structured JSON prompt, parses the response (including
  markdown code block stripping), and validates against `UnderstandingResult`.
- Provider selection is configurable per API call via `provider` field.

## 5. API Contract

### POST /document-versions/{id}/understand

Request body (optional):
```json
{
  "provider": "deterministic-local",
  "model": null,
  "profile_id": "*.understand.default"
}
```

Response (200 on success):
```json
{
  "id": "...",
  "document_version_id": "...",
  "profile_id": "*.understand.default",
  "provider": "deterministic-local",
  "model": "",
  "status": "completed",
  "result": { "summary": "...", ... },
  "error": null,
  "created_at": "...",
  "updated_at": "..."
}
```

Errors:
- 404: document version not found
- 503: provider unavailable or LLM returned invalid JSON

### GET /document-versions/{id}/understanding

Returns the latest understanding record for the version, or 404 if none exists.

## 6. Idempotency and Versioning

- `input_hash` = SHA256(profile_id + provider + model + extracted_text).
- If an existing record has the same `(document_version_id, profile_id)` and
  matching `input_hash`, the existing record is returned without re-processing.
- If the hash differs (text changed), the existing record is overwritten.
- This prevents duplicate dirty data while allowing re-generation after edits.

## 7. Web Console Behavior

The Document / Chunk Preview panel now fetches
`/document-versions/{id}/understanding` and renders:

- **not_generated**: pill + "No understanding result yet. Run POST ... to generate."
- **processing**: pill + "Understanding is being generated..."
- **failed**: pill + error message (no secret leakage)
- **completed**: provider/model/profile metadata, summary card, TOC card,
  entities card, key claims card.

## 8. Verification Commands

```bash
# Lint
make lint

# Tests
make test

# Coverage (100% gate)
make coverage

# Web console checks
make web-check

# Local validation with deterministic provider
# 1. Ingest fixture data
make ingest-local
# 2. Generate understanding for a version (requires version UUID from DB)
#    curl -X POST http://localhost:8000/document-versions/{id}/understand \
#         -H "Content-Type: application/json" \
#         -d '{"provider":"deterministic-local"}'
# 3. View result
#    curl http://localhost:8000/document-versions/{id}/understanding
```

## 9. Risk and Limitations

- Synchronous execution: large documents or slow LLMs may timeout. Documented
  as a known limitation; no background queue in P1.
- Real local LLM runtime (Ollama, LM Studio) not verified in CI; only the
  deterministic provider is exercised automatically.
- Cloud providers require optional dependencies and secrets; they are supported
  via the generic `LLMUnderstandingProvider` but not smoke-tested in CI.
