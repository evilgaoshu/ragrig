# EVI-104: Phase 3 ACL Policy Regression & Explain Hardening

**Version**: 1.0
**Date**: 2026-05-12
**Status**: Proposed
**Supersedes**: Phase 2 ACL (EVI-68+)

## 1. ACL Policy Matrix

The following table defines the expected access decision for every combination of document ACL state and request principal context.

| # | Document `visibility` | `allowed_principals` | `denied_principals` | Request `principal_ids` | Expected `permits()` | Expected `acl_explain.reason` |
|---|-----------------------|----------------------|---------------------|-------------------------|---------------------|-------------------------------|
| 1 | `public` (default)    | `[]`                 | `[]`                | `None` / `[]` / any     | `True`              | `public`                      |
| 2 | `public`              | `["alice"]`          | `[]`                | `None`                  | `True`              | `public`                      |
| 3 | `protected`           | `["alice"]`          | `[]`                | `["alice"]`             | `True`              | `allowed_principal`           |
| 4 | `protected`           | `["group:eng"]`      | `[]`                | `["group:eng"]`         | `True`              | `allowed_principal`           |
| 5 | `protected`           | `["alice","bob"]`    | `["bob"]`           | `["bob"]`               | `False`             | `denied_principal`            |
| 6 | `protected`           | `["alice"]`          | `["bob"]`           | `["alice","bob"]`       | `False`             | `denied_principal`            |
| 7 | `protected`           | `["alice"]`          | `[]`                | `["bob"]`               | `False`             | `no_matching_principal`       |
| 8 | `protected`           | `["alice"]`          | `[]`                | `[]` / `None`           | `False`             | `no_principal`                |
| 9 | `protected`           | `["alice"]`          | `[]`                | `["unknown"]`           | `False`             | `no_matching_principal`       |
|10 | `unknown`             | `["alice"]`          | `[]`                | `["alice"]`             | `False`             | `unknown_visibility`          |
|11 | `protected`           | `["alice"]`          | `["alice"]`         | `["alice"]`             | `False`             | `denied_principal`            |
|12 | no `acl` key          | N/A                  | N/A                 | `None` / any            | `True`              | `public`                      |

### Principal Resolution Rules

1. **Case-insensitive matching**: `Alice` == `alice` == `ALICE`.
2. **Deny takes precedence**: If a principal appears in both `allowed_principals` and `denied_principals`, access is **denied**.
3. **Any match**: If any of the request's principal_ids match an allowed principal (and none match a denied principal), access is granted.
4. **Public override**: `visibility=public` grants access regardless of `allowed_principals` or `denied_principals`.
5. **Unknown coercion**: Any `visibility` value other than `"public"` or `"protected"` (including `None`, `"secret"`, or missing) is coerced to `"unknown"` → denies all.

---

## 2. `acl_explain` Field Contract

Every chunk in the `/retrieval/search` response array **must** include an `acl_explain` object. The full response may optionally carry a top-level `acl_explain` summary.

### Per-chunk `acl_explain` schema

```jsonc
{
  "chunk_id": "<uuid>",
  "visibility": "public" | "protected" | "unknown",
  "permitted": true | false,
  "reason": "public" | "allowed_principal" | "denied_principal" | "no_matching_principal" | "no_principal" | "unknown_visibility"
}
```

### Reason semantics

| `reason`                  | Meaning                                                    |
|---------------------------|------------------------------------------------------------|
| `public`                  | Document is public (no ACL or visibility=public)           |
| `principal_match`         | At least one request principal matched `allowed_principals` |
| `explicit_deny`           | At least one request principal matched `denied_principals`  |
| `no_matching_principal`   | Protected document, no request principal matched `allowed_principals` |
| `missing_principal`       | Protected document, request principal_ids is None or empty |
| `unknown_visibility`      | ACL visibility is not public/protected (deny all)          |

### Safety constraints

The `acl_explain` object **must NOT** contain:
- Raw `allowed_principals` or `denied_principals` lists
- Full chunk text (only matters outside `acl_explain`)
- Raw prompts, secrets, or credentials

### Top-level `acl_explain_summary` (optional)

When present in the API response:

```jsonc
{
  "total_chunks": 10,
  "permitted": 7,
  "denied": 3,
  "reasons": {
    "public": 5,
    "principal_match": 2,
    "explicit_deny": 1,
    "no_matching_principal": 1,
    "missing_principal": 0,
    "unknown_visibility": 1
  }
}
```

---

## 3. Audit Event Consistency

`/retrieval/search` response `acl_explain` per-chunk `reason` and count must be **consistent** with the audit event system. The test suite must verify:

1. The `acl_explain_summary.reasons` counts match the per-chunk reasons.
2. Reasons present in the response are from the allowed set (`public`, `allowed_principal`, `denied_principal`, `no_matching_principal`, `no_principal`, `unknown_visibility`).
3. Neither the API response nor audit events contain:
   - Raw prompt text
   - Raw secrets / API keys
   - Full document text
   - Complete `allowed_principals` or `denied_principals` arrays

### Per-chunk reason consistency with top-level summary

Every chunk in the response has an `acl_explain.reason`. The top-level
`acl_explain_summary.reasons` counts must equal the count of per-chunk
reasons with the same value.

---

## 4. Chunk Override Document ACL

When a chunk has its own `acl` in `metadata_json` different from the parent document's ACL, the **chunk-level ACL** is authoritative for retrieval filtering. The chunk must carry `inheritance="document"` or `inheritance="propagated"` to indicate origin, but the evaluation always uses the chunk's own `acl` data.

---

## 5. Cross-KB / Tenant Isolation

Documents in different Knowledge Bases must not be visible to principals of another KB unless explicitly allowed by each document's ACL. The isolation boundary is the Knowledge Base itself — ACL filtering is always scoped to the target KB via `knowledge_base_name`.

---

## 6. Out of Scope

- Enterprise SSO / external IdP integration
- ACL storage migration to relational model
- Phase 2 default-public compatibility semantics
- ReBAC / ABAC extensions
