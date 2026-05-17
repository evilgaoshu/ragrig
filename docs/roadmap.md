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

## Phase 3: Workflow and Connector Expansion — Done

**Done:**
- Lightweight DAG runner for ingestion workflows (`workflows/ingestion_dag.py`).
- Retries, resumable runs, dry-run mode, and failure queues.
- Operational console: source config drafts, dry-run ingestion, retry/resume UI.
- Enterprise connector workflow stubs.
- Google Workspace source connector (pilot, contract-aligned).
- S3 source connector fully wired into console ingest flow.
- Database source connectors (PostgreSQL, MySQL read path).
- Parquet export dependency in place (`pyarrow`).
- Markdown, JSONL, and NFS export sinks (unified `sink.filesystem` connector writing to any local path, including NFS mount points).

**Done (P3 SMB focus, May 2026):**
- **P3a — OpenAI-compatible REST + MCP server + SSE streaming**: `POST /v1/chat/completions`, `GET /v1/models`, `POST /mcp` (`initialize`/`tools/list`/`tools/call`/`resources/list`); model identifier syntax `ragrig/<kb>[@provider:model]`; `stream=true` on retrieval + chat-completion paths.
- **P3b — Multi-turn conversations + feedback loop + citation highlighting**: `conversations`, `conversation_turns`, `answer_feedback` tables; `_build_contextual_query` folds prior turns into retrieval; `char_start/char_end/page_number` spans propagated end-to-end through `RetrievalResult`, `EvidenceChunk`, and `Citation`.
- **P3c — Usage + cost dashboard with budget alerts**: `usage_events` and `budgets` tables; `record_usage_events`, `aggregate_usage`, `daily_timeseries`, `evaluate_budget` core APIs; `/usage`, `/usage/timeseries`, `/budgets`, `/admin/usage/evaluate` REST endpoints; per-workspace monthly limits with latched email + webhook alerts and optional `hard_cap`.
- **P3d — Confluence Cloud + Notion + Feishu / Lark Wiki connectors**: pluggable `HttpTransport` scanners + per-source `/sources/{source}/webhook` receiver with HMAC-SHA256 signature verification.
- **P3e — Admin console + workspace backup/restore**: `/admin/status` counts; `dump_workspace` / `restore_workspace` JSON round-trip (upsert by id, idempotent); `/admin/backup/{workspace_id}` and `/admin/restore` endpoints.

**Open:**
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

**Done:**
- Authored golden question sets for domain-specific retrieval quality regression (retrieval, edge-cases, multi-doc fixture sets with 35 questions across hit/miss/lexical/semantic/adversarial tags).

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
- Automated nightly evidence smoke in CI (full EVI-110 evidence workflow).

---

## Authentication and Multi-Tenant Isolation — In Progress

**Done:**
- `workspaces`, `users`, `workspace_memberships`, `api_keys`, `user_sessions` DB schema and migrations.
- HMAC-SHA256 API key hashing with prefix lookup and optional pepper.
- Session token create / verify / revoke with expiry.
- Password hashing (bcrypt) and `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` endpoints.
- `RAGRIG_AUTH_ENABLED` config flag: when `false`, all requests fall through to the default workspace for local dev.
- `AuthContext` FastAPI dependency; `workspace_id` derived from verified token (not silently defaulted).
- `knowledge_bases` scoped to `workspace_id` with per-workspace unique constraint.
- Frontend login page with sign-in / create-account tabs; `AuthProvider`, `ProtectedRoute`, token stored in localStorage.

**Done:**
- Role-based write guards on mutating API routes (`require_write_auth` for editor+, `require_admin_auth` for admin+).
- User management API (`GET /auth/workspace/members`, `PATCH /auth/workspace/members/{id}`, `DELETE /auth/workspace/members/{id}`).
- `AuthContext.role` resolved from `WorkspaceMembership` on every request.

**Done:**
- `workspace_id` propagated to hot retrieval tables (`chunks`, `embeddings`); direct `Chunk.workspace_id` filter added to all retrieval query paths (`build_embedding_base_statement`, SQL and Python distance search, available-profiles probe).
- Admin invitation flow: `POST/GET/DELETE /auth/workspace/invitations`; `invitation_token` on register; `RAGRIG_OPEN_REGISTRATION` flag for closed-registration mode.

**Done (P0 enterprise security):**
- **LDAP authentication**: `POST /auth/login/ldap`; configurable server URL, bind DN, user filter, TLS, group mapping, default role; auto-provisions local user on first login.
- **OIDC/OAuth2**: `GET /auth/oidc/authorize` + `GET /auth/oidc/callback`; full authorization-code flow; discovery document; ID token validation via joserfc; auto-provisions user from claims.
- **MFA / TOTP**: `POST /auth/mfa/setup` (provisioning URI + QR code + backup codes), `POST /auth/mfa/confirm`, `POST /auth/mfa/disable`, `POST /auth/mfa/challenge`; login returns `mfa_required: true` with a scoped pending token when MFA is enrolled.
- **Audit log query API**: `GET /audit/events` (admin-scoped, workspace-filtered, supports event_type/actor/since/until/run_id/offset/limit); `workspace_id` column added to `audit_events` migration 0014.
- **PII redaction**: `ragrig.pii` module; regex-based detection of email, phone, SSN, credit card, IP, NI; hooked into indexing pipeline via `pii_redaction=True`; enabled per-request via `RAGRIG_PII_REDACTION_ENABLED`.
- **Right to erasure**: `DELETE /auth/users/me` (self), `DELETE /auth/workspace/members/{id}/erase` (owner-only); revokes all sessions and API keys, removes memberships, anonymises PII in user record.

**Open:**
- Email delivery for invitation links (requires SMTP / transactional email provider integration).

---

## Non-goals for the First Release

- Full office-suite editing.
- General-purpose agent workflow automation.
- A hosted SaaS control plane.
- Building a custom vector database.
