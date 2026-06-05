# RAGRig Web Console

This directory contains the production Web Console served by the FastAPI app.
The legacy prototype files under `src/ragrig/web_console.*` are not the active
frontend.

## Development

```bash
npm ci
npm run dev
```

The Vite dev server proxies API calls to `http://localhost:8000`. Start the
backend separately from the repository root:

```bash
make run-web
```

## Build Coupling

The console is intentionally coupled to the FastAPI package:

- `frontend/vite.config.ts` writes production assets to
  `../src/ragrig/static/dist`.
- `Dockerfile` builds this frontend in a Node stage, then copies the compiled
  assets into `src/ragrig/static/dist` in the Python runtime image.
- `src/ragrig/routers/frontend.py` serves those assets under the app routes.

When changing routes or static asset behavior, verify both the Vite dev server
and the FastAPI-served production build.

## Checks

```bash
npm run lint
npm run test:run
npm run build
```

For a backend-integrated smoke from the repository root:

```bash
make web-check
```
