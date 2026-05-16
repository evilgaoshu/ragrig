# RAGRig ProcessingProfile, SupportedFormat, and Document Understanding Spec

Date: 2026-05-08
Status: P0 implemented (EVI-54, PR #33) — ProcessingProfile core, APIs, Web Console matrix

## 1. Goal

Define the data models, visualization strategy, and phased rollout plan for four
connected capabilities that move RAGRig beyond simple mime-type-based parsing:

1. **ProcessingProfile** — a file-type × task-type two-dimensional pipeline matrix that
   enables fine-grained LLM-assisted processing per format and operation.
2. **SupportedFormat** — a platform-level file format registry that makes format
   support explicit, queryable, and enforceable at upload time.
3. **Browser File Upload** — a Web Console upload path that validates formats against
   the registry, rejects unsupported files, and triggers the ingestion pipeline.
4. **Document Understanding** — LLM-powered document comprehension beyond vector
   search, including structured summaries, tables of contents, entity extraction,
   cross-document term glossaries, and knowledge maps.

All four capabilities are pure documentation in this issue. No code changes are
delivered. Implementation will happen in follow-up issues once this spec is accepted.

## 2. Current State

### 2.1 Parser Selection Today

The current parser selection in `src/ragrig/ingestion/pipeline.py` (`_select_parser`)
is a hardcoded function that checks file extensions:

```python
def _select_parser(path: Path):
    if path.suffix.lower() in {".md", ".markdown"}:
        return MarkdownParser()
    return PlainTextParser()
```

Each parser declares a `mime_type` attribute (e.g. `text/plain`, `text/markdown`), but
there is no:

- parser registry that maps extensions or MIME types to parsers
- abstraction layer that selects processing behavior per task type
- notion of LLM-assisted cleaning, correction, or summarization profiles
- pluggable profile override per file type × task combination

### 2.2 Existing Infrastructure We Can Build On

- `docs/specs/` contains 20+ spec files with a consistent naming and structure pattern
- The Web Console (`GET /console`) serves as an HTML-based operator workbench
- The plugin registry in `src/ragrig/plugins/` demonstrates contract-first, manifest-based
  registration with discoverability and readiness reporting
- `POST /plugins/{plugin_id}/validate-config` shows a working config validation pattern
- The `SupportedFormat` concept is partially implicit in the parser code and plugin manifests,
  but lacks a centralized, queryable registry

## 3. ProcessingProfile System

### 3.1 Concept

A ProcessingProfile defines how RAGRig should process a specific combination of file type
and task. Instead of a single "parse this file" codepath, every file goes through a
two-dimensional dispatch:

```
              correct   clean    chunk    summarize   understand   ...
.docx         P1        P2       P3       P4          P5
.xlsx         P6        P7       P8       P9          P10
.md           P11       P12      P13      P14         P15
.pdf          P16       P17      P18      P19         P20
.txt          P21       P22      P23      P24         P25
.ppt(x)       P26       P27      P28      P29         P30
.csv          P31       P32      P33      P34         P35
.html         P36       P37      P38      P39         P40
```

Each cell in this matrix contains a ProcessingProfile that tells the pipeline engine
exactly how to execute that operation for that file type.

### 3.2 Data Model

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TaskType(str, Enum):
    """Processing task types that a profile can target."""
    CORRECT = "correct"         # LLM-assisted error correction (OCR errors, formatting)
    CLEAN = "clean"             # Normalize whitespace, remove boilerplate, redact PII
    CHUNK = "chunk"             # Split content into retrievable chunks
    SUMMARIZE = "summarize"     # Generate structured summaries
    UNDERSTAND = "understand"   # Extract structure: TOC, entities, key claims
    EMBED = "embed"             # Generate vector embeddings
    CLASSIFY = "classify"       # Classify document type, language, topic
    TRANSLATE = "translate"     # Translate content to a target language
    EXTRACT = "extract"         # Extract structured fields (tables, key-value pairs)


class ProfileStatus(str, Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    EXPERIMENTAL = "experimental"


class LLMProvider(str, Enum):
    DETERMINISTIC = "deterministic-local"   # No LLM, pure local code
    OLLAMA = "ollama"
    LM_STUDIO = "lm_studio"
    OPENAI_COMPATIBLE = "openai_compatible"  # vLLM, Xinference, llama.cpp, LocalAI
    OPENAI = "openai"
    VERTEX_AI = "vertex_ai"
    BEDROCK = "bedrock"
    AZURE_OPENAI = "azure_openai"
    OPENROUTER = "openrouter"
    COHERE = "cohere"
    JINA = "jina"
    ANTHROPIC = "anthropic"


class OutputFormat(str, Enum):
    TEXT = "text"
    JSON = "json"
    MARKDOWN = "markdown"
    YAML = "yaml"


@dataclass(frozen=True)
class ProcessingProfile:
    """A processing profile for a specific file-type × task-type combination."""

    profile_id: str
    """Unique identifier, e.g. 'docx.correct.default', 'pdf.summarize.v1'."""

    extension: str
    """Target file extension, e.g. '.docx', '.pdf', '.md'. Use '*' for catch-all."""

    task_type: TaskType
    """The processing task this profile handles."""

    display_name: str
    """Human-readable name for UI."""

    description: str
    """What this profile does and when to use it."""

    llm_provider: LLMProvider
    """Which LLM provider to use. DETERMINISTIC means no LLM call."""

    model_id: str | None = None
    """Provider-specific model identifier, e.g. 'gpt-4o', 'llama3.1:8b'."""

    system_prompt: str | None = None
    """System prompt template for LLM-assisted tasks."""

    user_prompt_template: str | None = None
    """User prompt template. Supports {content}, {extension}, {metadata} placeholders."""

    output_format: OutputFormat = OutputFormat.JSON
    """Expected output format from the LLM."""

    output_schema: dict[str, Any] | None = None
    """JSON Schema for structured output validation (when output_format is JSON)."""

    temperature: float = 0.0
    """LLM temperature. 0.0 means deterministic output."""

    max_tokens: int | None = None
    """Maximum output tokens."""

    max_input_chars: int | None = None
    """Maximum input characters before truncation or chunked processing."""

    fallback_profile_id: str | None = None
    """Fallback profile when this one is unavailable (e.g. LLM not reachable)."""

    status: ProfileStatus = ProfileStatus.ACTIVE

    tags: list[str] = field(default_factory=list)
    """Tags for filtering and discovery, e.g. ['fast', 'accurate', 'pii-safe']."""

    created_at: str = ""
    updated_at: str = ""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Extension point for custom metadata."""
```

### 3.3 Default Profile Strategy

The system ships with a **default profile per task type** that applies to all extensions.
Individual extension-task combinations then override specific cells.

Default profiles (all use `DETERMINISTIC` or a configurable local LLM):

| Profile ID | Task | Extension | LLM | Description |
|---|---|---|---|---|
| `*.correct.default` | correct | * | deterministic | No-op; passes content through unchanged |
| `*.clean.default` | clean | * | deterministic | Normalize whitespace, strip trailing blank lines |
| `*.chunk.default` | chunk | * | deterministic | Character-window chunking (existing `chunker.character_window`) |
| `*.summarize.default` | summarize | * | configurable | Basic LLM summary prompt |
| `*.understand.default` | understand | * | configurable | Basic structure extraction prompt |
| `*.embed.default` | embed | * | deterministic | Use the configured embedding provider |

Per-extension overrides can then be registered to provide specialized handling:

| Profile ID | Task | Extension | LLM | Description |
|---|---|---|---|---|
| `pdf.correct.v1` | correct | .pdf | configurable | OCR error correction with layout-aware prompt |
| `docx.clean.v1` | clean | .docx | deterministic | Strip Word-specific boilerplate, track-changes artifacts |
| `xlsx.chunk.v1` | chunk | .xlsx | configurable | Table-aware chunking with row/column semantics |
| `md.summarize.v1` | summarize | .md | configurable | Heading-aware summary generation |

### 3.4 Profile Resolution Algorithm

When the pipeline engine needs a profile for `(extension, task_type)`:

1. Look up exact match: `{extension}.{task_type}` with `status=active`.
2. If not found, look up wildcard: `*.{task_type}` with `status=active`.
3. If still not found, use a hardcoded reasonable default (no-op for correct/clean,
   character-window for chunk, etc.).
4. If the selected profile has a `fallback_profile_id` and its LLM provider is
   unavailable, resolve the fallback profile recursively (with a depth limit of 3).
5. Cache the resolved profile for the pipeline run duration.

This ensures that:
- New file types work immediately through wildcard defaults.
- Specialized profiles are opt-in overrides.
- LLM unavailability degrades gracefully.

### 3.5 Two-Dimensional Matrix Visualization

The Web Console will include a **Processing Profile Matrix** view that renders the
extension × task_type grid as an interactive table.

#### Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│  Processing Profile Matrix                           [+ Add Profile] │
├──────────┬──────────┬──────────┬──────────┬──────────┬──────────────┤
│          │ correct  │ clean    │ chunk    │ summarize│ understand   │
├──────────┼──────────┼──────────┼──────────┼──────────┼──────────────┤
│ .docx    │ default  │ docx.cl… │ default  │ default  │ default      │
│          │ ○ det    │ ● ollama │ ○ det    │ ○ det    │ ○ det        │
├──────────┼──────────┼──────────┼──────────┼──────────┼──────────────┤
│ .xlsx    │ default  │ default  │ xlsx.ch… │ default  │ default      │
│          │ ○ det    │ ○ det    │ ● ollama │ ○ det    │ ○ det        │
├──────────┼──────────┼──────────┼──────────┼──────────┼──────────────┤
│ .md      │ default  │ default  │ default  │ md.summ… │ default      │
│          │ ○ det    │ ○ det    │ ○ det    │ ● lm_st… │ ○ det        │
├──────────┼──────────┼──────────┼──────────┼──────────┼──────────────┤
│ .pdf     │ pdf.cor… │ default  │ default  │ default  │ default      │
│          │ ● ollama │ ○ det    │ ○ det    │ ○ det    │ ○ det        │
└──────────┴──────────┴──────────┴──────────┴──────────┴──────────────┘

  ● = LLM-assisted   ○ = Deterministic (no LLM)
```

#### Interaction Design

- **Read mode:** Each cell shows the profile name (or "default") and an LLM/deterministic
  indicator. Clicking a cell opens a detail panel.
- **Edit mode:** Clicking a cell opens an inline editor or side panel showing the full
  profile data model. Operators can change the LLM provider, system prompt, temperature,
  and fallback.
- **Add profile:** The "+ Add Profile" button opens a form pre-filled with the selected
  extension and task type.
- **Filtering:** Tabs or chips across the top let operators filter by task type
  ("Show all", "LLM-assisted only", "summarize tasks", etc.).
- **Color coding:**
  - Green border: active profile with explicit override
  - Gray: inherited from wildcard default
  - Amber: experimental status
  - Red outline: profile's LLM provider is currently unreachable
- **Hover tooltip** shows the profile's LLM provider, model, temperature, and fallback.

#### Technical Implementation Notes

- The matrix view is a standard HTML table rendered server-side in the Web Console, with
  minimal JavaScript for inline editing and filtering.
- The backend exposes profiles through `GET /profiles` and `GET /profiles/{profile_id}`.
- Profile mutations (`POST`, `PUT`, `DELETE`) land in a separate issue with DB-backed
  persistence. In the initial read-only version, profiles are loaded from YAML/JSON
  fixture files.
- The matrix is computed on the server: the backend returns a flat list of profiles plus
  a list of known extensions and task types; the browser renders the grid.
- No heavy frontend framework required — the existing Web Console's vanilla HTML/CSS/JS
  approach is sufficient.

### 3.6 API Contract

```
GET /profiles
  Query params: ?extension=.docx&task_type=summarize&status=active
  Returns: list of ProcessingProfile objects

GET /profiles/{profile_id}
  Returns: single ProcessingProfile

GET /profiles/matrix
  Returns: {
    extensions: [".docx", ".xlsx", ".md", ".pdf", ...],
    task_types: ["correct", "clean", "chunk", "summarize", ...],
    cells: {
      ".docx.correct": { profile_id: "*.correct.default", is_default: true, ... },
      ".docx.clean":   { profile_id: "docx.clean.v1", is_default: false, ... },
      ...
    }
  }
```

## 4. SupportedFormat Registry

### 4.1 Concept

A centralized, queryable registry of every file format RAGRig can process. This
registry answers the question "Can RAGRig handle this file?" before any pipeline
code runs, and it drives the browser upload accept/reject logic.

### 4.2 Data Model

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FormatStatus(str, Enum):
    SUPPORTED = "supported"     # Fully implemented, tested, production-ready
    PREVIEW = "preview"         # Partially implemented, opt-in, may have limitations
    PLANNED = "planned"         # On the roadmap, not yet implemented


@dataclass(frozen=True)
class SupportedFormat:
    """A file format that RAGRig knows how to process."""

    extension: str
    """File extension including dot, e.g. '.docx', '.pdf', '.md'. Must be lowercase."""

    mime_type: str
    """Standard MIME type, e.g. 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'."""

    display_name: str
    """Human-readable format name, e.g. 'Microsoft Word (.docx)'."""

    parser_id: str
    """Plugin ID of the parser that handles this format, e.g. 'parser.markdown'."""

    default_profile_id: str | None = None
    """Default ProcessingProfile ID for this format, e.g. 'docx.clean.v1'.
    When None, the wildcard default is used."""

    status: FormatStatus = FormatStatus.SUPPORTED
    """Current implementation status."""

    max_file_size_mb: int = 50
    """Maximum recommended file size in megabytes."""

    capabilities: list[str] = field(default_factory=list)
    """What this format supports: ['parse', 'chunk', 'embed', 'ocr']."""

    limitations: str | None = None
    """Known limitations, displayed to users."""

    docs_reference: str | None = None
    """Link to documentation for this format's processing pipeline."""

    metadata: dict[str, Any] = field(default_factory=dict)
```

### 4.3 Initial Registry

The initial registry entries shipped as a YAML fixture (`profiles/supported_formats.yaml`):

| Extension | MIME Type | Parser | Status | Notes |
|---|---|---|---|---|
| `.md` | `text/markdown` | `parser.markdown` | supported | Full pipeline |
| `.markdown` | `text/markdown` | `parser.markdown` | supported | Alias for .md |
| `.txt` | `text/plain` | `parser.text` | supported | Full pipeline |
| `.text` | `text/plain` | `parser.text` | supported | Alias for .txt |
| `.rst` | `text/x-rst` | `parser.text` | preview | Parsed as plain text, no RST structure |
| `.csv` | `text/csv` | `parser.text` | preview | Parsed as plain text, no table awareness |
| `.json` | `application/json` | `parser.text` | preview | Parsed as plain text |
| `.xml` | `application/xml` | `parser.text` | preview | Parsed as plain text |
| `.html` | `text/html` | `parser.text` | preview | Parsed as plain text, tags stripped |
| `.pdf` | `application/pdf` | `parser.pdf` | planned | Requires PDF parser plugin |
| `.docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | `parser.advanced_documents` | planned | Requires DOCX parser |
| `.xlsx` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` | `parser.advanced_documents` | planned | Requires XLSX parser |
| `.pptx` | `application/vnd.openxmlformats-officedocument.presentationml.presentation` | `parser.advanced_documents` | planned | Requires PPTX parser |
| `.doc` | `application/msword` | `parser.advanced_documents` | planned | Legacy format |
| `.xls` | `application/vnd.ms-excel` | `parser.advanced_documents` | planned | Legacy format |
| `.ppt` | `application/vnd.ms-powerpoint` | `parser.advanced_documents` | planned | Legacy format |

### 4.4 API Contract

```
GET /supported-formats
  Query params: ?status=supported&extension=.md
  Returns: list of SupportedFormat objects

GET /supported-formats/check?extension=.docx
  Returns: {
    extension: ".docx",
    supported: true,
    status: "planned",
    parser_id: "parser.advanced_documents",
    message: "DOCX support is planned. Currently .md and .txt are fully supported."
  }
```

### 4.5 Upload-Time Format Matching

When a file is uploaded (see Section 5), the system must:

1. Extract the file extension (lowercase, including the dot).
2. Look up the extension in the SupportedFormat registry.
3. If no entry exists or the status is `planned` with no parser available:
   - Reject the upload with HTTP 415 Unsupported Media Type.
   - Return a JSON error: `{ "error": "unsupported_format", "extension": ".xyz", "message": "File format .xyz is not supported. Supported formats: .md, .txt." }`
4. If the entry is `preview`:
   - Accept the upload but show a warning in the UI.
   - Record the `preview` status in the pipeline run item metadata.
5. If the entry is `supported`:
   - Accept the upload normally.

This logic must be applied server-side in the upload endpoint. The browser-side file
picker's `accept` attribute is a convenience hint only; it must not be relied upon
for security.

## 5. Browser File Upload

### 5.1 Concept

The Web Console must support uploading files directly from the browser into a knowledge
base, triggering the ingestion pipeline. This replaces the current CLI-only ingestion
path (`make ingest-local`) for interactive use.

### 5.2 UX Flow

```
┌──────────────────────────────────────────────────────────────┐
│  Upload to Knowledge Base: "team-docs"                       │
│                                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │                                                         │ │
│  │            Drag and drop files here                      │ │
│  │                      or                                  │ │
│  │               [ Choose Files ]                           │ │
│  │                                                         │ │
│  │   Accepted: .md, .markdown, .txt, .text                  │ │
│  │   Preview: .csv, .json, .html, .xml, .rst               │ │
│  │                                                         │ │
│  └─────────────────────────────────────────────────────────┘ │
│                                                              │
│  Selected files:                                             │
│  ┌──────────────────────────────────────────────────────────┐│
│  │ 📄 guide.md          12 KB  ✅ Ready                    ││
│  │ 📄 report.txt         8 KB  ✅ Ready                    ││
│  │ ❌ photo.jpg          2 MB  🚫 Unsupported format        ││
│  │ ⚠️ data.csv          45 KB  ⚠️ Preview — parsed as text  ││
│  └──────────────────────────────────────────────────────────┘│
│                                                              │
│  [ Cancel ]                              [ Upload & Ingest ] │
└──────────────────────────────────────────────────────────────┘
```

#### States

| State | Trigger | UI Behavior |
|---|---|---|
| Idle | No files selected | Drop zone shown, upload button disabled |
| Files selected | User drops or selects files | File list shown with per-file validation status |
| Validation failed | Unsupported format detected | Red error on the file, cannot proceed |
| Warning | Preview-format files | Amber warning, can proceed |
| Ready | All files valid | Upload button enabled |
| Uploading | Upload in progress | Progress bar, cancel button |
| Success | Upload complete | Redirect to pipeline run detail |
| Error | Upload failed | Error message with retry option |

### 5.3 Backend API Design

```
POST /knowledge-bases/{kb_name}/upload
  Content-Type: multipart/form-data
  Body:
    - files: one or more file parts (max 50 MB each, max 10 files per request)
  Response 202:
    {
      "pipeline_run_id": "...",
      "accepted_files": 3,
      "rejected_files": 1,
      "rejections": [
        {
          "filename": "photo.jpg",
          "extension": ".jpg",
          "reason": "unsupported_format",
          "message": "File format .jpg is not supported."
        }
      ],
      "warnings": [
        {
          "filename": "data.csv",
          "extension": ".csv",
          "status": "preview",
          "message": "CSV is in preview status — content will be parsed as plain text."
        }
      ]
    }
  Response 400: Invalid request (no files, KB not found)
  Response 413: File too large
  Response 415: All files rejected (no accepted files)
```

#### Endpoint Behavior

1. Validate the knowledge base exists.
2. For each uploaded file:
   a. Check file extension against `SupportedFormat` registry.
   b. Reject unsupported formats immediately.
   c. Warn on preview-status formats.
   d. Validate file size against `SupportedFormat.max_file_size_mb` and a global cap (default 100 MB).
3. Save accepted files to a temporary staging directory (configurable, default `data/uploads/staging/`).
4. Compute SHA-256 hashes for deduplication.
5. Trigger the ingestion pipeline for the accepted files (async, via background task or separate process).
6. Record a `pipeline_run` with a `source = "web_upload"` marker.
7. Return 202 Accepted with the pipeline run ID.

### 5.4 Large File Strategy

| File Size | Strategy |
|---|---|
| < 10 MB | Direct upload through the multipart endpoint |
| 10-100 MB | Chunked upload with `Content-Range` headers (future) |
| > 100 MB | Reject with clear guidance: "Use CLI or direct fileshare connector" |

For files between 10-100 MB (future phase):
- Client splits the file into 5 MB chunks.
- `POST /knowledge-bases/{kb_name}/upload/chunk` with `X-Chunk-Index` and `X-Chunk-Total` headers.
- `POST /knowledge-bases/{kb_name}/upload/complete` to finalize and trigger ingestion.
- Chunks are assembled server-side, verified with a client-supplied SHA-256, then ingested.

For the initial implementation, the 10 MB direct-upload limit is sufficient for
Markdown and text files which are the currently supported formats.

### 5.5 Security Considerations

- File type validation must be server-side (extension + magic bytes check).
- Uploaded files must be written to a staging directory outside the application root.
- File names must be sanitized (remove path traversal characters).
- Upload size limits enforced at the application level and ideally at the reverse proxy.
- Uploaded files are deleted from staging after successful ingestion.
- Failed/stale uploads are cleaned up by a periodic background job.

## 6. Document Understanding

### 6.1 Concept

Document Understanding goes beyond vector-based retrieval and uses LLMs to extract
structured knowledge from documents. It operates at three levels:

| Level | Capability | Priority | Difficulty |
|---|---|---|---|
| **Single-document** | Structured summary, table of contents, key entity extraction | P1 | Medium |
| **Cross-document** | Term glossary, synonym mapping, concept deduplication | P2 | High |
| **Knowledge map** | Document relationship graph, topic clustering, coverage visualization | P2 | Very High |

### 6.2 Data Model

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class UnderstandingLevel(str, Enum):
    DOCUMENT = "document"        # Single-document understanding
    CROSS_DOCUMENT = "cross_document"  # Multi-document analysis
    KNOWLEDGE_MAP = "knowledge_map"    # Graph-level understanding


class UnderstandingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    STALE = "stale"              # Document version changed, needs re-processing


@dataclass(frozen=True)
class DocumentUnderstanding:
    """A record of LLM-powered document understanding results, versioned against
    a specific document_version."""

    understanding_id: str
    """Unique identifier for this understanding run."""

    document_version_id: str
    """FK to document_versions.id — ties understanding to a specific version."""

    document_id: str
    """FK to documents.id — for cross-version aggregation."""

    knowledge_base_id: str
    """FK to knowledge_bases.id."""

    level: UnderstandingLevel
    """Which understanding level this record represents."""

    profile_id: str
    """The ProcessingProfile ID used (task_type = 'understand')."""

    model_id: str
    """The LLM model used."""

    provider: str
    """The LLM provider used."""

    status: UnderstandingStatus

    result: dict[str, Any]
    """The understanding output. Schema depends on level:
    - document: { summary, table_of_contents, entities, key_claims, language, topics }
    - cross_document: { glossary, synonym_map, deduplicated_concepts }
    - knowledge_map: { nodes, edges, clusters, coverage_stats }
    """

    prompt_used: str | None = None
    """The system prompt used for reproducibility."""

    tokens_used: int | None = None
    """Total tokens consumed (input + output)."""

    latency_ms: int | None = None
    """Processing latency in milliseconds."""

    error_message: str | None = None
    """Error details if status is FAILED."""

    created_at: str = ""
    updated_at: str = ""

    metadata: dict[str, Any] = field(default_factory=dict)
```

### 6.3 Single-Document Understanding (P1)

#### Output Schema

```json
{
  "summary": {
    "one_liner": "A single-sentence summary of the document.",
    "executive_summary": "2-3 paragraph executive summary.",
    "key_points": ["Point 1", "Point 2", "Point 3"]
  },
  "table_of_contents": [
    { "level": 1, "title": "Introduction", "anchor": null },
    { "level": 2, "title": "Background", "anchor": "background" },
    { "level": 1, "title": "Methodology", "anchor": null }
  ],
  "entities": [
    {
      "name": "RAGRig",
      "type": "PRODUCT",
      "mentions": 42,
      "description": "Open-source RAG governance platform"
    },
    {
      "name": "pgvector",
      "type": "TECHNOLOGY",
      "mentions": 15,
      "description": "PostgreSQL vector extension"
    }
  ],
  "key_claims": [
    {
      "claim": "RAGRig supports pgvector as a first-class vector backend.",
      "confidence": "high",
      "evidence_snippet": "pgvector and Postgres/pgvector as first-class vector backends"
    }
  ],
  "language": {
    "primary": "en",
    "confidence": 0.99
  },
  "topics": ["RAG", "vector databases", "knowledge governance", "open source"],
  "quality_metrics": {
    "readability_score": null,
    "estimated_reading_time_minutes": 12
  }
}
```

#### How It Uses ProcessingProfile

Single-document understanding is a `TaskType.UNDERSTAND` operation. The pipeline engine:

1. Looks up the ProcessingProfile for `(extension, TaskType.UNDERSTAND)`.
2. Uses the profile's `llm_provider`, `model_id`, `system_prompt`, and `output_schema`.
3. Feeds the document's `extracted_text` into the LLM via the profile's prompt template.
4. Validates the LLM's output against `output_schema`.
5. Stores the result as a `DocumentUnderstanding` record linked to the `document_version`.
6. If the profile's LLM is unreachable, falls back to `fallback_profile_id` (or a no-op).

#### Versioning and Traceability

- Every `DocumentUnderstanding` is tied to a specific `document_version_id`.
- When a document is re-ingested (new version), existing understanding records are
  marked `STALE`.
- The next `understand` pipeline run picks up stale records and re-processes them.
- Understanding results are queryable by `document_id`, `document_version_id`,
  `knowledge_base_id`, and `level`.

### 6.4 Cross-Document Term Glossary (P2)

#### Concept

When multiple documents reference the same concepts using different terminology, RAGRig
should detect these relationships and build a cross-document glossary.

Example:

```
Document A: "We use Qdrant as our vector database."
Document B: "The vector store is configured for cosine similarity."
Document C: "Vector DB connection pool settings..."

Detected glossary:
  "vector database" ≡ "vector store" ≡ "Vector DB" → canonical: "vector database"
```

#### Processing Pipeline

1. **Candidate extraction:** For each document version, extract terms and their
   definitions using the `understand` profile.
2. **Candidate pairing:** Select N most recently updated documents in the knowledge base.
   Pair candidates by semantic similarity of their definitions (using embeddings).
3. **LLM reconciliation:** Batch candidate pairs and ask an LLM to decide which are
   synonyms, which are distinct, and which canonical term to use.
4. **Glossary storage:** Store the glossary as a `DocumentUnderstanding` record with
   `level = CROSS_DOCUMENT`. The `document_version_id` can be `null` (KB-level).
5. **Incremental update:** When a new document is added, extract its terms and check
   against the existing glossary. Only process new or changed candidates.

#### Output Schema

```json
{
  "glossary": [
    {
      "canonical_term": "knowledge base",
      "aliases": ["KB", "knowledge collection", "knowledge store"],
      "definition": "A named collection of documents with shared ingestion and access policies.",
      "source_documents": ["doc-001", "doc-003", "doc-007"],
      "confidence": 0.92
    }
  ],
  "synonym_map": {
    "vector database": ["vector store", "vector DB", "vector backend"],
    "embedding model": ["embedder", "embedding provider"],
    "chunk": ["text segment", "document fragment"]
  },
  "deduplicated_concepts": [
    {
      "concept": "cosine similarity",
      "merged_from": ["cosine distance", "cosine metric"],
      "rationale": "These terms are used interchangeably across documents."
    }
  ]
}
```

### 6.5 Knowledge Map (P2)

#### Concept

A visual graph showing how documents in a knowledge base relate to each other, what
topics they cover, and where knowledge gaps exist.

#### Visualization

```
┌────────────────────────────────────────────────────────────────┐
│  Knowledge Map: "team-docs"                                     │
│                                                                 │
│              ┌──────────┐                                       │
│              │ RAG Arch │───references──┐                       │
│              └──────────┘               │                       │
│                    │                    ▼                       │
│                    │              ┌──────────┐                  │
│   ┌──────────┐     │              │ Embedding│                  │
│   │ Ingestion│─────┼──────────────│  Guide   │                  │
│   └──────────┘     │              └──────────┘                  │
│                    │                    │                       │
│                    ▼                    ▼                       │
│              ┌──────────┐        ┌──────────┐                  │
│              │Vector DB │        │ Chunking │                  │
│              │  Setup   │        │ Strategy │                  │
│              └──────────┘        └──────────┘                  │
│                                                                 │
│  Topics:  ● RAG (4 docs)  ● Embedding (2 docs)                 │
│           ○ Security (0 docs) ← gap detected                   │
│                                                                 │
│  [ Filter by topic ▼ ]  [ Zoom: - + ]  [ Export: PNG / SVG ]   │
└────────────────────────────────────────────────────────────────┘
```

#### Technical Approach

The knowledge map is built in two stages:

**Stage 1: Relationship Detection (batch, LLM-assisted)**
1. For each document, use the `understand` profile to extract topics and key claims.
2. Compute pairwise document similarity using embedding vectors.
3. Cluster documents into topic groups (e.g. with HDBSCAN or simple threshold).
4. For high-similarity pairs, ask the LLM to classify the relationship type:
   - `references`: Document A cites or links to Document B.
   - `extends`: Document B builds on concepts from Document A.
   - `contradicts`: Documents make conflicting claims.
   - `duplicates`: Documents cover substantially the same content.
   - `complements`: Documents cover different aspects of the same topic.
5. Store relationships as a `DocumentUnderstanding` record with `level = KNOWLEDGE_MAP`.

**Stage 2: Visualization (browser, interactive)**
- **Library:** [D3.js](https://d3js.org/) force-directed graph for the initial version.
  D3 is chosen because it's dependency-light (single JS file), works well with vanilla
  HTML, and has excellent force-simulation support for document graphs.
- **Alternative:** [Cytoscape.js](https://js.cytoscape.org/) if richer graph analysis
  (centrality, layout algorithms) is needed later. Cytoscape is ~400 KB gzipped and
  adds layout algorithm complexity that may be overkill for the initial version.
- **Data flow:**
  1. Frontend fetches graph data from `GET /knowledge-bases/{kb_name}/knowledge-map`.
  2. Renders as a D3 force-directed graph with:
     - Nodes: documents (size proportional to topic count or entity count)
     - Edges: relationships (color-coded by type)
     - Labels: document titles (shown on hover or for larger nodes)
  3. Supports zoom, pan, and click-to-focus.
  4. Topic legend on the side with document counts.
  5. Highlight detected knowledge gaps (topics with zero documents).

#### API Contract

```
GET /knowledge-bases/{kb_name}/knowledge-map
  Returns: {
    knowledge_base_id: "...",
    generated_at: "...",
    nodes: [
      {
        document_id: "...",
        title: "RAG Architecture Guide",
        topics: ["RAG", "architecture"],
        entity_count: 12,
        understanding_id: "..."
      }
    ],
    edges: [
      {
        source_document_id: "...",
        target_document_id: "...",
        relationship: "references",
        strength: 0.85,
        evidence: "Document A cites 'RAG Architecture Guide' in section 3.2."
      }
    ],
    topic_coverage: [
      { topic: "RAG", document_count: 4, coverage_pct: 80 },
      { topic: "Security", document_count: 0, coverage_pct: 0 }
    ]
  }
```

#### Initial Implementation Status

The first knowledge-map increment is implemented as
`GET /knowledge-bases/{kb_id}/knowledge-map`. It derives graph nodes and edges
from fresh latest-version `document_understandings` records, excludes stale or
failed understanding output, and reports deterministic document/entity
relationships in the Web Console. Relationship labels currently use shared
entity evidence (`mentions`, `shares_entities`, `co_mentioned`); embedding
clustering, LLM relationship classification, and D3 export controls remain later
P2 work.

### 6.6 Evaluation and Quality

All understanding outputs should be evaluable:

- **Single-document:** Human review of summary quality, entity accuracy, TOC completeness.
  Future: automated metrics (ROUGE, BERTScore) against reference summaries.
- **Cross-document glossary:** Human review of synonym mappings, deduplication accuracy.
- **Knowledge map:** Human review of relationship types, topic assignments.

Each `DocumentUnderstanding` record carries the `profile_id`, `model_id`, and `prompt_used`
so that evaluation results can be traced back to the exact configuration that produced them.

## 7. Phased Rollout Plan

### Phase 1: Foundation (this spec + follow-up implementation)

| Item | Deliverable | Dependencies |
|---|---|---|
| SupportedFormat data model | `src/ragrig/formats/` module with Pydantic models + YAML fixture | None |
| SupportedFormat API | `GET /supported-formats`, `GET /supported-formats/check` | SupportedFormat data model |
| SupportedFormat in README | Update plugin table with format support column | None |
| ProcessingProfile data model | `src/ragrig/profiles/` module with Pydantic models + YAML fixture | None |
| ProcessingProfile resolution engine | Profile lookup with fallback chain | ProcessingProfile data model |
| Default profiles for supported formats | YAML fixture with wildcard defaults | ProcessingProfile data model |
| Profile matrix API | `GET /profiles/matrix` returning grid data | ProcessingProfile resolution engine |
| Profile matrix Web Console view | Read-only HTML table in `/console` with LLM/deterministic indicators | Profile matrix API |
| Browser upload API | `POST /knowledge-bases/{kb_name}/upload` | SupportedFormat API |
| Browser upload Web Console UI | Drag-and-drop zone, file validation, upload progress | Browser upload API, SupportedFormat API |
| Upload format validation | Server-side format check + formatted rejection messages | SupportedFormat API |
| DocumentUnderstanding data model | `src/ragrig/understanding/` module with Pydantic models | ProcessingProfile data model |
| Single-document understanding runner | LLM call through ProcessingProfile, store result | ProcessingProfile, LLM provider adapters |
| Single-document understanding Web Console view | Read-only view of understanding results per document | Understanding runner |

### Phase 2: Editing and Rich Features

| Item | Deliverable | Dependencies |
|---|---|---|
| Profile CRUD API | `POST/PUT/DELETE /profiles/{profile_id}` | DB-backed profile storage |
| Profile matrix inline editing | Edit profile fields from the matrix view | Profile CRUD API |
| Profile evaluation view | Per-profile quality metrics in the Web Console | Understanding runner results |
| Cross-document glossary pipeline | Batch term extraction + LLM reconciliation | Understanding runner |
| Glossary Web Console view | Searchable, filterable glossary table | Glossary pipeline |
| Knowledge map generation pipeline | Relationship detection + graph building | Understanding runner |
| Knowledge map D3 visualization | Interactive graph in Web Console | Knowledge map pipeline |
| Chunked upload for large files | `POST .../upload/chunk` + `POST .../upload/complete` | Browser upload base |

### Phase 3: Evaluation and Optimization

| Item | Deliverable | Dependencies |
|---|---|---|
| Per-profile quality metrics dashboard | A/B comparison of profile versions | Phase 2 understanding results |
| Profile recommendation engine | Based on format + content, suggest best profile | Quality metrics |
| Automated glossary refresh | Trigger on new document ingestion | Glossary pipeline |
| Knowledge map coverage alerts | Notify when topics have zero or few documents | Knowledge map pipeline |
| Profile import/export | YAML/JSON export and import of profile definitions | Profile CRUD API |

## 8. Non-Goals

The following are explicitly out of scope for this spec and the follow-up implementation:

- Real-time collaborative profile editing.
- Profile marketplace or community sharing.
- Automatic profile generation (AI creates profiles from examples).
- Document understanding for non-text content (images, audio, video).
- Full NER (Named Entity Recognition) with custom entity types beyond LLM extraction.
- Integration with external knowledge graph databases (Neo4j, etc.).
- Any change to the existing `.py` code in this issue.

## 9. API Overview

Combined API surface for all four capabilities:

```
# SupportedFormat
GET    /supported-formats
GET    /supported-formats/check

# ProcessingProfile
GET    /profiles
GET    /profiles/{profile_id}
GET    /profiles/matrix

# Browser Upload
POST   /knowledge-bases/{kb_name}/upload

# Document Understanding
GET    /knowledge-bases/{kb_name}/understanding
GET    /documents/{doc_id}/understanding
GET    /knowledge-bases/{kb_name}/knowledge-map
```

All APIs except `POST /knowledge-bases/{kb_name}/upload` are read-only in the initial
implementation.

## 10. Verification

### Phase 1 Verification Commands (post-implementation)

```bash
# SupportedFormat
curl http://localhost:8000/supported-formats | jq '.formats | length'
curl http://localhost:8000/supported-formats?status=supported | jq '.formats[].extension'

# ProcessingProfile
curl http://localhost:8000/profiles | jq '.profiles | length'
curl http://localhost:8000/profiles/matrix | jq '.extensions'

# Browser upload (requires a file on disk)
echo "# test" > /tmp/test-upload.md
curl -X POST http://localhost:8000/knowledge-bases/fixture-local/upload \
  -F "files=@/tmp/test-upload.md" | jq '.accepted_files'

# Reject unsupported format
dd if=/dev/urandom of=/tmp/test.jpg bs=1024 count=1 2>/dev/null
curl -s -X POST http://localhost:8000/knowledge-bases/fixture-local/upload \
  -F "files=@/tmp/test.jpg" | jq '.rejections[0].reason'

# Document understanding (read-only, requires prior understanding runs)
curl http://localhost:8000/knowledge-bases/fixture-local/understanding | jq '.understandings | length'
```

## 11. References

- [RAGRig Plugin System Spec](./ragrig-plugin-system-spec.md)
- [RAGRig Web Console Spec](./ragrig-web-console-spec.md)
- [RAGRig MVP Spec](./ragrig-mvp-spec.md)

## 12. EVI-54 Implementation Delta (ProcessingProfile P0)

**PR:** [#33](https://github.com/evilgaoshu/ragrig/pull/33)
**Branch:** `agent/dev-pi/d76578cb`

### 12.1 Implemented

| Spec Item | Implementation | Notes |
|---|---|---|
| ProcessingProfile data model | `src/ragrig/processing_profile/models.py` | TaskType, ProfileStatus, ProcessingProfile, ProcessingKind, ProfileSource |
| Default profiles (6 wildcards) | `src/ragrig/processing_profile/registry.py` | `*.correct.default`, `*.clean.default`, `*.chunk.default`, `*.summarize.default`, `*.understand.default`, `*.embed.default` |
| Profile resolution (extension → wildcard → fallback) | `resolve_profile()` in registry | Supports per-extension overrides via `overrides` parameter |
| `GET /profiles` → `/processing-profiles` | `src/ragrig/main.py` | Returns profile list with task_type/extension/provider/status/provider_available; no raw secrets |
| `GET /profiles/matrix` → `/processing-profiles/matrix` | `src/ragrig/main.py` | 6 extensions × 6 task_types = 36 cells; each cell has profile_id/kind/source/is_default/provider_available |
| Web Console matrix | `src/ragrig/web_console.html` | Read-only table with sticky extension column, kind badges (deterministic/LLM-assisted/unavailable), source labels (default/override) |
| Pipeline profile tracking | `src/ragrig/indexing/pipeline.py`, `src/ragrig/ingestion/pipeline.py` | config_snapshot includes profile IDs; chunk.embed metadata includes `profile_id` |
| Provider availability check | `resolve_provider_availability()` in registry | Checks plugin registry status; deterministic-local always available; unavailable providers NOT faked as ready |
| 100% test coverage | `tests/test_processing_profile.py` (24 tests) + web-check tests (6) | Core hard scope maintained |

### 12.2 Deferred (per spec non-goals)

| Spec Item | Reason |
|---|---|
| SupportedFormat registry | Separate issue, not in P0 scope |
| Browser file upload | Separate issue, not in P0 scope |
| DocumentUnderstanding data model/runner | Separate issue, not in P0 scope |
| Profile CRUD (POST/PUT/DELETE) | Read-only only; CRUD deferred to future phase |
| Real LLM summarize/understand calls | Profiles define config only; stubs |
| Per-profile A/B evaluation | Deferred |
| Secret storage / secret echo in API | Never introduced; API validates no secrets |

### 12.3 Delta from Spec API Contract

| Spec Path | Implemented Path | Delta |
|---|---|---|
| `GET /profiles` | `GET /processing-profiles` | Renamed for clarity; response structure matches spec |
| `GET /profiles/{profile_id}` | Not implemented | Deferred; not in P0 hard requirements |
| `GET /profiles/matrix` | `GET /processing-profiles/matrix` | Renamed for consistency |
| `GET /supported-formats` | Not implemented | SupportedFormat deferred to separate issue |
| `GET /supported-formats/check` | Not implemented | SupportedFormat deferred to separate issue |
| `POST /knowledge-bases/{kb_name}/upload` | Not implemented | Browser upload deferred to separate issue |
| `GET /knowledge-bases/{kb_name}/understanding` | Not implemented | Understanding deferred to separate issue |
| `GET /documents/{doc_id}/understanding` | Not implemented | Understanding deferred to separate issue |
| `GET /knowledge-bases/{kb_name}/knowledge-map` | `GET /knowledge-bases/{kb_id}/knowledge-map` | Initial deterministic graph read path implemented from fresh understanding records |

### 12.4 Degradation Semantics

- When a profile's LLM provider is unavailable: matrix cell shows `provider_available: false` and amber ⚠ indicator in Web Console
- API response includes `provider_available: false` — never fabricates a ready state
- Ingestion/indexing pipelines record profile IDs in config snapshots and chunk/embed metadata for future fallback logic
- All task types have active wildcard defaults; no pipeline path hits the safe fallback in current usage

## 13. EVI-53 Implementation Delta (SupportedFormat Registry + Browser Upload)

**PR:** [#32](https://github.com/evilgaoshu/ragrig/pull/32)
**Branch:** `agent/dev-pi/f58150b9`

### 13.1 Delivered: SupportedFormat Registry + Browser Upload

This section documents the implementation of the SupportedFormat registry and browser
upload entry point (Phase 1 items marked above). The following were implemented:

#### New Modules

- `src/ragrig/formats/` — SupportedFormat data model (`model.py`), registry (`registry.py`),
  and YAML fixture (`supported_formats.yaml`) defining 13 file formats across
  supported (4), preview (5), and planned (4) statuses.

#### API Endpoints

- `GET /supported-formats` — Lists all formats, optionally filtered by `?status=` query param.
- `GET /supported-formats/check?extension=<ext>` — Checks a single extension against the
  registry, returning `supported`/`preview`/`planned`/`unsupported` status with detail.
- `POST /knowledge-bases/{kb_name}/upload` — Multipart file upload endpoint that:
  - Validates each file's extension against the SupportedFormat registry
  - Rejects unsupported/planned formats with HTTP 415 (`reason: unsupported_format`)
  - Accepts supported/preview formats and triggers the ingestion pipeline
  - Returns 202 with `pipeline_run_id`, `accepted_files`, `rejections`, and `warnings`

#### Web Console Updates

- **Supported Formats panel**: Displays formats grouped by status (supported/preview/planned)
  with color-coded chips and hovers showing limitations.
- **Browser Upload panel**: Drag-and-drop zone, file picker, per-file format validation
  with status indicators (ready/warning/error), upload submission, and result display
  with pipeline run link.

#### Dependencies Added

- `python-multipart` — Required by FastAPI for multipart form file uploads.
- `pyyaml` — Required for parsing the SupportedFormat YAML fixture.

#### Non-Implemented (per issue scope)

- ProcessingProfile CRUD, matrix editing, or profile evaluation.
- DocumentUnderstanding, term glossary, or knowledge map.
- 10-100MB chunked upload.
- PDF/DOCX/XLSX advanced parser capabilities.
- Secret plaintext storage or display.

#### Verification

```bash
# SupportedFormat count
curl -s http://localhost:8000/supported-formats | jq '.formats | length'
# => 13 (all statuses), >= 4 (supported status)

# Check .md support
curl -s 'http://localhost:8000/supported-formats/check?extension=.md' | jq -r '.supported, .status'
# => true, supported

# Upload .md to fixture KB
echo "# test" > /tmp/test-upload.md
curl -s -X POST http://localhost:8000/knowledge-bases/fixture-local/upload \
  -F 'files=@/tmp/test-upload.md' | jq '.accepted_files, .pipeline_run_id'
# => 1, <non-empty uuid>

# Reject .jpg
curl -s -X POST http://localhost:8000/knowledge-bases/fixture-local/upload \
  -F 'files=@/tmp/test.jpg' | jq '.rejections[0].reason'
# => "unsupported_format"
```
