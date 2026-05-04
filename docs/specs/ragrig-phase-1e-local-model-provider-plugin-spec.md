# RAGRig Phase 1e Local Model Provider Plugin Spec

Issue: EVI-34
Date: 2026-05-04
Status: DEV implementation spec for PR-2

## Scope

Phase 1e is split into three reviewable pull requests so the provider-plugin layer can land
without a single large, mixed-risk diff.

PR split:

1. PR-1: Provider registry core contract, deterministic-local registration, retrieval/indexing compatibility, and docs.
2. PR-2: Local runtime adapters and optional heavy local ML providers.
3. PR-3: Cloud provider manifests/stubs and cloud-second docs alignment.

This PR-2 includes:

- `model.ollama` local adapter with configurable host, model inventory, chat/generate, embedding capability detection, and structured local-disabled errors
- `model.lm_studio` local adapter over an OpenAI-compatible base URL with docs default `http://localhost:1234/v1`
- shared OpenAI-compatible local adapter coverage for `llama.cpp`, `vLLM`, `Xinference`, and `LocalAI`
- `embedding.bge` and `reranker.bge` provider boundaries with optional dependency-safe lazy runtime loading
- plugin discovery updates so the official local-runtime manifests are exposed as ready or dependency-gated instead of PR-1 stubs
- `/models` read-boundary updates that show registered local model and reranker providers as available registry surfaces
- tests covering fake-client local runtime contracts, optional dependency failure paths, plugin discovery, and Web Console model visibility
- README and policy updates that document optional local ML installation and current limits

Explicitly out of scope for PR-2:

- cloud provider stubs or SDK integrations beyond the already documented PR-3 boundary
- DB-backed model profile persistence, migrations, or model write APIs
- mandatory `192.168.3.100` runtime validation for this issue

## Authority

This spec is subordinate to:

- `docs/specs/ragrig-mvp-spec.md`
- `docs/specs/ragrig-phase-1c-chunking-embedding-spec.md`
- `docs/specs/ragrig-phase-1d-retrieval-api-spec.md`
- `docs/specs/ragrig-local-first-quality-supply-chain-policy.md`

If this file conflicts with those documents, the authority documents win.

## PR-2 Technical Shape

Files and boundaries:

- `src/ragrig/providers/local.py`: Ollama and OpenAI-compatible local model provider adapters with optional SDK-safe loaders
- `src/ragrig/providers/bge.py`: optional local BGE embedding and reranker adapters with lazy runtime loading
- `src/ragrig/providers/__init__.py`: registry wiring for the new local providers while preserving deterministic-local defaults
- `src/ragrig/plugins/official.py`: promote local provider manifests from unavailable stubs to PR-2-ready discovery entries
- `src/ragrig/web_console.py`: report local model and reranker registry shells as ready read-only boundaries
- `tests/test_local_providers.py`: fake-client local runtime contract coverage
- `tests/test_plugins.py`, `tests/test_web_console.py`, `tests/test_plugins_check.py`, `tests/test_import_guard.py`: plugin discovery, read-boundary, and optional import guard coverage
- `pyproject.toml`: optional `local-ml` extra only

PR-2 must preserve the existing default path:

- no secrets
- no network
- no GPU
- no optional SDK imports at top-level core import time
- deterministic-local remains the default indexing and retrieval embedding profile

## Provider Contract Fields

The registry contract must support these fields even if some providers will only fill them in later:

- `name`
- `kind` (`local` or `cloud`)
- `description`
- `capabilities` covering `chat`, `generate`, `embedding`, `rerank`, `streaming`, `batch`
- `default_dimensions` and `max_dimensions`
- `default_context_window` and `max_context_window`
- `required_secrets`
- `config_schema`
- `sdk_protocol`
- `healthcheck`
- `failure_modes`
- `retry_policy`
- `audit_fields`
- `metric_fields`
- `intended_uses`

Provider runtime contracts in PR-2:

- `BaseProvider.embed_text()` is implemented for embedding providers
- `BaseProvider.generate()`, `BaseProvider.chat()`, and `BaseProvider.rerank()` fail with structured `unsupported_capability`
- `health_check()` returns a structured status/detail payload
- missing providers fail with structured `provider_not_registered`
- optional local runtime loaders fail with structured `optional_dependency_missing`
- Ollama embedding attempts against a non-embedding-capable model fail with structured `embedding_not_supported`

## Deterministic-local Boundary

`deterministic-local` remains a built-in embedding provider for CI and smoke use only.

PR-2 requirements for this provider:

- it remains registered through the core registry without any behavior changes
- it remains the default profile for indexing and retrieval when no other profile is requested
- its metadata continues to state that it is intended for `ci` and `smoke`
- PR-2 docs still must not describe it as a production semantic embedding model

## Retrieval and Indexing Compatibility

PR-1 must keep the Phase 1c and Phase 1d behavior compatible:

- indexing still writes `provider`, `model`, and `dimensions` into `embeddings`
- retrieval still resolves by `provider` / `model` / `dimensions`
- default no-index case still falls back to `deterministic-local` and `hash-<dimensions>d`
- dimension mismatch still returns `embedding_profile_mismatch`
- query embedding and indexing embedding still use the same deterministic profile family by default

## Read-only Service Boundary

PR-2 extends the existing read-only boundary so later Web Console model pages can discover which local providers are registered now.

For this PR the existing `GET /models` response is sufficient if it includes:

- indexed embedding profiles already present in the database
- registered provider metadata derived from the provider registry
- explicit ready states for local LLM and reranker registry shells, while still remaining read-only

No write API, live runtime mutation API, or DB persistence is required in PR-2.

## Optional Dependency Strategy

PR-2 may add local runtime packages only behind an optional extra.

Rules:

- default dependency set still must not include `torch`, `FlagEmbedding`, `sentence-transformers`, `ollama`, `openai`, or cloud SDKs
- optional `local-ml` extra may include `torch`, `FlagEmbedding`, `sentence-transformers`, `ollama`, and `openai`
- provider registry core imports must stay optional-dependency-safe
- follow-on cloud provider SDKs still belong in optional extras or dependency groups in PR-3

## Test Strategy

Default verification remains local and CI friendly.

Required automated coverage in PR-2:

- fake-client Ollama generation, chat, model listing, health, and embedding behavior
- fake-client OpenAI-compatible local runtime coverage for LM Studio, llama.cpp, vLLM, Xinference, and LocalAI
- BGE embedding and reranker runtime coverage with fake local runtimes
- optional dependency error coverage for missing BGE runtime imports
- plugin discovery status changes for local runtime manifests and dependency-gated BGE manifests
- `/models` includes the expanded registered provider metadata and ready read-only LLM/reranker registry shells
- import guard confirms the provider registry and new provider modules avoid top-level optional SDK imports
- existing indexing and retrieval default-path coverage remains intact

Required repository commands:

- `make format`
- `make lint`
- `make test`
- `make coverage`

## Verification Strategy

Hard gate for this issue:

- local verification and GitHub CI-aligned commands only

`192.168.3.100` policy for this PR:

- not a hard requirement for EVI-34 PR-2
- if a developer voluntarily runs shared-host validation, record it explicitly
- if no shared-host run is performed, the delivery note must say that 3.100 verification is not required for this PR slice

## PR-2 Delivery Boundary

PR-2 delivers these local adapters behind the contract introduced in PR-1:

- Ollama adapter
- LM Studio adapter
- OpenAI-compatible local runtime base for llama.cpp server, vLLM, Xinference, and LocalAI
- optional BGE embedding and reranker adapters
- env-gated live smoke tests only for explicitly enabled local runtimes

## PR-3 Boundary

PR-3 will add cloud-second manifests and stubs behind the same contract:

- Google Vertex AI
- Amazon Bedrock
- Azure OpenAI
- OpenRouter
- OpenAI
- Cohere
- Voyage
- Jina

Those providers remain optional, stubbed, or fake-client-tested until a later production adapter pass.
