# Phase 2 ACL and Pre-Retrieval Permission Filtering

## Principal Model

RAGRig models retrieval subjects as normalized principal strings. Users are represented as `user:<id>` and groups as `group:<id>`. Legacy bare user IDs remain accepted for backward compatibility and are normalized case-insensitively. A request principal context is the union of the user subject and all group subjects.

Missing principal context is degraded: protected or unknown content is not treated as visible.

## Document and Chunk ACL Schema

ACL metadata is stored under `metadata_json.acl` on documents, document versions, and chunks:

```json
{
  "visibility": "public|protected|unknown",
  "allowed_principals": ["user:alice", "group:engineering"],
  "denied_principals": ["user:bob"],
  "acl_source": "fileshare:owner:group",
  "acl_source_hash": "source-hash",
  "inheritance": "document|propagated|chunk_override",
  "ttl": "2026-06-01T00:00:00+00:00"
}
```

`public` permits all callers. `protected` requires a matching allowed principal and no matching denied principal. `unknown` denies all callers.

## Inheritance and Overrides

Indexing copies the latest document or document-version ACL to each chunk with `inheritance: propagated`. Chunk-level ACL CRUD can replace that metadata with a chunk-specific ACL. Deny entries always override allow entries. Missing ACL metadata defaults to `public` for backward compatibility with local smoke fixtures.

## Filtering Order

`/retrieval/search` applies ACL filtering immediately after candidate fetch and before hybrid lexical fusion, rerank, API serialization, answer generation, citations, or debug payload assembly. `/retrieval/answer` consumes only the already filtered retrieval report, so unauthorized chunks cannot enter the answer prompt or citations.

The response includes safe `acl_explain` counts: enforcement state, principal context state, candidate count, visible count, filtered count, and aggregate reason codes. It never includes full restricted text or raw principal allow/deny lists.

## Audit Events

The `audit_events` repository records:

- `acl_write`: document/chunk ACL writes during ingestion or ACL CRUD.
- `retrieval_filter`: pre-retrieval filtering with safe aggregate counts.
- `access_denied`: retrieval where candidates existed but no visible result remained.

Audit payloads redact raw secrets, raw prompts, provider messages, and full restricted text.

## Secret Boundary

ACL summaries, permission previews, retrieval explain payloads, and audit events expose only metadata counts, visibility, inheritance, hashes, and reason codes. They must not include raw provider secrets, raw prompts, complete restricted chunk text, or complete allow/deny principal lists.
