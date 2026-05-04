# RAGRig Dependency Inventory

Generated from `pyproject.toml` by `python -m scripts.dependency_inventory`.

## Core Runtime Dependencies

| Package | Class | Governance |
| --- | --- | --- |
| `alembic` | core runtime | default local-first path |
| `fastapi` | core runtime | default local-first path |
| `pgvector` | core runtime | default local-first path |
| `pydantic-settings` | core runtime | default local-first path |
| `psycopg[binary]` | core runtime | default local-first path |
| `sqlalchemy` | core runtime | default local-first path |
| `uvicorn[standard]` | core runtime | default local-first path |

## Development And Quality Gate Dependencies

| Package | Class | Governance |
| --- | --- | --- |
| `cyclonedx-bom` | dev / quality gate | test, lint, coverage, or supply-chain tooling |
| `httpx` | dev / quality gate | test, lint, coverage, or supply-chain tooling |
| `pip-audit` | dev / quality gate | test, lint, coverage, or supply-chain tooling |
| `pip-licenses` | dev / quality gate | test, lint, coverage, or supply-chain tooling |
| `pytest` | dev / quality gate | test, lint, coverage, or supply-chain tooling |
| `pytest-cov` | dev / quality gate | test, lint, coverage, or supply-chain tooling |
| `ruff` | dev / quality gate | test, lint, coverage, or supply-chain tooling |

## Planned Optional Plugin SDK Groups

The extras are intentionally empty in `pyproject.toml` today. They reserve install boundaries without pulling real cloud, OCR, or heavy ML SDKs into the default environment.

| Extra group | Category | Preferred SDKs | Governance |
| --- | --- | --- | --- |
| `cloud-llm` | official cloud SDKs | `google-genai`, `boto3`, `openai`, `cohere`, `voyageai` | Cloud providers stay optional and must not affect fresh-clone tests or local indexing defaults. |
| `cloud-embeddings` | cloud embedding SDKs | `voyageai`, `cohere`, `openai`, `google-genai` | Use only behind explicit plugin extras and document network, auth, and cost metadata. |
| `doc-parsers` | document / OCR parsers | `pypdf`, `python-docx`, `docling`, `unstructured`, `paddleocr` | Large parser stacks stay optional because they pull native deps, models, or extra licenses. |
| `local-ml` | local runtime / heavy ML | `ollama`, `FlagEmbedding`, `sentence-transformers`, `torch` | Never import from core modules. Install only for plugin or local model work. |
| `vectorstores` | vector database SDKs | `qdrant-client`, `pymilvus`, `weaviate-client`, `opensearch-py` | Keep pgvector as the core default. Alternate vector stores must remain optional plugins. |

## Governance Rules

- Core runtime must stay local-first and secret-free for `make test` and `make coverage`.
- Optional SDKs must not be imported from core module top level.
- Heavy ML, cloud, enterprise connector, and document-suite dependencies belong in optional extras only.
- Default supply-chain review uses `make licenses`, `make sbom`, and `make audit`.

