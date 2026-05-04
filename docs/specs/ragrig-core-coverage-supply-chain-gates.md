# RAGRig Core Coverage And Supply Chain Gates

Date: 2026-05-04
Status: Accepted executable quality gate

## Goal

Turn the local-first quality policy into commands that a fresh clone can run without cloud accounts, secrets, GPUs, model downloads, or optional SDK installs.

## Core Coverage Gate

The hard coverage scope for `make coverage` is:

- `src/ragrig/db`
- `src/ragrig/repositories`
- `src/ragrig/ingestion`
- `src/ragrig/parsers`
- `src/ragrig/chunkers`
- `src/ragrig/embeddings`
- `src/ragrig/indexing`
- `src/ragrig/retrieval.py`
- `src/ragrig/config.py`
- `src/ragrig/health.py`

The gate is line coverage at 100% for this scope.

### Explicit Omits

The coverage config omits these paths on purpose:

- `src/ragrig/main.py`: FastAPI app wiring and route composition, not core ingestion/indexing/retrieval logic.
- `src/ragrig/web_console.py`: Web Console presentation adapter, outside the hard scope for this issue.
- `src/ragrig/cleaners/*`: placeholder package, no shipped behavior yet.
- `src/ragrig/vectorstore/*`: placeholder package, no shipped behavior yet.

Generated Alembic migration files are not included in the `ragrig` package coverage source and remain documented but outside the hard gate.

## Command Surface

- `make test`: full default test suite.
- `make coverage`: full suite plus the 100% hard-scope coverage gate and `coverage.json` artifact.
- `make licenses`: license policy check against installed dependencies.
- `make sbom`: generate a CycloneDX JSON SBOM for the local environment.
- `make audit`: vulnerability audit of the local environment.
- `make audit-dry-run`: offline/degraded audit path that verifies dependency collection without contacting a vulnerability service.
- `make dependency-inventory`: regenerate `docs/operations/dependency-inventory.md`.
- `make supply-chain-check`: run license check, SBOM generation, and vulnerability audit together.

## Optional Dependency Guard

Optional SDK groups are declared in `pyproject.toml` but intentionally left empty until each plugin is designed and approved. Core modules must never top-level import:

- local heavy ML SDKs such as `ollama`, `FlagEmbedding`, `sentence-transformers`, or `torch`
- cloud SDKs such as `google-genai`, `boto3`, `openai`, `cohere`, or `voyageai`
- optional vector/database SDKs such as `qdrant-client`, `pymilvus`, `weaviate-client`, or `opensearch-py`
- optional document/OCR SDKs such as `docling`, `unstructured`, or `paddleocr`

`tests/test_import_guard.py` enforces this boundary.

## Supply Chain Policy

The executable supply-chain gate currently enforces:

- fail the license check if installed packages match GPL, AGPL, SSPL, or source-available identifiers
- ignore the local editable `ragrig` package in license enforcement so the check focuses on third-party supply chain
- generate SBOM and audit artifacts under `docs/operations/artifacts/`

## Offline And Degraded Behavior

- `make licenses` and `make sbom` are fully local once dependencies are installed.
- `make audit` depends on network access to the configured vulnerability service.
- If the environment is offline, run `make audit-dry-run` to prove dependency collection still works, then record the audit as blocked by network access.
