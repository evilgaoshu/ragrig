# Authentication & RBAC

RAGRig ships with password-based authentication, API keys, and per-workspace
role isolation. This page is the reference for operators turning auth on for
a shared install. For a default `docker compose up` demo, auth is off — see
the README Quick Start.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `RAGRIG_AUTH_ENABLED` | `true` (`false` in shipped `.env.example`) | Enable auth enforcement. Set `false` only for local dev or single-user demos. |
| `RAGRIG_AUTH_SESSION_DAYS` | `30` | Session token lifetime in days. |
| `RAGRIG_AUTH_SECRET_PEPPER` | dev default | HMAC pepper for token hashing. **Always override in production.** |

To enable auth on a fresh deploy:

```bash
RAGRIG_AUTH_ENABLED=true
RAGRIG_AUTH_SECRET_PEPPER='<a long random string, kept secret>'
```

Restart the app so new sessions pick up the pepper.

## First-run setup

With auth enabled, navigate to the web console — you will be redirected to
the login page. Register the first account via **Create account**. The first
account automatically receives the `owner` role for the default workspace.

## Role-based access

| Role | Description |
| --- | --- |
| `owner` | Full access, including member management and role assignment |
| `admin` | Can manage members (except owner assignment) and all write operations |
| `editor` | Can write to knowledge bases, run pipelines, upload documents |
| `viewer` | Read-only access |

Write routes (`POST /knowledge-bases`, `POST /knowledge-bases/{name}/upload`,
pipeline and source operations) require `editor` or above. Processing-profile
mutations and rollbacks require `admin` or above.

## Member management

```bash
# List workspace members
curl /auth/workspace/members \
  -H "Authorization: Bearer rag_session_..."

# Change a member's role (admin/owner only)
curl -X PATCH /auth/workspace/members/{user_id} \
  -H "Authorization: Bearer rag_session_..." \
  -H "Content-Type: application/json" \
  -d '{"role": "editor"}'

# Remove a member (admin/owner only)
curl -X DELETE /auth/workspace/members/{user_id} \
  -H "Authorization: Bearer rag_session_..."
```

## API keys

Token-based API access is supported alongside browser sessions:

```bash
# Create an API key via a registered session (replace TOKEN and NAME)
curl -X POST /auth/api-keys \
  -H "Authorization: Bearer rag_session_..." \
  -H "Content-Type: application/json" \
  -d '{"name": "ci-key"}'

# Use the returned key on API requests
curl /knowledge-bases \
  -H "Authorization: Bearer rag_live_..."
```

API keys are hashed with HMAC-SHA256 plus the pepper — the plain key is
returned **once** at creation time.

## Enterprise SSO (P0)

LDAP, OIDC/OAuth2, and MFA/TOTP are wired through `/auth/login/ldap`,
`/auth/oidc/authorize` + `/auth/oidc/callback`, and `/auth/mfa/*`. See the
P0 enterprise security spec for the full surface and the relevant env vars.

## Local development (auth disabled)

```bash
RAGRIG_AUTH_ENABLED=false uv run uvicorn ragrig.main:app --reload
```

All requests are routed to the default workspace as an anonymous user. This
is also the default in the shipped `.env.example` so `docker compose up`
works without any login overhead.
