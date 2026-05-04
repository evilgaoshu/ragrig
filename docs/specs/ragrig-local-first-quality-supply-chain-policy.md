# RAGRig Local-first, Quality, and Supply Chain Policy

Date: 2026-05-04
Status: Accepted project policy

## 1. Product Principle

RAGRig is local-first. The default developer and SME deployment path must work without a
hosted model provider, hosted vector database, or cloud object store.

Cloud integrations are second-layer plugins. They are important, but they must not become
required dependencies of the core service, default smoke tests, or fresh-clone demo.

Practical rules:

- Core development must run with local files, PostgreSQL/pgvector, deterministic local
  embeddings, and later local model providers.
- Local model adapters have higher priority than cloud model adapters.
- Cloud SDKs belong in optional plugin extras, not the core dependency set.
- The Phase 1e provider registry contract is core. Real local/cloud adapters remain optional follow-on work.
- Every provider must expose capability metadata so operators can compare privacy,
  cost, latency, streaming, embedding, reranking, and batch support.
- Official or open-source SDKs are preferred. If an official SDK does not exist or is too
  heavy, use the official HTTP API with `httpx` and document why.

## 2. Model Provider Priority

### P0: Local-first model providers

| Plugin | Provider | SDK or protocol | Notes |
| --- | --- | --- | --- |
| `model.ollama` | [Ollama](https://ollama.com/) | [`ollama`](https://github.com/ollama/ollama-python) Python SDK and Ollama REST API | Default local LLM and embedding path. Supports local host configuration, streaming, generation, chat, and embed APIs. |
| `model.lm_studio` | [LM Studio](https://lmstudio.ai/) | [OpenAI-compatible API](https://lmstudio.ai/docs/developer/openai-compat) via the official `openai` SDK or `httpx` | Local desktop/server model runtime. Default base URL is commonly `http://localhost:1234/v1`. |
| `model.llama_cpp_server` | [llama.cpp](https://github.com/ggml-org/llama.cpp) server | OpenAI-compatible API via `openai` SDK or `httpx` | Lightweight CPU/GPU local serving path. |
| `model.vllm` | [vLLM](https://www.vllm.ai/) | OpenAI-compatible API via `openai` SDK or `httpx` | Self-hosted GPU serving for larger local or private-cloud models. |
| `model.xinference` | [Xinference](https://inference.readthedocs.io/) | Official REST/client surface where available, otherwise OpenAI-compatible API | Local and private-cluster model serving. |
| `model.localai` | [LocalAI](https://localai.io/) | OpenAI-compatible API via `openai` SDK or `httpx` | Optional local OpenAI-compatible runtime. |
| `embedding.bge` | [BAAI BGE](https://huggingface.co/BAAI) | `FlagEmbedding`, `sentence-transformers`, or OpenAI-compatible local serving | Preferred local embedding family. |
| `reranker.bge` | [BAAI BGE rerankers](https://huggingface.co/BAAI) | `FlagEmbedding` or local HTTP serving | Preferred local reranking family. |

### P1: Cloud model providers

| Plugin | Provider | SDK or protocol | Notes |
| --- | --- | --- | --- |
| `model.google_vertex` | [Google Vertex AI](https://cloud.google.com/vertex-ai) / Gemini on Vertex AI | [`google-genai`](https://cloud.google.com/vertex-ai/generative-ai/docs/sdks/overview) | Official Google Gen AI SDK. Must support project/location configuration and service-account auth. |
| `model.aws_bedrock` | [Amazon Bedrock](https://aws.amazon.com/bedrock/) | [`boto3`](https://docs.aws.amazon.com/bedrock/latest/userguide/getting-started-api.html) / botocore | Official AWS SDK path. Must support region, profile, role, and retry configuration. |
| `model.azure_openai` | [Azure OpenAI](https://azure.microsoft.com/en-us/products/ai-services/openai-service) | Official `openai` SDK configured for Azure endpoints, plus Azure identity packages when needed | Enterprise cloud model path for Microsoft tenants. |
| `model.openrouter` | [OpenRouter](https://openrouter.ai/) | [OpenRouter API](https://openrouter.ai/docs/quickstart), OpenRouter SDK, or official `openai` SDK with OpenRouter base URL | Cloud model routing path. Must record selected upstream model/provider. |
| `model.openai` | [OpenAI](https://platform.openai.com/docs/overview) | Official `openai` SDK | Optional cloud model provider. |
| `model.cohere` | [Cohere](https://cohere.com/) | Official `cohere` SDK or Cohere HTTP API | Cloud embedding, reranking, and generation. |
| `model.voyage` | [Voyage AI](https://www.voyageai.com/) | Official [`voyageai`](https://docs.voyageai.com/docs/api-key-and-installation) Python package | Cloud embedding and reranking. |
| `model.jina` | [Jina AI](https://jina.ai/) | [Jina API](https://docs.jina.ai/) via `httpx` unless an official Python SDK is selected | Cloud embeddings, reranking, and document APIs. |

## 3. Initial SDK and Dependency Inventory

This inventory is not a commitment to install every package in the core application. It is
the preferred supply chain for official plugins when those plugins are implemented.

### Current core runtime

| Area | Package | Policy |
| --- | --- | --- |
| API | `fastapi`, `uvicorn` | Core dependency |
| Settings | `pydantic-settings` | Core dependency |
| Database | `sqlalchemy`, `alembic`, `psycopg[binary]` | Core dependency |
| Vector in Postgres | `pgvector` | Core dependency |
| Build | `hatchling` | Build dependency |
| Dev and tests | `pytest`, `httpx`, `ruff` | Dev dependency |

### Planned optional plugin dependencies

| Plugin area | Preferred SDKs or packages | Supply chain rule |
| --- | --- | --- |
| Local model serving | `ollama`, `openai`, `httpx` | Prefer local official SDK or OpenAI-compatible protocol. |
| Local embedding/rerank | `FlagEmbedding`, `sentence-transformers`, `torch` | Heavy ML packages must be optional extras, never core imports. |
| Cloud model serving | `google-genai`, `boto3`, `openai`, `cohere`, `voyageai`, `httpx` | Official SDK first; direct official API second. |

PR-1 note:

- `src/ragrig/providers/` is now part of the core dependency-safe path.
- PR-1 must not add any provider SDK from the tables above into the default runtime.
- PR-2 and PR-3 may add extras or dependency groups, but core imports must remain optional-safe.
| Qdrant | `qdrant-client` | Official client. |
| Enterprise vector stores | `pymilvus`, `weaviate-client`, `opensearch-py`, `elasticsearch`, `redis` | Official or project-maintained clients only. |
| Object storage | `boto3`, `google-cloud-storage`, `azure-storage-blob`, `minio` | Prefer cloud/vendor SDKs; S3-compatible adapters must be tested against at least AWS S3, MinIO, and one non-AWS S3-compatible service. |
| File shares | `smbprotocol`, `paramiko`, `httpx` | NFS should use mounted local paths rather than a special SDK. |
| Google Workspace | `google-api-python-client`, `google-auth` | Official Google API clients. |
| Microsoft 365 | `msgraph-sdk`, `azure-identity` | Official Microsoft Graph and Azure identity packages where practical. |
| Wiki and collaboration | `httpx` first; official SDK only when maintained by the platform | Avoid stale community SDKs for core connectors. |
| Document parsing | `pypdf`, `python-docx`, `python-pptx`, `openpyxl`, `docling`, `unstructured` | Keep heavyweight parsers optional. |
| OCR | `pytesseract`, `paddleocr`, cloud OCR SDKs | Local OCR first; cloud OCR plugins optional. |
| Analytics sinks | `pyarrow`, `duckdb`, `clickhouse-connect`, `google-cloud-bigquery`, `snowflake-connector-python` | Output plugins only. |

## 4. Supply Chain Management

Dependency management requirements:

- Keep `uv.lock` committed for reproducible development and CI installs.
- Put optional provider SDKs behind plugin extras or dependency groups.
- Do not import optional SDKs from core modules.
- Prefer packages published by official vendors or active open-source projects.
- Prefer Apache-2.0, MIT, BSD, and ISC licenses.
- GPL, AGPL, SSPL, source-available, or commercial-only dependencies require explicit
  maintainer approval and must not enter the core path by default.
- Do not vendor third-party code unless the source, version, checksum, and license are
  documented.
- Run vulnerability and license checks before release. Preferred tools are `pip-audit`,
  OSV Scanner, and CycloneDX or Syft for SBOM generation.
- Document every secret required by a plugin. No plugin may read undeclared environment
  variables.
- Cloud plugins must record provider, region, model ID, SDK version, request ID when
  available, latency, token usage, and cost metadata when available.

## 5. Test Coverage Policy

Core modules must reach and maintain 100% coverage.

Core modules include:

- `src/ragrig/db`
- `src/ragrig/repositories`
- `src/ragrig/ingestion`
- `src/ragrig/parsers`
- `src/ragrig/chunkers`
- `src/ragrig/embeddings`
- `src/ragrig/indexing`
- `src/ragrig/providers`
- future plugin registry, workflow engine, permission boundary, retrieval, audit, and
  evaluation core modules

Coverage expectations:

- 100% line coverage for core modules.
- Meaningful branch and error-path tests for parser failures, skipped files, duplicate
  documents, retryable provider failures, permanent provider failures, and database errors.
- No network, cloud account, or secret is required for default unit tests.
- Cloud and enterprise plugins need contract tests with fake clients, plus optional live
  smoke tests gated by explicit environment variables.
- Generated migrations and pure type declarations may be excluded only with an inline
  reason and maintainer approval.

The coverage gate should be implemented before the next core feature milestone that adds
retrieval, plugin registry, or production model providers.
