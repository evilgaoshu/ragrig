# EVI-130 — Vercel Preview + Supabase Database

## Goal

Provide a Vercel Preview environment for RAGRig that can serve the FastAPI app and
Web Console while using Supabase Postgres as the remote metadata database.

## Deployment Shape

- Vercel Preview runs RAGRig through the Python function entrypoint at `api/index.py`.
- `vercel.json` rewrites all requests to that function so `/health`, `/console`, and
  API routes keep the same paths as the local Docker stack.
- Runtime dependencies are exposed through `requirements.txt` for the Vercel Python
  builder.
- Supabase is configured through environment variables only. No Supabase URL,
  password, service key, or model credential is committed.

## Required Vercel Preview Environment

Set these in Vercel Project Settings for the Preview target:

```text
DATABASE_URL=postgresql://USER:PASSWORD@HOST:PORT/postgres?sslmode=require
VECTOR_BACKEND=pgvector
APP_ENV=preview
```

Equivalent Vercel CLI setup:

```bash
vercel env add DATABASE_URL preview
vercel env add VECTOR_BACKEND preview
vercel env add APP_ENV preview
```

For local migration and database validation against Supabase, also set:

```text
DB_RUNTIME_HOST=HOST
DB_HOST_PORT=PORT
```

`DB_RUNTIME_HOST` and `DB_HOST_PORT` are needed because the existing migration and
database-check path uses `runtime_database_url`, which can rewrite the host for
Docker/local workflows. Vercel runtime requests use `DATABASE_URL` directly through
SQLAlchemy.

## Supabase Bootstrap

Run the database bootstrap from a trusted local or CI environment with the same
Supabase connection details:

```bash
DATABASE_URL='postgresql://USER:PASSWORD@HOST:PORT/postgres?sslmode=require' \
DB_RUNTIME_HOST='HOST' \
DB_HOST_PORT='PORT' \
uv run alembic upgrade head
```

Then verify:

```bash
DATABASE_URL='postgresql://USER:PASSWORD@HOST:PORT/postgres?sslmode=require' \
DB_RUNTIME_HOST='HOST' \
DB_HOST_PORT='PORT' \
make db-check
```

## Preview Smoke

After Vercel creates a Preview deployment, verify it with:

```bash
VERCEL_PREVIEW_URL='https://your-preview-url.vercel.app' make vercel-preview-smoke
```

The smoke checks `/health`, `/console`, and `/local-pilot/status`. It intentionally
does not call model providers.

## Model Boundary

Vercel Preview is allowed to boot without LLM, embedding, or reranker credentials:
no model credentials are required for startup. Provider health and answer smoke are
readiness checks, not deployment blockers.

## Acceptance Criteria

- `/health` is available on a Vercel Preview URL.
- `/console` is available on the same Preview URL.
- Supabase-backed requests use `DATABASE_URL`.
- Migration is run explicitly before relying on the Preview database.
- Missing model credentials do not block app startup.
