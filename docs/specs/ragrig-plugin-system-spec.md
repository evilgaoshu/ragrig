# RAGRig Plugin System Spec

## Goal

Define a contract-first plugin system for RAGRig that exposes stable plugin identities, manifest validation, capability reporting, dependency guards, config validation, and discovery APIs without requiring optional SDKs, network access, or secrets in the default core path.

## Scope

This spec covers the plugin registry core, versioned manifest schema, built-in core plugin manifests, official stub manifests, config validation, dependency guards, a discovery API, contract tests, and contributor-facing documentation.

This spec does not implement real Google Workspace, Microsoft 365, Office preview, OCR, Qdrant, or cloud model runtime connectors.

## Stable Plugin Identity

- Plugin ids use the documented short form such as `source.local`, `parser.markdown`, and `vector.pgvector`.
- Every manifest must declare `manifest_version: 1`.
- Every manifest must declare a stable `plugin_type`, `family`, `version`, `owner`, `tier`, and `status`.

## Plugin Tiers

- Built-in core plugins ship with the default local-first path and must work without optional SDKs.
- Official plugins may depend on optional SDKs, but their manifests must still load and report truthful readiness.
- Community plugin packaging is reserved for a future issue; this phase only preserves the contract boundary.

## Built-in Core Plugins

The core registry must register these built-in plugins:

- `source.local`
- `parser.markdown`
- `parser.text`
- `chunker.character_window`
- `embedding.deterministic_local`
- `vector.pgvector`
- `sink.jsonl`
- `preview.markdown`

## Official Stub Plugins

The core registry must register these official stubs:

- `vector.qdrant`
- `model.local_runtime`
- `embedding.bge`
- `reranker.bge`
- `source.s3`
- `sink.object_storage`
- `source.fileshare`
- `source.google_workspace`
- `source.microsoft_365`
- `source.wiki`
- `source.database`
- `preview.office`
- `source.collaboration`
- `parser.advanced_documents`
- `ocr`
- `sink.analytics`
- `sink.agent_access`

## Manifest Schema

Manifests are defined with Pydantic models.

Required fields:

- `manifest_version`
- `plugin_id`
- `display_name`
- `description`
- `plugin_type`
- `family`
- `version`
- `owner`
- `tier`
- `status`
- `capabilities`
- `docs_reference`

Optional fields:

- `config_model`
- `example_config`
- `secret_requirements`
- `optional_dependencies`
- `unavailable_reason`

Config models must use `extra="forbid"` so unknown fields fail validation.

## Capability Matrix

Capabilities are stable documented strings. Core and official manifests must fail validation if they declare a capability that is not allowed for the manifest type.

Current documented capabilities:

- `read`
- `write`
- `parse_text`
- `chunk_text`
- `embed_text`
- `generate_text`
- `rerank`
- `vector_read`
- `vector_write`
- `preview_read`
- `preview_write`
- `ocr_text`
- `incremental_sync`
- `delete_detection`
- `permission_mapping`

## Dependency Guard

- Optional SDKs must never be imported at top level from the core path.
- Registry discovery checks SDK availability with import-spec inspection only.
- Missing optional SDKs must surface as `unavailable` with an explicit reason.

## Secret and Config Validation

- Plugins may reference secrets using `env:SECRET_NAME` values.
- A plugin config fails validation if it references a secret not declared in `secret_requirements`.
- A plugin config fails validation if it contains unknown fields.
- A plugin with no config model is not configurable and rejects non-empty configs.

## Discovery API

`GET /plugins` returns the registry discovery view.

Each item includes:

- plugin id and manifest version
- type, family, owner, tier, and version
- status and reason
- capabilities
- whether the plugin is configurable
- missing dependencies
- secret requirements
- docs reference

The API must work without optional SDKs, secrets, network access, or seeded data.

## Runtime Notes

- `source.s3` ships a real S3-compatible ingestion runtime behind optional `boto3`.
- `sink.object_storage` ships a real S3-compatible export runtime behind optional `boto3`.
- `sink.object_storage` remains `degraded` even when `boto3` is installed because Google Cloud Storage and Azure Blob stay contract-only in this phase.

## Existing Runtime Boundaries

- Local ingestion continues to use the built-in parser manifests only.
- Local indexing continues to use the built-in character chunker, deterministic embedding provider, and pgvector backend only.
- Model, embedding, and vector runtime contracts beyond the current built-in path remain deferred to follow-up issues.

## Testing Strategy

Contract tests must cover:

- manifest validation
- capability validation
- config validation
- secret declaration enforcement
- dependency guard behavior
- discovery output
- local docs link checks

Docs link checks only validate local paths or URL shape. They must not perform outbound HTTP requests.

## Contributor Guidance

Contributors adding a new plugin in this phase must:

1. Add a manifest under `src/ragrig/plugins/`.
2. Add a config model if the plugin is configurable.
3. Declare all secret requirements explicitly.
4. Add example config that passes validation.
5. Extend contract tests so the registry still validates every built-in or official manifest.
