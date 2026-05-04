# RAGRig Web Console Spec

Date: 2026-05-03
Branch: `design/web-console-spec-prototype`
Status: design draft

## Purpose

RAGRig needs a Web Console because governance, ingestion, review, and evaluation are hard to operate from CLI and Swagger alone.

The Web Console is not a chatbot-first UI. It is an operational workbench for people who need to turn enterprise sources into reliable RAG-ready knowledge and prove what happened along the way.

This spec covers the first lightweight Web Admin Console MVP. The first version must include:

- knowledge base list
- data source configuration
- local file and Markdown ingestion tasks
- pipeline run history
- document and chunk preview
- model configuration
- retrieval debugging Playground
- health check and database status

## Target Users

Primary users:

- Platform engineers running RAGRig for internal teams.
- Knowledge operations owners curating documents and pipelines.
- AI application developers debugging retrieval quality.

Secondary users:

- Security and compliance reviewers checking source provenance, access boundaries, and audit trails.
- Open-source contributors validating connector, parser, vector-store, or model integrations.

## Product Principles

- **Start with operations, not conversation.** The first screen shows system state, knowledge bases, pipeline health, and quality signals.
- **Make provenance visible.** Every document, chunk, retrieval result, and evaluation result should point back to source, version, and pipeline run.
- **Keep actions inspectable.** Ingestion, cleaning, chunking, embedding, indexing, and evaluation must expose configuration snapshots and outcomes.
- **Use dense but calm layouts.** The product should feel like infrastructure for repeated work, not a marketing dashboard.
- **Separate current capability from future capability.** Prototype screens may show the intended console shape, but implementation phases must align with backend readiness.

## Navigation

The first console should use a persistent left rail with these sections:

| Section | Purpose |
| --- | --- |
| Overview | Health, storage, model, ingestion, and quality summary |
| Knowledge Bases | List and manage knowledge collections |
| Sources | Configure local, SMB/NFS, S3/R2, wiki, Google Drive, database, WPS, and OnlyOffice sources |
| Pipelines | Inspect ingestion and processing runs |
| Documents | Preview extracted text, versions, chunks, parser metadata, and source links |
| Retrieval Lab | Test queries, inspect ranked chunks, rerank output, and citations |
| Models | Register LLMs, embedding models, rerankers, OCR, and parser profiles |
| Evaluation | Golden questions, quality runs, regressions, and human feedback |
| Settings | Deployment, secrets, vector backends, auth, audit, and backups |

## MVP Required Modules

### 1. Knowledge Base List

The knowledge base list is the console's default working inventory.

It must show:

- name
- owner or team
- description
- vector backend
- document count
- chunk count
- latest pipeline status
- latest update time

MVP actions:

- open knowledge base detail
- create knowledge base
- trigger local ingestion for a selected knowledge base

### 2. Data Source Configuration

The first data source configuration screen should support local directory sources and reserve the UI model for later SMB/NFS, S3/R2, wiki, Google Docs, WPS, OnlyOffice, and database sources.

MVP fields:

- knowledge base
- source name
- source kind
- root path
- include patterns
- exclude patterns
- max file size
- schedule mode, defaulting to manual

MVP actions:

- save draft
- test scan
- create source

Secrets must not be shown in raw form. Future cloud and SaaS connectors should bind to named credential profiles.

### 3. Local File and Markdown Ingestion Tasks

The MVP ingestion task UI should expose the current CLI-local ingestion behavior through the console.

It must support:

- selected knowledge base
- selected local source
- include patterns for `.md`, `.markdown`, `.txt`, and `.text`
- dry-run mode
- max file size
- start run
- display discovered, skipped, succeeded, and failed counts

The UI should make it clear when a run is a dry run and when it writes `documents`, `document_versions`, `pipeline_runs`, and `pipeline_run_items`.

### 4. Pipeline Run History

Pipeline run history must reflect the existing backend model.

It must show:

- run id
- run type
- knowledge base
- source
- status
- total items
- success count
- skipped count when available from item metadata
- failure count
- started and finished timestamps

Run detail must show per-document items with status, filename, skip reason, version number, and error message.

### 5. Document and Chunk Preview

Document preview starts with current `document_versions` and prepares for future chunks.

It must show:

- source URI
- mime type
- content hash
- version number
- parser name
- parser metadata
- extracted text preview
- Markdown preview for Markdown documents
- future chunk list with chunk index, heading, char span, page number, and text

The MVP may show an empty chunk state until chunking is implemented, but the UI contract should already reserve the chunk preview region.

### 6. Model Configuration

Model configuration should begin as a registry UI, even if only local or OpenAI-compatible providers are wired later.

It must support profiles for:

- LLM
- embedding model
- reranker
- parser profile

MVP fields:

- provider
- model name
- endpoint
- dimensions for embedding models
- context limit or max input tokens
- batch size
- status

Changing an embedding model should warn that affected knowledge bases may need reindexing.

### 7. Retrieval Debugging Playground

The Playground is evidence-first. It should debug retrieval results before answer generation exists.

It must provide:

- knowledge base selector
- query input
- top-k control
- filter preview
- model profile selector
- run query action
- ranked result list
- score
- citation
- document version
- chunk index
- metadata
- copy API request

If retrieval APIs are not implemented yet, the first UI implementation may use mock data behind a feature flag or disabled state.

### 8. Health Check and Database Status

The console should surface backend readiness without requiring Swagger or CLI commands.

It must show:

- API health
- database connectivity
- Alembic revision state
- pgvector extension state
- table availability
- latest error detail when unhealthy

The first implementation can call `GET /health` and later expand to `GET /system/status`.

## First Prototype Screen

The first prototype is a single operator canvas for the lightweight Web Admin Console MVP.

It should include:

- service and database health
- current vector backend state
- knowledge base summary
- data source configuration
- local file and Markdown ingestion task controls
- latest pipeline runs
- document and chunk preview
- model configuration
- retrieval debugging Playground

This screen is intentionally not a landing page. It is the first screen an authenticated operator sees.

## Core Screens

### Overview

The overview provides a compact operational readout:

- health state for API, DB, worker, vector backend, and model provider
- counts for knowledge bases, sources, documents, chunks, embeddings, and pipeline runs
- last ingestion status and next scheduled run
- top failing sources or parser types
- recent retrieval evaluation score
- quick actions for ingest, evaluate, and open Retrieval Lab

### Knowledge Bases

Required fields:

- name
- description
- owner
- source count
- document count
- latest version timestamp
- chunk count
- embedding model
- vector backend
- access profile
- quality score

Primary actions:

- create knowledge base
- open detail
- trigger reindex
- run evaluation
- export package

### Sources

Supported source categories:

- local directory
- SMB/NFS
- S3-compatible storage, including Cloudflare R2
- Google Drive and Google Docs
- wiki systems
- relational databases
- WPS document middle platform
- OnlyOffice-compatible document services

Each source detail should show:

- connection kind and URI
- credential profile name, never raw secret values
- sync schedule
- include and exclude rules
- last scan result
- changed, skipped, failed, and deleted item counts
- permission mapping strategy

### Pipelines

Pipeline runs should be inspectable at three levels:

- run summary: status, timing, config snapshot, counts, and owner
- stage detail: scan, parse, clean, chunk, embed, index, evaluate
- item detail: per-document success, skip, failure, parser metadata, and error message

The UI should preserve the existing backend concept of `pipeline_runs` and `pipeline_run_items`.

### Documents

Document review must support:

- source preview
- extracted text preview
- Markdown preview and edit draft
- document version comparison
- chunk list with source spans
- parser metadata
- pipeline lineage
- skip and failure reasons

Office editing should stay integration-first. WPS and OnlyOffice can provide rich document preview/editing, while RAGRig owns extracted text, Markdown review, chunk inspection, and reindex decisions.

### Retrieval Lab

The Retrieval Lab lets developers and knowledge owners inspect retrieval behavior without generating final answers by default.

Controls:

- knowledge base selector
- query input
- top-k
- filters
- dense, sparse, hybrid, and rerank toggles
- model profile selector

Results:

- ranked chunks
- score and rerank score
- source citation
- document version
- chunk index and span
- metadata chips
- copy as API request

### Models

Model registry should cover:

- LLM
- embedding model
- reranker
- OCR
- parser profile

Model fields:

- provider
- model name
- endpoint
- dimension or context limit
- batch limit
- supported languages
- deployment mode
- cost profile
- health status
- affected knowledge bases when changed

### Evaluation

Evaluation should show:

- golden question sets
- retrieval hit rate
- citation coverage
- no-answer behavior
- latency and cost
- regression comparison between pipeline or model versions
- human feedback queue

## Phase Boundaries

### Phase 1c: Lightweight Web Admin Console MVP

Build a minimal Web Console on top of current Phase 1a/1b capabilities:

- health check and database status
- knowledge base list
- data source configuration for local directory sources
- local file and Markdown ingestion task controls
- pipeline run list and detail
- document version preview for Markdown and plain text
- chunk preview empty state or mock preview until chunking exists
- model configuration registry shell
- Retrieval Playground shell if retrieval endpoint is not ready

### Phase 2: Operational Console

Add mutating workflows:

- richer source configuration
- inspect failures
- retry run
- preview extracted text
- approve or reject review items

### Phase 3: Governance Console

Add enterprise governance:

- access profiles
- pre-retrieval permission previews
- audit log
- metadata schema editor
- export and backup controls
- evaluation regression gates

## Data Requirements

The Web Console should rely on explicit API endpoints instead of reading database tables directly.

Initial API needs:

```text
GET /health
GET /knowledge-bases
GET /knowledge-bases/{id}
GET /sources
GET /pipeline-runs
GET /pipeline-runs/{id}
GET /pipeline-runs/{id}/items
GET /documents
GET /documents/{id}
GET /documents/{id}/versions
GET /document-versions/{id}
GET /document-versions/{id}/chunks
```

Follow-on API needs:

```text
POST /knowledge-bases
POST /sources/local
POST /sources/{id}/ingest
POST /retrieve
GET /models
POST /models
GET /evaluations
POST /evaluations/runs
```

## UX States

Every console screen needs these states:

- loading
- empty
- healthy
- degraded
- failed
- permission denied
- stale data
- long-running operation

## Prototype Deliverables

The design prototype lives at:

```text
docs/prototypes/web-console/index.html
```

The exported prototype image lives at:

```text
docs/prototypes/web-console/ragrig-web-console-prototype.png
```

## Non-goals

- Building a chat-first product experience.
- Replacing WPS or OnlyOffice as full office-suite editors.
- Implementing all screens in this branch.
- Adding backend routes in this branch.
- Creating a SaaS billing or organization control plane.

## Open Questions

- Should Phase 1c use server-rendered templates first, or a separate React/Vite app?
- Should Retrieval Lab expose answer generation once retrieval APIs exist, or keep evidence-only as the default?
- How much document editing should RAGRig own versus delegating to WPS, OnlyOffice, or Markdown-specific editors?
