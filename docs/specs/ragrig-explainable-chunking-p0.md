# Explainable chunking P0

## Scope

RAGRig maps every built-in chunking strategy to a stable template contract:

| Template | Strategy |
| --- | --- |
| `char_window_v1` | fixed character windows |
| `paragraph_v1` | paragraph boundaries |
| `heading_v1` | Markdown heading sections |
| `sentence_v1` | sentence boundaries |
| `parent_child_v1` | parent context plus embedded children |
| `recursive_v1` | heading → paragraph → sentence → character fallback |
| `token_aware_v1` | lightweight estimated-token windows |

Templates expose a version, display name, parameter defaults, split rules, and
limitations. Template metadata is additive: legacy chunk text hashes and
`config_hash` inputs are unchanged.

## Explainability contract

New chunks record the template ID/version, strategy, parameter snapshot,
stable split reason, character range, heading/section data when available,
source block type/ID, and parent linkage when applicable. Indexing adds the
document URI and version identifiers used by retrieval citations.

`POST /chunking/preview` accepts text or a workspace-scoped
`document_version_id` and invokes the same chunker used by indexing. Unknown
templates and invalid parameters return stable errors.

`recursive_v1` records the boundary actually selected for every chunk, including
`recursive_fit` when no split is needed and `window_boundary` when an
indivisible block requires character fallback.
`token_aware_v1` accepts `max_tokens` and `token_overlap`, records
`estimated_tokens`, and intentionally uses a dependency-light estimate rather
than claiming provider billing-token parity.

## Manual overrides

The Documents chunk review UI supports splitting a chunk, merging adjacent
chunks, and resetting to template output. Saving writes a revisioned
`chunk_override` snapshot to `document_version.metadata_json`; it never
modifies immutable `extracted_text`.

Each save/reset records actor, timestamp, reason, before/after counts, and
operation summaries in an audit event. A saved override marks
`chunk_index_status.reindex_required=true`. The reindex endpoint rebuilds only
the selected latest document version, regenerating chunk text from the stored
source character ranges and replacing its embeddings.

Chunk IDs change during reindex, matching the existing force-reindex
semantics. Citation continuity is provided by stable document URI,
document-version ID, chunk index, and character range. Parent-child indexing
continues unchanged; P0 rejects manual overrides for parent-child chunks with
`parent_child_manual_override_unsupported` rather than dropping parent links.
