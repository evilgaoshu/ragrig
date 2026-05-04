# RAGRig Phase 1e Local Model Provider Plugin Spec

Issue: EVI-34
Date: 2026-05-04
Status: DEV implementation spec for PR-1

## Scope

Phase 1e is split into three reviewable pull requests so the provider-plugin layer can land
without a single large, mixed-risk diff.

PR split:

1. PR-1: Provider registry core contract, deterministic-local registration, retrieval/indexing compatibility, and docs.
2. PR-2: Local runtime adapters and optional heavy local ML providers.
3. PR-3: Cloud provider manifests/stubs and cloud-second docs alignment.

This PR-1 includes:

- `src/ragrig/providers/` core registry contract and deterministic-local registration
- provider metadata, capability declarations, structured provider error contract, and health contract
- retrieval/indexing resolve path updated to use the registry while preserving default local behavior
- read-only provider inventory exposure through the existing `/models` service boundary
- tests covering registry registration, discovery, error shape, health checks, and indexing/retrieval compatibility
- README and policy updates that state the registry exists now while real Ollama/LM Studio/BGE adapters remain follow-on work

Explicitly out of scope for PR-1:

- Ollama, LM Studio, llama.cpp server, vLLM, Xinference, or LocalAI runtime adapters
- BGE embedding or reranker implementations
- cloud provider stubs or SDK integrations
- DB-backed model profile persistence, migrations, or model write APIs
- mandatory `192.168.3.100` runtime validation for this issue

## Authority

This spec is subordinate to:

- `docs/specs/ragrig-mvp-spec.md`
- `docs/specs/ragrig-phase-1c-chunking-embedding-spec.md`
- `docs/specs/ragrig-phase-1d-retrieval-api-spec.md`
- `docs/specs/ragrig-local-first-quality-supply-chain-policy.md`

If this file conflicts with those documents, the authority documents win.

## PR-1 Technical Shape

Files and boundaries:

- `src/ragrig/providers/__init__.py`: provider capability enum, provider metadata, retry policy, health result, structured provider error, base provider interface, registry implementation, default registry factory, deterministic-local registration
- `src/ragrig/indexing/pipeline.py`: resolve deterministic-local via registry instead of direct class construction
- `src/ragrig/retrieval.py`: resolve query embedding provider via registry instead of direct class construction
- `src/ragrig/web_console.py`: expose read-only registered provider metadata via the existing `/models` service boundary
- `tests/test_providers.py`: registry contract coverage
- `tests/test_indexing_pipeline.py`, `tests/test_retrieval.py`, `tests/test_web_console.py`, `tests/test_import_guard.py`: compatibility and read-boundary coverage

PR-1 must preserve the existing default path:

- no secrets
- no network
- no GPU
- no optional SDK imports
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

Provider runtime contracts in PR-1:

- `BaseProvider.embed_text()` is implemented for embedding providers
- `BaseProvider.generate()`, `BaseProvider.chat()`, and `BaseProvider.rerank()` fail with structured `unsupported_capability`
- `health_check()` returns a structured status/detail payload
- missing providers fail with structured `provider_not_registered`

## Deterministic-local Boundary

`deterministic-local` remains a built-in embedding provider for CI and smoke use only.

PR-1 requirements for this provider:

- it must register through the core registry instead of being treated as a special hardcoded path
- it must remain the default profile for indexing and retrieval when no other profile is requested
- its metadata must state that it is intended for `ci` and `smoke`
- docs must not describe it as a production semantic embedding model

## Retrieval and Indexing Compatibility

PR-1 must keep the Phase 1c and Phase 1d behavior compatible:

- indexing still writes `provider`, `model`, and `dimensions` into `embeddings`
- retrieval still resolves by `provider` / `model` / `dimensions`
- default no-index case still falls back to `deterministic-local` and `hash-<dimensions>d`
- dimension mismatch still returns `embedding_profile_mismatch`
- query embedding and indexing embedding still use the same deterministic profile family by default

## Read-only Service Boundary

PR-1 should expose registry metadata through a read-only boundary that later Web Console model pages can reuse.

For this PR the existing `GET /models` response is sufficient if it includes:

- indexed embedding profiles already present in the database
- registered provider metadata derived from the provider registry
- explicit disabled/deferred states for LLM and reranker adapters that are not implemented until PR-2

No write API or DB persistence is required in PR-1.

## Optional Dependency Strategy

PR-1 must not add heavy or cloud provider packages to the default dependency set.

Rules:

- no `torch`
- no `FlagEmbedding`
- no `sentence-transformers`
- no `ollama`
- no `openai`
- no cloud SDKs
- provider registry core imports must stay optional-dependency-safe
- follow-on provider SDKs belong in optional extras or dependency groups in PR-2/PR-3

## Test Strategy

Default verification remains local and CI friendly.

Required automated coverage in PR-1:

- registry register/get/list/read
- registry health-check aggregation
- structured errors for unknown providers and unsupported capabilities
- deterministic-local registration in the default registry
- indexing path resolves the provider through the registry
- retrieval path resolves the provider through the registry
- existing profile mismatch coverage remains in place
- `/models` includes both indexed profile data and registered provider metadata
- import guard confirms the provider registry stays in the core module set and avoids optional SDK imports

Required repository commands:

- `make format`
- `make lint`
- `make test`

## Verification Strategy

Hard gate for this issue:

- local verification and GitHub CI-aligned commands only

`192.168.3.100` policy for this PR:

- not a hard requirement for EVI-34 PR-1
- if a developer voluntarily runs shared-host validation, record it explicitly
- if no shared-host run is performed, the delivery note must say that 3.100 verification is not required for this PR slice

## PR-2 Boundary

PR-2 will add real local adapters behind the contract introduced here:

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
