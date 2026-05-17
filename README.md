<p align="center">
  <img src="./assets/ragrig-icon.svg" alt="RAGRig logo" width="160" height="160">
</p>

<h1 align="center">RAGRig</h1>

<p align="center">
  <strong>An open-source RAG workbench you can self-host in two minutes — pipeline-grade, traceable, model-flexible.</strong>
</p>

<p align="center">
  <em>源栈: from scattered sources to traceable, model-ready knowledge.</em>
</p>

<p align="center">
  <a href="./README.zh-CN.md">中文</a> ·
  <a href="#try-it-in-30-seconds">Try it</a> ·
  <a href="#whats-in-the-box">Features</a> ·
  <a href="#how-ragrig-compares">vs. others</a> ·
  <a href="#deploy">Deploy</a>
</p>

---

RAGRig is for **small and medium-sized teams** who want to run their own
retrieval-augmented knowledge layer instead of paying per-seat for a hosted
chatbot. Every chunk, every retrieval hit, every model call is inspectable
— no black-box "chat with your docs."

## Try it in 30 seconds

```bash
git clone https://github.com/evilgaoshu/ragrig.git
cd ragrig
docker compose up
```

Open <http://localhost:8000>. You land in the Web Console with a `demo`
knowledge base already seeded from `examples/local-pilot/` — ask a
question immediately, no registration, no API key, no manual upload.

- Multi-stage build assembles the React console from source inside the image.
- Alembic migrations run on startup.
- The default answer provider is `deterministic-local` — no LLM credentials needed.
- Auth is **off** in demo mode. Flip `RAGRIG_AUTH_ENABLED=true` in `.env` before exposing the install.

Stop with `docker compose down`.

## What's in the box

### Ingest & retrieve
- Local files, Markdown / TXT, S3-compatible object storage, PDF / DOCX (text-layer).
- Parse → clean → chunk → embed → index → retrieve → rerank, each step inspectable in the console.
- pgvector by default, Qdrant as an optional backend (same retrieval contract).
- BGE / Ollama / LM Studio / OpenAI-compatible embedders side-by-side with OpenAI / OpenRouter / Gemini.

### Integrate
- **OpenAI-compatible API** — `POST /v1/chat/completions` and `GET /v1/models`. Point any OpenAI SDK at it. Use model `ragrig/<kb>[@provider:model]`.
- **MCP server** — `POST /mcp` exposes knowledge bases as MCP tools and resources for Claude Desktop, IDE agents, etc.
- **Webhooks in** — Confluence / Notion / Feishu (Lark) connectors, with HMAC-SHA256 signature verification on `POST /sources/{source}/webhook`.
- **Streaming** — REST answers and chat completions both support `stream=true` (SSE).

### Operate
- **Conversations** with multi-turn threading and 👍/👎 feedback at the turn level.
- **Usage dashboard** — tokens, cost, latency rollups (`GET /usage`, `GET /usage/timeseries`); per-workspace monthly budgets with email + webhook alerts and optional hard cap.
- **Workspace backup / restore** — `GET /admin/backup/{workspace_id}` produces a self-contained JSON dump; `POST /admin/restore` upserts idempotently.
- **Auth & RBAC** — password + API keys + sessions, RBAC (owner/admin/editor/viewer), per-workspace isolation. Optional LDAP / OIDC / MFA.
- **Production guardrails** — fake-reranker fallback disabled in production by default; `/health` reports policy.
- **Observability** — Prometheus `/metrics`, OpenTelemetry tracing, structured JSON logging.

## How RAGRig compares

| | RAGRig | LangChain / LlamaIndex | Dify / FastGPT | RAGFlow |
| --- | --- | --- | --- | --- |
| Shape | runnable product | code SDK | low-code app builder | RAG-focused product |
| Pipeline steps inspectable | first-class | build-your-own | partial (behind nodes) | first-class |
| Answer → chunk → doc version → run traceability | built-in | DIY | partial | built-in |
| OpenAI-compatible API + MCP | both built-in | N/A | OpenAI-compat | partial |
| Multi-tenant workspace + RBAC | built-in | N/A | built-in | built-in |
| Default vector store | pgvector (your Postgres) | none | varies | ElasticSearch |
| License | Apache 2.0 | MIT / Apache | Apache 2.0 (with notice) | Apache 2.0 |

In one line: **a framework gives you bricks, a chatbot builder gives you a
black box, RAGRig gives you an inspectable pipeline you can hand to your
team.**

## Who it's for

**Fits well:**
- A team of 2–50 standing up their own internal docs / handbook / support knowledge layer.
- Anyone who needs to point a real product (or agent / IDE) at a private knowledge base via OpenAI-compatible or MCP APIs.
- Self-hosters who care about traceability — "why did the model say that?" → click through chunk → document version → pipeline run.

**Not optimized for:**
- One-shot personal chat-with-pdf — try a desktop tool, this is overkill.
- Hundred-million-document enterprise indexing — pgvector is the default; you'll outgrow it before RAGRig itself.
- No-code workflow building with branching LLM logic — use Dify if that's your need.

## Deploy

### Docker Compose (recommended)

`docker compose up` from the Quick Start above is the supported path. It
runs Postgres + pgvector + the app, executes migrations, and auto-seeds
the demo KB.

**If ports 8000 or 5432 are taken**, set `APP_HOST_PORT=18000` and
`DB_HOST_PORT=15433` in `.env`.

**Optional sidecars** (MinIO/S3, Qdrant, Samba/WebDAV/SFTP fileshare smoke,
local-LLM answer smoke) — env-var reference in
[docs/operations/optional-services.md](./docs/operations/optional-services.md).

### Vercel Preview + Supabase

For an online product preview, RAGRig can run as a Vercel Preview backed
by Supabase Postgres. Docker is still the recommended path for trying it
locally. Required env:

```text
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/postgres?sslmode=require
VECTOR_BACKEND=pgvector
APP_ENV=preview
```

Migrate from a trusted local/CI environment first, then smoke the deployment:

```bash
DATABASE_URL='postgresql://USER:PASSWORD@HOST:PORT/postgres?sslmode=require' \
DB_RUNTIME_HOST='HOST' DB_HOST_PORT='PORT' \
uv run alembic upgrade head

VERCEL_PREVIEW_URL='https://your-preview-url.vercel.app' make vercel-preview-smoke
```

Model credentials remain optional — no model credentials are required for
startup. See
[EVI-130](./docs/specs/EVI-130-vercel-preview-supabase.md) for the full
contract.

### 10-Minute Local Pilot Demo

For an evidence-backed end-to-end smoke (preflight + container build +
console walk-through) the legacy targets are still wired:

```bash
make pilot-docker-preflight   # check Docker is healthy
make pilot-up                 # docker compose up -d db app
make pilot-docker-smoke       # JSON evidence pack
make pilot-down               # tear down
```

Model configuration is optional for startup. The demo seed uses the
`deterministic-local` provider and answers without any external model.
Sample content used by the seed lives at:

- `examples/local-pilot/company-handbook.md`
- `examples/local-pilot/support-faq.md`
- `examples/local-pilot/demo-questions.json`

To answer with a real model, run Ollama or LM Studio on the host and point
`RAGRIG_ANSWER_BASE_URL` at it, or set `OPENAI_API_KEY` /
`OPENROUTER_API_KEY` / `GEMINI_API_KEY` in your `.env`.

## Configure for production

Before exposing your install beyond a single trusted machine:

1. **Turn auth on.** Set `RAGRIG_AUTH_ENABLED=true` and override
   `RAGRIG_AUTH_SECRET_PEPPER` with a long random secret.
2. **Keep the fake-reranker guard on.** Production blocks the
   deterministic fake reranker fallback by default. Only set
   `RAGRIG_ALLOW_FAKE_RERANKER=true` for explicitly accepted demos.
3. **Decide on connectors.** If you wire Confluence / Notion / Feishu
   webhooks, set a per-source secret and verify HMAC-SHA256 on
   `POST /sources/{source}/webhook`.
4. **Set a usage budget.** `PUT /budgets` caps monthly spend per
   workspace and routes alerts to email + your webhook.
5. **Back up.** `GET /admin/backup/{workspace_id}` is a self-contained
   JSON dump; restore is idempotent.

Full RBAC / member management / API-key reference:
[docs/operations/auth.md](./docs/operations/auth.md).

## Web Console

Operator surface. Knowledge bases, sources, pipeline runs, document /
chunk preview, Playground for retrieval + answer with citations, usage
dashboard, conversations, admin status, backup/restore.

The current production console ships from the React app under
`/app`. The image below is the original prototype mockup retained for
spec context:

<p align="center">
  <img src="./docs/prototypes/web-console/ragrig-web-console-prototype.png" alt="RAGRig Web Console prototype" width="860">
</p>

## Develop & contribute

```bash
make sync                       # install dependencies via uv
cp .env.example .env            # local env
docker compose up --build -d db # just the database
make migrate
make db-check
make run-web                    # http://localhost:8000/console
```

Quick local smoke loop:

```bash
make ingest-local
make index-local
make retrieve-check QUERY="RAGRig Guide"
make local-pilot-smoke
```

Frontend (React + Vite) lives in `frontend/`; `npm run dev` from there
during console work. The Vite build outputs into
`src/ragrig/static/dist` so the FastAPI app serves it under `/app`.

**Full verification catalog** (default suite, browser e2e, nightly
evidence, supply-chain audit, live-provider smokes):
[docs/operations/verification.md](./docs/operations/verification.md).

## Architecture

```mermaid
flowchart LR
    inputs["Inputs<br/>files, URLs, object storage, docs, DB"]
    pipeline["Pipeline<br/>parse, clean, chunk, embed, index"]
    core["RAGRig core<br/>KB, docs, versions, chunks, runs, audit"]
    providers["Provider registry<br/>LLM, embedding, reranker, parser"]
    vectors["Vector backends<br/>pgvector default, Qdrant optional"]
    console["Web Console<br/>configure, preview, health, playground"]
    answer["Retrieval + Answer<br/>hits, citations, diagnostics"]

    inputs --> pipeline
    providers --> pipeline
    pipeline --> core
    core --> vectors
    vectors --> answer
    core --> console
    providers --> console
    answer --> console
```

| Layer | Current / Default | Optional / Roadmap |
| --- | --- | --- |
| App / API | Python, FastAPI | MCP / export surfaces |
| Web Console | React (Vite) served by FastAPI | richer workflow UI |
| Metadata DB | PostgreSQL | SQLite for smoke/test paths |
| Vector backend | pgvector | Qdrant |
| Local models | Ollama, LM Studio, OpenAI-compatible endpoints | vLLM, llama.cpp, Xinference, LocalAI |
| Cloud models | OpenAI, OpenRouter, Gemini | Vertex AI, Bedrock, Azure OpenAI, Anthropic catalog |
| Inputs | local files, Markdown / TXT, S3-compatible | PDF / DOCX upload, URLs, enterprise connectors |
| Quality | pytest, coverage, contract tests | opt-in live provider smoke |

## Documentation

- **Operations:**
  [auth & RBAC](./docs/operations/auth.md) ·
  [verification commands](./docs/operations/verification.md) ·
  [optional services](./docs/operations/optional-services.md) ·
  [supply chain](./docs/operations/supply-chain.md) ·
  [dependency inventory](./docs/operations/dependency-inventory.md)
- **Specs:**
  [Local Pilot](./docs/specs/ragrig-local-pilot-spec.md) ·
  [MVP](./docs/specs/ragrig-mvp-spec.md) ·
  [Web Console](./docs/specs/ragrig-web-console-spec.md) ·
  [fake reranker guard](./docs/specs/EVI-129-fake-reranker-production-guard.md) ·
  [Vercel preview + Supabase](./docs/specs/EVI-130-vercel-preview-supabase.md)
- **Roadmap:** [docs/roadmap.md](./docs/roadmap.md)

## Repository layout

```text
.
├── assets/             # Project icon
├── docs/               # Specs, operations docs, prototypes
├── frontend/           # React + Vite Web Console
├── scripts/            # Smoke, ops, and verification commands
├── src/ragrig/         # RAGRig application code
├── tests/              # Unit and contract tests
├── docker-compose.yml  # Local Postgres/pgvector and optional services
├── pyproject.toml      # Python dependencies and tooling
└── Makefile            # Common developer commands
```

## License

RAGRig is licensed under the Apache License 2.0. See [LICENSE](./LICENSE).
