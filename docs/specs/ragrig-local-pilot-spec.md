# RAGRig Local Pilot Spec

Date: 2026-05-14
Branch: `codex/local-pilot-spec`
Status: draft for owner review

## Purpose

RAGRig's next product step is a simple local pilot, not an enterprise pilot.

The first pilot must prove that a user can start RAGRig locally, add a small
knowledge source, index it, and ask grounded questions with visible citations
and retrieval evidence. Enterprise connectors, real tenant permissions, and
organization rollout remain roadmap work.

The pilot should answer one question clearly:

```text
Can a small team run RAGRig on a laptop or local workstation and evaluate a
real RAG workflow in under 30 minutes?
```

## Positioning

RAGRig Local Pilot is a local-first RAG workbench.

It is not a generic chat-with-PDF toy. The value is the inspectable pipeline:
source, parser output, chunks, model configuration, vector backend, retrieval
hits, generated answer, citations, and health checks all remain visible.

The pilot narrows RAGRig's near-term story to:

- upload local documents or import a small docs URL set
- use local models first, with mainstream cloud providers available
- default to Postgres/pgvector, with Qdrant as an optional backend
- expose the whole path in a lightweight Web Console
- show failures in plain language instead of hiding them behind a generic
  `failed` state

## Target Users

Primary users:

- developers evaluating RAG tooling for a small team
- founders or technical operators testing an internal knowledge base idea
- open-source contributors validating parser, model, retrieval, or UI changes

Secondary users:

- platform engineers who want a local proving ground before enterprise
  connector work
- teams that need a reproducible demo before deciding whether to pilot deeper
  governance features

## Owner Decisions

The owner approved these boundaries during planning:

- Use the hybrid scope: support both document upload and lightweight website
  import in the first pilot.
- Use the recommended local stack: Docker Compose with Postgres/pgvector as
  the default, local models first, Qdrant optional.
- Cloud models must be supported, but the first pilot should not become a
  Vertex AI or Bedrock integration project.
- Gemini must have health check support and one answer smoke path.
- Website import should support single-page URL plus sitemap or docs page list
  import; it should not be a general-purpose crawler.
- Document upload should support Markdown, TXT, PDF, and DOCX.
- Web Console should use a hybrid shape: Local Pilot Wizard plus normal
  management pages.

## In Scope

### Inputs

Document upload:

- Markdown: `.md`, `.markdown`
- text: `.txt`, `.text`
- PDF: text-based PDFs first
- DOCX: body text, headings, and lists first

Website import:

- one public HTML page URL
- sitemap URL
- explicit docs page list

### Model Providers

Local-first providers:

- Ollama
- LM Studio
- generic OpenAI-compatible local endpoint

Cloud providers required for the pilot:

- OpenAI-compatible endpoint
- OpenAI
- OpenRouter
- Gemini, including health check and one answer smoke

Cloud providers listed but non-blocking for the pilot:

- Google Vertex AI
- AWS Bedrock
- Azure OpenAI
- Anthropic and other catalog providers already represented in the registry

### Vector Backends

Default:

- Postgres with pgvector

Optional:

- Qdrant

The default demo path must not require Qdrant.

### Web Console

The first pilot console must include:

- Local Pilot Wizard
- knowledge base list and detail
- upload/import source step
- model provider configuration and health check
- pipeline run status
- document preview
- chunk preview
- retrieval and answer Playground
- health and database status

## Out of Scope

The Local Pilot does not include:

- enterprise tenant pilot
- Google Workspace or Microsoft 365 real tenant validation
- broad SMB/NFS/S3 rollout as the main demo path
- recursive whole-site crawler
- authenticated website crawling
- OCR for scanned PDFs as a hard requirement
- complex DOCX tables, comments, tracked changes, or embedded media fidelity
- production RBAC, SSO, billing, hosted SaaS, or multi-tenant org management
- full Vertex AI and Bedrock runtime coverage as pilot blockers

## User Journey

1. User starts the local stack.
2. User opens `/console`.
3. Console shows a Local Pilot Wizard and system health.
4. User creates or selects a knowledge base.
5. User uploads files or enters one URL, sitemap URL, or docs page list.
6. User selects model provider:
   - local provider if available
   - cloud provider if credentials are configured
7. Console runs provider health checks before ingestion and answer smoke.
8. User starts ingestion.
9. Console shows parsing, cleaning, chunking, embedding, and indexing progress.
10. User opens document/chunk preview to inspect extracted text.
11. User asks a question in Playground.
12. Console shows:
    - generated answer
    - citations
    - top retrieval hits
    - chunk scores
    - model/provider diagnostics
    - relevant pipeline run references

## Web Console Shape

The home screen uses a hybrid layout:

- persistent navigation for platform pages
- Local Pilot Wizard on the first screen
- status, document preview, and Playground preview visible beside the wizard

Recommended navigation:

- Overview
- Local Pilot
- Knowledge Bases
- Sources
- Runs
- Documents
- Models
- Playground
- Health

The Local Pilot Wizard should be the fastest route through the product. It
should not hide the normal pages; it should orchestrate them.

## API Surface

The implementation may reuse or extend existing endpoints, but the pilot
requires these product-level capabilities:

- create or select knowledge base
- upload document into a knowledge base
- import website source into a knowledge base
- create ingestion run
- inspect run and run-item status
- list documents and versions
- list chunks for a document version
- list model providers and health status
- run provider-specific answer smoke
- search retrieval results
- generate grounded answer with citations
- inspect health and DB/vector backend status

## Data Flow

```text
Document upload / URL import
        |
        v
Source record + pipeline run
        |
        v
Parser selection
        |
        v
Text extraction + sanitizer
        |
        v
Chunking
        |
        v
Embedding provider
        |
        v
pgvector by default / Qdrant optional
        |
        v
Retrieval + optional rerank
        |
        v
Answer generation + citations
        |
        v
Playground evidence view
```

## Provider Behavior

Provider status must be truthful:

- `ready`: configuration exists and health check succeeded
- `degraded`: configuration exists, but a runtime dependency, model, or smoke
  path is unavailable
- `unavailable`: required config or dependency is missing
- `unknown`: provider has metadata only and no runtime check in the pilot

Gemini must not be metadata-only. The pilot requires:

- configuration validation
- health check
- one answer smoke using the same answer boundary as local/OpenAI-compatible
  providers
- redacted error messages for missing or invalid credentials

Vertex AI and Bedrock may remain catalog/documentation entries unless a later
issue promotes them into hard pilot scope.

## Error Handling

The pilot should prefer explicit degraded states over silent fallback.

Required user-facing errors:

- model server not reachable
- model name missing or not found
- API key missing
- provider authentication failed
- PDF encrypted
- PDF has no extractable text
- DOCX has no extractable body text
- URL fetch timeout
- URL content type unsupported
- URL returned non-2xx status
- parsed page body is empty
- sitemap contains no usable pages
- vector backend unavailable
- embedding dimension mismatch

Every failed ingestion item should have a reason visible in run detail.

## Quality Bar

The pilot must keep the repository's quality policy:

- core modules maintain 100% test coverage
- provider integrations use official SDKs or stable documented APIs where
  practical
- optional cloud and local model dependencies stay outside the default install
  unless required for secret-free tests
- fake-client and contract tests cover cloud paths that require secrets
- live provider smoke tests are explicit opt-in and must not be required for
  default CI
- dependency inventory and supply-chain documentation remain current when a new
  SDK is added

## Acceptance Criteria

### Local startup

- A fresh clone can start the default local stack with documented commands.
- `/health` and `/console` are reachable.
- Postgres/pgvector is the default vector path.
- Qdrant can be selected only when configured and healthy.

### Document upload

- User can upload Markdown, TXT, PDF, and DOCX from Web Console.
- Text-based PDF produces extracted text and chunks.
- DOCX produces extracted body text and chunks.
- Encrypted or image-only PDF shows a clear degraded or failed reason.
- Unsupported file types are rejected before starting a misleading run.

### Website import

- User can import one public HTML page.
- User can import sitemap or explicit docs page list.
- Import stores source URL and extracted text provenance.
- Failed fetch or empty extraction is visible in run detail.
- No recursive crawler is required.

### Model support

- Ollama, LM Studio, and generic OpenAI-compatible providers appear as local
  options.
- OpenAI and OpenRouter appear as cloud options.
- Gemini supports health check and one answer smoke.
- Missing local runtime or API key shows `degraded` or `unavailable`, not a
  false-ready state.

### Retrieval and answer

- User can ask a question against the pilot knowledge base.
- Playground shows answer, citations, retrieval hits, chunk scores, and source
  references.
- If answer generation is unavailable, retrieval results remain visible.
- Citations point back to document version and chunk.

### Console experience

- Local Pilot Wizard can complete the full path without switching to CLI.
- Management pages remain available for inspection and debugging.
- Run history and run-item failure reasons are visible.
- Health page shows database, vector backend, and model status.

### Documentation

- README and README.zh-CN describe Local Pilot as the next product focus.
- The spec is linked from both READMEs.
- Enterprise pilot and enterprise connector work are described as roadmap, not
  the immediate pilot path.

## Implementation Phases

### Phase LP-1: Spec and documentation

- Commit this Local Pilot spec.
- Update README and README.zh-CN positioning.
- Create follow-up issues for implementation slices.

### Phase LP-2: Backend vertical slice

- Add website import boundary.
- Confirm upload path for Markdown, TXT, PDF, and DOCX.
- Add or tighten provider health checks.
- Add Gemini answer smoke.
- Expose required run/document/chunk/provider endpoints.

### Phase LP-3: Web Console vertical slice

- Add Local Pilot Wizard.
- Wire upload/import/model/run/playground path.
- Add health and failure-state UI.
- Keep normal management pages visible.

### Phase LP-4: Verification and release candidate

- Run default CI and coverage.
- Run local stack smoke.
- Run document upload smoke.
- Run single-page URL smoke.
- Run at least one local provider health check.
- Run Gemini smoke only when credentials are explicitly present.

## Initial Defaults

These defaults keep the first implementation narrow enough to ship:

- Default embedding behavior:
  - deterministic embedding remains the secret-free CI and smoke path
  - BGE is the recommended local semantic embedding path when optional local ML
    dependencies are installed
  - cloud embedding providers remain opt-in
- Default upload limit: 50 MB per file for the first Web Console path.
- Default sitemap/docs import cap: 25 pages per run.
- Bundled demo dataset: required, so the Local Pilot can be verified without
  internet access or cloud credentials.
