# RAGRig ProcessingProfile Override CRUD + Matrix Editing Spec

Date: 2026-05-09
Status: Implemented (EVI-57)

## 1. Goal

Add override management on top of the existing read-only default ProcessingProfile matrix:
- Create / disable / delete override profiles via API
- Resolution logic: override > wildcard default > safe fallback
- Web Console editing entry for overrides

## 2. Verification

1. `make lint`, `make test`, `make coverage`, `make web-check` all pass.
2. After `POST /processing-profiles` creates a `.pdf/chunk` override,
   `GET /processing-profiles/matrix` returns `source=override` for that cell,
   and resolution prioritizes the override profile.
3. After `PATCH` (disable) or `DELETE` an override, resolution falls back to
   the wildcard default.
4. API does not echo provider secrets and does not fake unavailable providers
   as ready.
5. Web Console can create / disable overrides; empty / error / degraded states
   do not white-screen or overflow horizontally.

## 3. Best-Effort Goals

- Profile diff / preview (not implemented in P1)
- `created_by` / `updated_at` audit fields (implemented)

## 4. Out of Scope

- Real LLM execution (override is just registry metadata)
- Effect evaluation / A-B testing
- Secret storage integration
- Multi-tenant RBAC
- DB persistence (overrides are in-memory only; acceptable for MVP)

## 5. API Endpoints

- `POST /processing-profiles` — create override
- `GET /processing-profiles/overrides` — list overrides
- `GET /processing-profiles/overrides/{profile_id}` — get override detail
- `PATCH /processing-profiles/overrides/{profile_id}` — update / disable / enable
- `DELETE /processing-profiles/overrides/{profile_id}` — delete override
- `GET /processing-profiles/matrix` — matrix now reflects active overrides

## 6. Data Model Changes

- `ProfileStatus` added `DISABLED` for soft-disable without deletion.
- `ProcessingProfile` added `created_by` (str | None) and `updated_at` (datetime | None).
- `to_api_dict()` filters secret-like keys from `metadata` before serialization.

## 7. Registry Behavior

- In-memory `_OVERRIDE_STORE` dict keyed by `profile_id`.
- `resolve_profile(extension, task_type)` skips overrides with `status == DISABLED`.
- `build_matrix()` and `build_api_profile_list()` automatically include active overrides.

## 8. Web Console Changes

- Profile Matrix panel adds "Create Override" button and inline form.
- Each override cell displays Disable/Enable and Delete action buttons.
- Disabled overrides show `override · disabled` label; resolution falls back to default.

## 9. Verification Commands

```bash
make lint
make test
make coverage
make web-check
```

## 10. Risk and Limitations

- Overrides are stored in-memory only; server restart clears them.
- No RBAC; any authenticated client can create or delete overrides.
