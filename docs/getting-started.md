# Getting Started

Use this guide when you want the shortest path from a fresh clone to a running
RAGRig instance.

## 1. Choose A Path

| Goal | Use | Requires |
| --- | --- | --- |
| Try the product locally | Docker Compose | Docker 24+, port `8000`, 4 GB RAM available to Docker |
| Check local prerequisites | `make doctor` | `python3` on PATH; reports Docker, `uv`, Node.js, port, and memory status |
| Develop backend code | `uv` + Docker DB | `uv`, Docker, Python managed by `uv` |
| Develop frontend code | Vite dev server | Node.js 22+, npm, backend on `localhost:8000` |
| Avoid local setup | Hosted demo | Browser only |

Hosted demo:

- URL: <https://demo.ragrig.dev/>
- Read-only login: `demo@ragrig.dev` / `ragrig-demo-readonly`

## 2. Docker Quickstart

The first build compiles the React console and syncs Python dependencies inside
the image. Expect roughly 3-8 minutes on a cold machine.

```bash
git clone https://github.com/evilgaoshu/ragrig.git
cd ragrig
make doctor
make init
```

`make init` writes `.env` from `.env.example` and generates a local
`RAGRIG_POSTGRES_PASSWORD`. If `.env` already exists, it leaves the file alone;
use `make init PYTHON=python` if your platform exposes Python as `python`.

If you prefer manual setup, copy the template and set a deployment-specific
password yourself:

```text
RAGRIG_POSTGRES_PASSWORD=replace-me-with-a-local-secret
```

Start the app:

```bash
docker compose up
```

Open <http://localhost:8000>. The app seeds a `demo` knowledge base from
`examples/local-pilot/`.

Stop it:

```bash
docker compose down
```

If port `8000` is occupied:

```bash
echo "APP_HOST_PORT=18000" >> .env
docker compose up
```

Then open <http://localhost:18000>.

## 3. Backend Development

Install `uv`:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
# or: brew install uv
```

Sync dependencies and start only the database:

```bash
make sync
make init
docker compose up --build -d db
make migrate
make db-check
make run-web
```

Open <http://localhost:8000>.

Common backend checks:

```bash
make lint
make test-fast
make web-check
```

## 4. Frontend Development

Run the backend first with `make run-web`, then start Vite:

```bash
cd frontend
npm ci
npm run dev
```

The Vite dev server proxies API calls to `http://localhost:8000`. Production
builds write compiled assets into `src/ragrig/static/dist`, where FastAPI serves
them.

Common frontend checks:

```bash
cd frontend
npm run lint
npm run test:run
npm run build
```

## 5. First Smoke Loop

After the backend is running:

```bash
make ingest-local
make index-local
make retrieve-check QUERY="RAGRig Guide"
make local-pilot-smoke
```

Artifacts land in `docs/operations/artifacts/`.

## 6. What To Read Next

- [Architecture overview](./architecture.md) for component boundaries and data flow.
- [Verification commands](./operations/verification.md) for smoke and CI checks.
- [Specs index](./specs/README.md) for feature specs by topic.
- [Contributing](../CONTRIBUTING.md) for where to add new parsers, providers, routes, and settings.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `docker compose up` fails immediately | Confirm `.env` has `RAGRIG_POSTGRES_PASSWORD` |
| `make init` says `.env` already exists | The file was preserved; edit it manually or run `python3 -m scripts.bootstrap --force` intentionally |
| `make doctor` cannot find Python | Run `PYTHON=python make doctor` if your platform uses `python` instead of `python3` |
| Port conflict | Set `APP_HOST_PORT=18000` in `.env` |
| `make sync` says `uv` is missing | Install `uv` from the Backend Development section |
| Frontend dev server API calls fail | Confirm `make run-web` is running on `localhost:8000` |
| First Docker build feels slow | Cold build compiles Node and Python dependencies; reruns should reuse layers |
