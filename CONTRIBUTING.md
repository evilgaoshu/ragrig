# Contributing to RAGRig

Thanks for your interest in RAGRig.

RAGRig is early, so the most valuable contributions are clear problem reports, connector requirements, deployment constraints, and focused patches that make the first vertical slice stronger.

## Contribution Areas

- document parsers and source connectors
- Qdrant and pgvector indexing behavior
- retrieval, reranking, and citation quality
- permission-aware retrieval and metadata filtering
- local model support
- documentation, examples, and deployment notes

## Development Principles

- Keep the core small and observable.
- Preserve source provenance through every pipeline step.
- Prefer explicit capability matrices over leaky lowest-common-denominator abstractions.
- Treat permissions as retrieval constraints, not post-processing cleanup.
- Add tests for behavior that affects indexing, retrieval, permissions, or source traceability.

## Pull Requests

Before opening a pull request:

1. Keep the change focused.
2. Update docs when behavior changes.
3. Add or update tests when the change touches core behavior.
4. Explain how you verified the change.

## Branch Strategy

Use short-lived branches off `main`. Prefer names that make the change type
and scope obvious:

- `feature/<short-topic>` for user-visible capabilities
- `fix/<short-topic>` for bug fixes
- `docs/<short-topic>` for documentation-only changes
- `chore/<short-topic>` for dependency, CI, or maintenance work

Keep each branch focused on one reviewable outcome. Rebase or merge from
`main` before opening a PR when the branch is behind or when CI behavior changed
recently. Do not mix generated artifacts, dependency lockfile churn, and
application changes unless the PR needs all of them to pass.

## Commit Messages

Use concise imperative subjects. Conventional prefixes are encouraged because
they make changelogs and dependency automation easier to scan:

- `feat: add source connector health checks`
- `fix: preserve workspace filter during retrieval`
- `docs: record pgvector backend decision`
- `test: cover knowledge service permission failures`
- `chore(deps): bump frontend dependencies`

Include a body when the motivation, migration impact, security tradeoff, or
verification evidence is not obvious from the diff.

## Local Verification

For backend changes, run the narrowest relevant tests plus the standard quality
gates before opening the PR:

```bash
uv run ruff format . --check
uv run ruff check .
uv run pytest <changed-area-tests> -q
```

For frontend changes:

```bash
cd frontend
npm ci
npm run lint
npm audit --audit-level=high
npm run build
```

For dependency or container changes, also run the matching audit/build path
locally when practical:

```bash
make audit
make licenses
docker build -t ragrig:local .
```

CI is the source of truth for required checks on PRs to `main`. If a check is
skipped by design, say why in the PR description.

## License

By contributing, you agree that your contribution will be licensed under the Apache License 2.0.
