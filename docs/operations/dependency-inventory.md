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
| `python-multipart` | core runtime | default local-first path |
| `pyyaml` | core runtime | default local-first path |
| `pypdf` | core runtime | default local-first path |
| `python-docx` | core runtime | default local-first path |

## Development And Quality Gate Dependencies

| Package | Class | Governance |
| --- | --- | --- |
| `cyclonedx-bom` | dev / quality gate | test, lint, coverage, or supply-chain tooling |
| `httpx` | dev / quality gate | test, lint, coverage, or supply-chain tooling |
| `lxml` | dev / quality gate | test, lint, coverage, or supply-chain tooling |
| `pip-audit` | dev / quality gate | test, lint, coverage, or supply-chain tooling |
| `pip-licenses` | dev / quality gate | test, lint, coverage, or supply-chain tooling |
| `pytest` | dev / quality gate | test, lint, coverage, or supply-chain tooling |
| `pytest-cov` | dev / quality gate | test, lint, coverage, or supply-chain tooling |
| `ruff` | dev / quality gate | test, lint, coverage, or supply-chain tooling |

## Planned Optional Plugin SDK Groups

Optional extras keep cloud, storage, parsing, and heavy ML SDKs behind explicit
install boundaries instead of pulling them into the default local-first environment.

| Extra group | Category | Preferred SDKs | Governance |
| --- | --- | --- | --- |
| `cloud-aws` | official cloud SDKs | `boto3` | Use the official AWS SDK behind explicit Bedrock and AWS storage plugins. |
| `cloud-cohere` | official cloud SDKs | `cohere` | Use only behind explicit Cohere model and rerank plugins. |
| `cloud-google` | official cloud SDKs | `google-genai`, `google-cloud-aiplatform` | Use official Gemini and Vertex SDKs behind explicit cloud model plugins. |
| `cloud-jina` | cloud embedding / rerank API | `Jina HTTP API` | Prefer official SDKs when available; otherwise isolate HTTP clients in plugins. |
| `cloud-openai` | official cloud SDKs | `openai` | Use the official OpenAI SDK behind explicit cloud model plugins. |
| `cloud-voyage` | official cloud SDKs | `voyageai` | Use only behind explicit Voyage embedding and rerank plugins. |
| `cloud-llm` | official cloud SDKs | `google-genai`, `boto3`, `openai`, `cohere`, `voyageai` | Cloud providers stay optional and must not affect fresh-clone tests or local indexing defaults. |
| `cloud-embeddings` | cloud embedding SDKs | `voyageai`, `cohere`, `openai`, `google-genai` | Use only behind explicit plugin extras and document network, auth, and cost metadata. |
| `doc-parsers` | document / OCR parsers | `pypdf`, `python-docx`, `docling`, `unstructured`, `paddleocr` | Large parser stacks stay optional because they pull native deps, models, or extra licenses. |
| `local-ml` | local runtime / heavy ML | `ollama`, `FlagEmbedding`, `sentence-transformers`, `torch` | Never import from core modules. Install only for plugin or local model work. |
| `s3` | object storage SDKs | `boto3`, `S3-compatible API` | Keep S3-compatible storage connectors optional and plugin-scoped. |
| `parquet` | analytics export SDKs | `pyarrow` | Install only for structured export and lakehouse connector work. |
| `fileshare` | file share connector SDKs | `httpx`, `paramiko`, `smbprotocol` | Keep network filesystem clients optional and isolate credential handling. |
| `vectorstores` | vector database SDKs | `qdrant-client`, `pymilvus`, `weaviate-client`, `opensearch-py` | Keep pgvector as the core default. Alternate vector stores must remain optional plugins. |

## Governance Rules

- Core runtime must stay local-first and secret-free for `make test` and `make coverage`.
- Optional SDKs must not be imported from core module top level.
- Heavy ML, cloud, enterprise connector, and document-suite dependencies belong in
  optional extras only.
- Default supply-chain review uses `make licenses`, `make sbom`, and `make audit`.

