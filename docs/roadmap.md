# RAGRig Roadmap

This roadmap captures the first product shape for RAGRig. It is intentionally small enough to ship as an open-source foundation before expanding into a full knowledge governance platform.

## Phase 0: Project Foundation

- Define project positioning, icon, README, license, and contribution guidelines.
- Document the initial architecture and RAG pipeline concepts.
- Choose the first implementation stack and local development workflow.

## Phase 1: Minimal RAG Pipeline

- Ingest local files and folders.
- Parse Markdown, plain text, PDF, DOCX, PPTX, and XLSX.
- Run configurable cleaning and normalization steps.
- Create chunks with metadata and stable source references.
- Generate embeddings.
- Index into Qdrant and pgvector.
- Provide a retrieval API with citations.

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
