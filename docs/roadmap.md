# RAGRig Roadmap

This roadmap reflects the current state of the project as of May 2026. Completed work is marked. Open items represent active or upcoming scope.

---

## Phase 0: Project Foundation — Done

- Defined project positioning, README, license, and contribution guidelines.
- Documented initial architecture and RAG pipeline concepts.
- Chose implementation stack (Python/FastAPI, PostgreSQL/pgvector) and local development workflow.
- Published MVP spec and supply chain policy.

---

## Phase 1: Minimal RAG Pipeline — Done

### Phase 1a: Scaffold and Developer Workflow

- Python/FastAPI project skeleton with typed configuration and env example.
- Docker Compose for app and PostgreSQL/pgvector.
- Lint, format, test, and coverage commands via Makefile.
- Health-check tests and GitHub Actions baseline CI.

### Phase 1b: Local Ingestion Foundation

- Ingest local fixture directories into named knowledge bases.
- Parse Markdown and plain text into `document_versions`.
- Record pipeline runs, file-level skip reasons, and file-level failures.
- Host-side Compose DB port override for shared-machine verification.

### Phase 1c: Retrieval Loop Completion

- Deterministic cleaning and chunking pipeline.
- Embedding generation indexed into pgvector.
- Hybrid retrieval: dense vector + lexical fusion + optional reranking.
- Retrieval API with per-result `rank_stage_trace` for full pipeline transparency.
- Citations linking answers back to source chunks and document versions.

### Phase 1d: Source and Format Expansion

- PDF, DOCX, PPTX, and XLSX parsing with OCR degradation gate.
- S3-compatible source connector.
- Fileshare source plugin (SMB/NFS via paramiko/smbprotocol).
- Object storage sink plugin.
- Optional Qdrant vector backend alongside pgvector.

---

## Phase 2: Governance Core — Done

- Document-level and chunk-level access control with pre-retrieval permission filtering.
- ACL policy regression hardening and explain-mode audit.
- Audit trail for ingestion, indexing, retrieval, and deletion events (EVI-105).
- Metadata schema validation across pipeline stages.
- Pipeline-run and document-version versioning.

---

## Phase 3: Workflow and Connector Expansion — Substantially Done

**Done:**
- Lightweight DAG runner for ingestion workflows (`workflows/ingestion_dag.py`).
- Retries, resumable runs, dry-run mode, and failure queues.
- Operational console: source config drafts, dry-run ingestion, retry/resume UI.
- Enterprise connector workflow stubs.
- Google Workspace source connector (pilot, contract-aligned).
- S3 source connector fully wired into console ingest flow.
- Database source connectors (PostgreSQL, MySQL read path).
- Parquet export dependency in place (`pyarrow`).

**Open:**
- Markdown, JSONL, and NFS export sinks.
- Wiki, WPS, and OnlyOffice connectors.

---

## Phase 4: Evaluation and Operations — Substantially Done

**Done:**
- Docker Compose deployment, backup, restore, and upgrade smoke (EVI-108).
- Retrieval benchmark integrity guard with CI artifact and PR summary badge.
- Evaluation baseline: schema compatibility, manifest canonicalization, hash-mismatch fixes.
- Sanitizer drift history CI artifact and console badge.
- Answer live smoke diagnostics with JSON report and CI badge.
- Understanding export diff summary and artifact retention.
- Full evaluation comparison workflow: before/after reindex diff report.
- Knowledge map / cross-document understanding API, Web Console panel, and deterministic smoke artifact.
- Cost and latency tracking across pipeline and model changes.

**Open:**
- Authored golden question sets for domain-specific retrieval quality regression.

---

## Local Pilot — Active

This section was not in the original roadmap. It emerged to give contributors and operators a fast diagnostic path without needing a full production deployment.

**Done:**
- Dockerized local pilot environment.
- Interactive console wizard for local setup.
- Model provider smoke tests (Ollama, LM Studio, OpenAI-compatible).
- S3 ingest console flow.
- Go/no-go evidence pack generation for CI.
- SQLite-backed local storage with ResourceWarning audit and cleanup.
- Google Workspace pilot diagnostics parity with production contract.

**Open:**
- Automated nightly evidence smoke in CI.

---

## Non-goals for the First Release

- Full office-suite editing.
- General-purpose agent workflow automation.
- A hosted SaaS control plane.
- Building a custom vector database.
