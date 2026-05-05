# RAGRig Phase 1e Local Model Provider Plugin Spec

Issue: EVI-34
Date: 2026-05-04
Status: DEV implementation spec for PR-3

## Scope

Phase 1e is split into three reviewable pull requests so the provider-plugin layer can land
without a single large, mixed-risk diff.

PR split:

1. PR-1: Provider registry core contract, deterministic-local registration, retrieval/indexing compatibility, and docs.
2. PR-2: Local runtime adapters and optional heavy local ML providers.
3. PR-3: Cloud provider manifests/stubs and cloud-second docs alignment.

This PR-3 includes:

- contract-only cloud provider stubs for Google Vertex AI, Amazon Bedrock, Azure OpenAI, OpenRouter, OpenAI, Cohere, Voyage, and Jina
- provider registry metadata for the cloud-second providers, including secrets, config schema, retry/failure fields, audit/metrics fields, and intended uses
- plugin discovery updates so `/plugins` and `make plugins-check` expose cloud provider manifests with dependency-gated readiness and explicit stub limitations
- `/models` read-boundary updates that show cloud provider registry metadata alongside the existing local providers
- optional dependency declarations for cloud SDKs without adding any cloud package to the default core install path
- tests covering cloud registry visibility, discovery payloads, and Web Console `/models` exposure without live cloud access
- README and policy updates that document cloud-second boundaries, optional extras, environment variables, and production follow-up work

Explicitly out of scope for PR-3:

- production cloud API calls, live cloud smoke checks, or real secret handling
- DB-backed model profile persistence, migrations, or model write APIs
- mandatory `192.168.3.100` runtime validation for this issue

## Authority

This spec is subordinate to:

- `docs/specs/ragrig-mvp-spec.md`
- `docs/specs/ragrig-phase-1c-chunking-embedding-spec.md`
- `docs/specs/ragrig-phase-1d-retrieval-api-spec.md`
- `docs/specs/ragrig-local-first-quality-supply-chain-policy.md`

If this file conflicts with those documents, the authority documents win.

## PR-3 Technical Shape

Files and boundaries:

- `src/ragrig/providers/cloud.py`: shared cloud provider metadata and stub runtime contract
- `src/ragrig/providers/__init__.py`: registry wiring for the cloud stub providers while preserving the local and deterministic defaults
- `src/ragrig/plugins/official.py`: official plugin manifests for the cloud provider stubs, including dependency-gated discovery metadata
- `src/ragrig/web_console.py`: `/models` read-boundary automatically picks up the new cloud provider registry entries
- `tests/test_local_providers.py`: registry coverage extended to cloud metadata visibility
- `tests/test_plugins.py`, `tests/test_plugins_check.py`, `tests/test_web_console.py`: cloud plugin discovery, plugin-check payload, and Web Console read-boundary coverage
- `pyproject.toml`: optional cloud dependency groups only

PR-3 must preserve the existing default path:

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

Provider runtime contracts in PR-3:

- `BaseProvider.embed_text()` is implemented for embedding providers
- `BaseProvider.generate()`, `BaseProvider.chat()`, and `BaseProvider.rerank()` fail with structured `unsupported_capability`
- `health_check()` returns a structured status/detail payload
- missing providers fail with structured `provider_not_registered`
- optional local runtime loaders fail with structured `optional_dependency_missing`
- Ollama embedding attempts against a non-embedding-capable model fail with structured `embedding_not_supported`
- cloud stub providers fail with structured `optional_dependency_missing` when the optional SDK is absent
- cloud stub providers fail with structured `provider_stub_only` when a behavior path is invoked even if a fake client is injected

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
- registered provider metadata derived from the provider registry, including the cloud stubs
- explicit ready states for local and cloud LLM/reranker registry shells, while still remaining read-only

No write API, live runtime mutation API, or DB persistence is required in PR-3.

## Optional Dependency Strategy

PR-3 may add cloud SDK packages only behind optional extras.

Rules:

- default dependency set still must not include `torch`, `FlagEmbedding`, `sentence-transformers`, `ollama`, `openai`, or cloud SDKs
- optional `local-ml` extra may include `torch`, `FlagEmbedding`, `sentence-transformers`, `ollama`, and `openai`
- provider registry core imports must stay optional-dependency-safe
- cloud provider SDKs must stay in optional extras such as `cloud-google`, `cloud-aws`, `cloud-openai`, `cloud-cohere`, and `cloud-voyage`
- no cloud stub may require a real secret, network access, or live account in default tests

## Test Strategy

Default verification remains local and CI friendly.

Required automated coverage in PR-3:

- provider registry visibility for all eight cloud stubs
- plugin discovery visibility for all eight cloud stubs, including secret requirements and missing dependency reporting where applicable
- `/models` includes the expanded registered provider metadata and ready read-only LLM/reranker registry shells for the cloud stubs
- import guard confirms the provider registry and cloud stub module avoid top-level optional SDK imports
- default tests continue to run without cloud accounts, secrets, or network access

Required repository commands:

- `make format`
- `make lint`
- `make test`
- `make coverage`

## Verification Strategy

Hard gate for this issue:

- local verification and GitHub CI-aligned commands only

`192.168.3.100` policy for this PR:

- not a hard requirement for EVI-34 PR-3
- if a developer voluntarily runs shared-host validation, record it explicitly
- if no shared-host run is performed, the delivery note must say that 3.100 verification is not required for this PR slice

## PR-3 Delivery Boundary

PR-3 delivers these cloud provider stubs behind the contract introduced in PR-1 and extended in PR-2:

- Google Vertex AI stub
- Amazon Bedrock stub
- Azure OpenAI stub
- OpenRouter stub
- OpenAI stub
- Cohere stub
- Voyage stub
- Jina stub
- optional cloud dependency groups and docs only

Production cloud adapters remain out of scope after PR-3.

After PR-3, any future production cloud pass must be split separately per provider family or per shared SDK surface so that live cloud access, retry behavior, and cost/usage telemetry can be reviewed independently from the stub metadata layer.
