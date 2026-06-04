# Vercel Deployment Simplification Design

## Goal

Use Vercel Git integration as the only deployment path so GitHub reports two
environments: `Preview` for pull requests and `Production` for `main`.

## Current State

- Vercel Git integration already creates Preview deployments for pull requests.
- Vercel Git integration already creates Production deployments for `main`.
- `demo.ragrig.dev` is already attached to the Vercel project and resolves to the
  latest Production deployment.
- `.github/workflows/vercel-demo-deploy.yml` creates a second Production
  deployment for every `main` push and records it as a third GitHub environment
  named `demo`.

## Design

Delete the custom demo deployment workflow and rely on Vercel Git integration.
Keep the hosted demo URL and read-only credentials in both READMEs. Document that
`demo.ragrig.dev` is a Production Domain and that Preview deployments receive
unique Vercel URLs.

The repository test suite will guard against reintroducing the duplicate
workflow while continuing to verify the hosted demo links and Preview smoke
entrypoint.

After the change reaches `main` and Vercel Production is healthy, delete the
empty GitHub `demo` Environment. No Vercel project domains, application
environment variables, or Supabase settings change.

## Verification

- Deployment-focused pytest module passes.
- Ruff format and lint pass.
- GitHub Actions no longer runs `Deploy Demo to Vercel`.
- `demo.ragrig.dev/health` returns HTTP 200 from Vercel Production.
- GitHub Deployments lists only `Preview` and `Production`.
