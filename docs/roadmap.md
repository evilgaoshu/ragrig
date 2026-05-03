# RAGRig Roadmap

This roadmap captures the first product shape for RAGRig. It is intentionally small enough to ship as an open-source foundation before expanding into a full knowledge governance platform.

## Phase 0: Project Foundation

- Define project positioning, icon, README, license, and contribution guidelines.
- Document the initial architecture and RAG pipeline concepts.
- Choose the first implementation stack and local development workflow.

## Phase 1: Minimal RAG Pipeline

Phase 1 starts with a scaffold-only checkpoint before the first end-to-end ingestion loop lands.

### Phase 1a: Scaffold and Developer Workflow

- Commit the Python/FastAPI project skeleton.
- Ship Docker Compose for app + PostgreSQL/pgvector.
- Add typed configuration, env example, lint/format/test commands, and minimal health-check tests.
- Keep ingestion, parsing, chunking, embedding, and retrieval as later follow-up issues.

### Phase 1b: Local Ingestion Foundation

- Ingest explicit local fixture directories into a named knowledge base.
- Parse Markdown and plain text into real `document_versions`.
- Record pipeline runs, file-level skip reasons, and file-level failures.
- Keep host-side Compose DB port override support for shared-machine verification.
- Defer chunking, embedding, retrieval, PDF, and richer connectors to later issues.

### Phase 1c: Retrieval Loop Completion

- Add deterministic cleaning and chunking.
- Generate embeddings.
- Index into pgvector.
- Provide a retrieval API with citations.

### Phase 1d: Source And Format Expansion

- Add PDF, DOCX, PPTX, and XLSX parsing.
- Expand source connectors beyond local directories.

## Phase 2: Governance Core

- Add knowledge base, document, chunk, and pipeline-run versioning.
- Add metadata schemas and validation.
- Add document-level and chunk-level access control.
- Enforce pre-retrieval permission filtering.
- Add audit events for ingestion, indexing, retrieval, and deletion.

## Phase 3: Workflow and Connector Expansion

- Add a lightweight DAG runner for ingestion workflows.
- Support retries, resumable runs, dry-run mode, and failure queues.
- Add SMB, NFS, S3, database, Google Drive, wiki, WPS, and OnlyOffice integrations.
- Add exports to S3, NFS, databases, Markdown, JSONL, and Parquet.

## Phase 4: Evaluation and Operations

- Add golden question sets.
- Track retrieval quality, citation quality, refusal behavior, latency, and cost.
- Compare pipeline and model changes before reindexing production knowledge bases.
- Add Docker Compose deployment, backup, restore, and upgrade guides.

## Non-goals for the First Release

- Full office-suite editing.
- General-purpose agent workflow automation.
- A hosted SaaS control plane.
- Building a custom vector database.
