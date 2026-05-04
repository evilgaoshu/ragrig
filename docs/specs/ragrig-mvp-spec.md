# RAGRig MVP Spec

Issue: EVI-27
Date: 2026-05-03
Status: PM-approved draft for review

## 1. Owner Decisions

The owner selected Route A: a local-first vertical slice. This spec turns the PM discussion into a versioned project document for the first RAGRig implementation track.

Accepted baseline:

- Start with a small, runnable RAG pipeline instead of broad connector coverage or a full governance platform.
- Phase 1a is API/CLI first. A Web UI is deferred.
- Phase 1a uses Python and FastAPI for the service layer.
- Phase 1a uses PostgreSQL with pgvector as the primary metadata and vector backend.
- Qdrant is planned for Phase 1b unless the owner later promotes it to a hard requirement.
- The current SPEC-only PR does not require `192.168.3.100` runtime validation. Any later runtime, deployment, smoke, live, connector, or profile validation work must include `192.168.3.100` verification evidence as a hard requirement.

## 2. Product Positioning

RAGRig is an open-source RAG governance and pipeline platform for enterprise knowledge. Its first audience is small and medium-sized teams that need a self-hosted, inspectable, low-cost way to turn internal knowledge sources into model-ready retrieval data.

The product should not compete as another generic chatbot wrapper. Its durable value is the operational layer around RAG:

- source provenance from retrieval result back to source file, document version, chunk, model, and pipeline run
- predictable ingestion, parsing, cleaning, chunking, embedding, indexing, and retrieval behavior
- metadata and data-model boundaries that can later support permissions, versioning, audits, and evaluation
- a Docker Compose first deployment path, with Kubernetes and broader operations support later

## 3. Target Users

Primary users:

- Internal platform, IT, or knowledge operations teams that need to build governed RAG systems for company documents.
- Developers integrating retrieval APIs into internal applications, assistants, or agent systems.

Secondary users:

- Open-source contributors building parsers, connectors, evaluation tools, or vector backend adapters.
- Teams evaluating whether RAG pipeline changes improve retrieval quality before scaling to larger knowledge bases.

Phase 1a favors developers and platform operators over non-technical end users. UI-heavy knowledge review workflows are deferred.

## 4. Phase 1a Goals

Phase 1a must prove the smallest complete loop:

1. Start the local development stack with Docker Compose.
2. Register or select a local knowledge base.
3. Ingest a local directory of files.
4. Parse Markdown, plain text, and PDF files.
5. Normalize and clean extracted text with deterministic defaults.
6. Chunk text into stable chunks with source references.
7. Generate embeddings with a local-first provider path, such as deterministic local
   embeddings for smoke tests, Ollama, LM Studio, BAAI BGE, or another local
   OpenAI-compatible endpoint.
8. Store metadata and vectors in PostgreSQL with pgvector.
9. Query a retrieval API.
10. Return top-k retrieval results with source citations and pipeline-run traceability.

The goal is a working developer demo and a foundation for governance. It is acceptable for Phase 1a to be plain and narrow if the boundaries are correct.

## 5. Non-goals For Phase 1a

The following are explicitly outside Phase 1a:

- hosted SaaS control plane
- full Web UI
- general-purpose agent workflow automation
- full office-suite editing
- custom vector database implementation
- broad enterprise connector coverage
- production-grade ACL enforcement
- multi-tenant billing or organization management
- LLM answer generation or chat UI
- advanced DAG orchestration

## 6. Hard Requirements

### 6.1 Product Behavior

- Ingest local files and folders from a configured path.
- Support Markdown, plain text, and PDF parsing.
- Preserve source references for every document and chunk.
- Persist pipeline-run records for ingestion, parsing, chunking, embedding, indexing, and failure states.
- Provide a retrieval endpoint that returns chunks, scores, and citations.
- Avoid answer generation in Phase 1a. The retrieval API returns evidence, not a generated final answer.

### 6.2 Architecture

- Use Python and FastAPI for the API service.
- Use PostgreSQL for metadata.
- Use pgvector for Phase 1a vector storage.
- Provide Docker Compose for local development and smoke validation.
- Keep parser, cleaner, chunker, embedding provider, and vector backend boundaries explicit.
- Store enough metadata to support later versioning, permission filtering, audit events, and evaluation without redesigning the core model.

### 6.3 Delivery

- This SPEC must be committed as `docs/specs/ragrig-mvp-spec.md`.
- Later development handoffs must include clear hard requirements, best-effort items, and a commit or PR result.
- Runtime implementation work must include shared environment validation on `192.168.3.100`, or a clear blocker with logs and next steps.

## 7. Best-effort Items

Best-effort for Phase 1a:

- Ollama-compatible or BAAI BGE local embedding example if it can use the same provider abstraction cleanly.
- Simple CLI wrapper for ingestion and retrieval if the API is already stable.
- Basic retrieval-event logging for later evaluation.
- Sample documents and a smoke script.
- Minimal architecture notes in README linking to this spec.

These items must not block the Phase 1a hard loop.

## 8. Phase 1b Scope

Phase 1b expands the proven loop:

- DOCX, PPTX, and XLSX parsing.
- Qdrant vector backend adapter.
- Configurable cleaning steps.
- Optional reranker support.
- Richer retrieval filters.
- More complete evaluation hooks.
- Connector preparation for S3-compatible storage, SMB/NFS, Google Drive, wiki systems, WPS, and OnlyOffice-compatible services.

## 9. Governance Roadmap

Phase 1a reserves data-model boundaries but does not enforce full governance.

Phase 2 adds governance core:

- knowledge base, document, chunk, and pipeline-run versioning
- metadata schemas and validation
- document-level and chunk-level access control
- pre-retrieval permission filtering
- audit events for ingestion, indexing, retrieval, export, and deletion

Phase 3 expands workflows and connectors:

- lightweight DAG runner
- retries, resumable runs, dry-run mode, and failure queues
- enterprise source connectors and export targets

Phase 4 adds evaluation and operations:

- golden question sets
- retrieval quality, citation quality, refusal behavior, latency, and cost metrics
- regression checks before production reindexing
- backup, restore, upgrade, and deployment guides

## 10. System Architecture

Phase 1a architecture:

```text
Local files/folders
        |
        v
Source scanner
        |
        v
Parser registry
        |
        v
Cleaner and normalizer
        |
        v
Chunker
        |
        v
Embedding provider
        |
        v
PostgreSQL metadata + pgvector index
        |
        v
Retrieval API
```

Core components:

| Component | Responsibility | Phase 1a boundary |
| --- | --- | --- |
| API service | Expose ingestion, run status, and retrieval endpoints | FastAPI only; no Web UI |
| CLI | Optional wrapper over API operations | Best-effort |
| Source scanner | Discover files under a configured local path | Local filesystem only |
| Parser registry | Convert supported files to extracted text and metadata | Markdown, text, PDF |
| Cleaner | Normalize extracted text | Deterministic defaults; LLM cleaning deferred |
| Chunker | Split text into stable chunks | Fixed token or character strategy with overlap |
| Embedding provider | Generate vectors | Local-first provider path required; cloud OpenAI-compatible providers are optional |
| Index repository | Persist vectors and metadata | pgvector required |
| Retrieval service | Query top-k chunks and return citations | No answer generation |
| Run recorder | Track pipeline runs and per-document outcomes | Required for traceability |

## 11. Data Flow

1. A user starts the Docker Compose stack.
2. A user creates or selects a knowledge base.
3. A user submits a local ingestion request with a path and pipeline config.
4. The source scanner finds supported files and records source metadata.
5. The parser registry extracts text and file-level metadata.
6. The cleaner normalizes text and records cleaning metadata.
7. The chunker creates stable chunks with source references.
8. The embedding provider generates vectors for chunks.
9. The index repository writes metadata and vectors into PostgreSQL and pgvector.
10. The run recorder persists run status, counts, failures, and config snapshots.
11. A retrieval request queries pgvector and returns ranked chunks with citations.

## 12. Data Model Boundary

Phase 1a should include these core entities or equivalent tables:

| Entity | Required purpose |
| --- | --- |
| knowledge_bases | Group documents and retrieval queries under a named collection |
| sources | Store local source configuration and source identity |
| documents | Track discovered source files and content hashes |
| document_versions | Preserve parsed content versions and parser metadata |
| chunks | Store chunk text, chunk ordering, spans, and source references |
| embeddings | Link chunks to provider, model, dimensions, and vector reference |
| pipeline_runs | Track run status, timing, config snapshot, counts, and errors |
| pipeline_run_items | Track per-document success, skip, and failure states |

Minimum citation fields for retrieval results:

- knowledge base id
- document id
- document version id
- chunk id
- source URI or local path
- chunk index
- score
- optional page, heading, or character span when available

ACL and audit tables may be introduced later. Phase 1a should avoid fake permission enforcement, but it must not make future pre-retrieval filtering impossible.

## 13. API Draft

Phase 1a should expose the following API shape or a close equivalent:

```text
GET /health
POST /knowledge-bases
POST /sources/local/ingest
GET /pipeline-runs/{run_id}
POST /retrieve
GET /documents/{document_id}/chunks
```

Example retrieval request:

```json
{
  "knowledge_base_id": "kb_123",
  "query": "How do we report security issues?",
  "top_k": 5
}
```

Example retrieval result:

```json
{
  "query": "How do we report security issues?",
  "results": [
    {
      "chunk_id": "chunk_123",
      "document_id": "doc_123",
      "document_version_id": "docv_123",
      "source_uri": "file:///data/SECURITY.md",
      "score": 0.82,
      "text": "Relevant chunk text",
      "citation": {
        "chunk_index": 4,
        "page": null,
        "heading": "Reporting Vulnerabilities"
      }
    }
  ]
}
```

## 14. Pipeline Configuration

Pipeline configuration should be explicit and serializable. YAML is preferred for developer readability.

Example shape:

```yaml
knowledge_base: default
source:
  type: local
  path: ./samples/security
  include:
    - "**/*.md"
    - "**/*.txt"
    - "**/*.pdf"
parser:
  markdown: default
  text: default
  pdf: default
cleaning:
  normalize_whitespace: true
  strip_empty_lines: true
chunking:
  strategy: fixed_tokens
  max_tokens: 800
  overlap_tokens: 100
embedding:
  provider: openai_compatible
  model: text-embedding-3-small
index:
  backend: pgvector
```

## 15. Error Handling

Phase 1a must handle partial failures predictably:

- A failed document must not fail the entire run unless configuration says fail-fast.
- Each failed document must record parser, cleaner, embedding, or indexing stage and error summary.
- Unsupported file types should be skipped with a recorded reason.
- Re-running the same path should be idempotent when file content hashes have not changed.
- Retrieval should return an empty result set with a clear response when a knowledge base has no indexed chunks.

## 16. Testing And Verification

SPEC PR verification:

- The spec file exists at `docs/specs/ragrig-mvp-spec.md`.
- The document contains product scope, non-goals, architecture, data model boundary, API draft, roadmap, work breakdown, and acceptance criteria.
- No runtime validation is required for this SPEC-only PR.

Phase 1a implementation verification:

- `docker compose up` starts the app and PostgreSQL with pgvector.
- A sample local directory can be ingested end to end.
- Retrieval returns top-k chunks with citations.
- Pipeline-run status is persisted and queryable.
- Unit tests cover chunking, parsing behavior, metadata persistence, retrieval output shape, and failure recording.
- Shared test environment validation on `192.168.3.100` is required, with commands, result summary, and log locations.

## 17. Work Breakdown

Recommended implementation order after this SPEC is accepted:

1. Project scaffold and developer workflow
   - Python package structure
   - FastAPI service
   - Docker Compose
   - lint, format, and test commands

2. Metadata database and migrations
   - PostgreSQL connection
   - core tables
   - pgvector extension setup
   - migration workflow

3. Local ingestion and parsing
   - local scanner
   - Markdown parser
   - text parser
   - PDF parser
   - content hashes and document records

4. Cleaning and chunking
   - deterministic text normalization
   - fixed-size chunker with overlap
   - stable chunk ids or stable chunk references

5. Embedding and indexing
   - local-first embedding provider path, with cloud providers optional
   - pgvector writes
   - idempotent update behavior for unchanged content

6. Retrieval API
   - top-k vector search
   - citation shape
   - result filtering by knowledge base

7. Pipeline run history and failure recording
   - run lifecycle
   - per-document outcomes
   - error summaries

8. Smoke data, docs, and shared environment validation
   - sample documents
   - smoke commands
   - `192.168.3.100` validation record for runtime implementation

## 18. Acceptance Criteria For Phase 1a

Phase 1a is acceptable when:

- A fresh clone can start the stack with documented commands.
- A local sample directory can be ingested into a named knowledge base.
- The system supports Markdown, plain text, and PDF input.
- Chunks include stable source references.
- Embeddings are stored in pgvector.
- Retrieval returns top-k chunks with scores and citations.
- A user can inspect pipeline-run status and per-document failures.
- Tests cover the behavior that affects indexing, retrieval, permissions boundary, or source traceability.
- Runtime validation evidence from `192.168.3.100` is included for implementation PRs.

## 19. Risks

- Parser quality can expand scope quickly. Phase 1a should prioritize predictable extraction over perfect formatting.
- LLM-assisted cleaning can become unclear. Phase 1a uses deterministic cleaning; LLM cleaning becomes a later configurable step.
- Supporting Qdrant and pgvector simultaneously in Phase 1a would increase adapter and test surface. Phase 1a chooses pgvector first.
- Governance can become performative if only labels are added. Phase 1a keeps source/version/run boundaries real and defers permission enforcement.
- A Web UI would slow the first runnable loop. Phase 1a exposes API and optional CLI only.

## 20. Future Decisions

These decisions are intentionally deferred beyond the SPEC PR:

- Exact ORM and migration library.
- Exact PDF parser package.
- Exact embedding model for default examples.
- Whether CLI is required in Phase 1a or remains best-effort.
- Whether Qdrant is promoted from Phase 1b to an earlier implementation issue.
- Whether the first UI should be an admin console, review workflow, or retrieval playground.
