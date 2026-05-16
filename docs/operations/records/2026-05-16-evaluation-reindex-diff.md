# Evaluation Reindex Diff

Date: 2026-05-16

## Scope

This record closes the Phase 4 roadmap item for a full evaluation comparison workflow: before/after reindex diff report.

The workflow is intentionally fixture-local and deterministic. It uses an ephemeral SQLite database, evaluates the golden question set before a forced reindex, evaluates it again after the reindex, and writes both JSON and Markdown diff artifacts.

## Evidence

Primary command:

```bash
make eval-reindex-diff
```

Primary artifacts:

```text
docs/operations/artifacts/eval-reindex-diff.json
docs/operations/artifacts/eval-reindex-diff.md
```

Supporting tests:

```bash
uv run pytest tests/test_eval_reindex_diff.py tests/test_eval_local_script.py tests/test_indexing_pipeline.py
```

## Contract

The report status is:

- `pass` when both runs complete and no metric or item regression is detected
- `degraded` when the workflow completes but a metric or item regresses
- `failure` when indexing or evaluation fails

The default before/after chunking configuration is identical, so the repository fixture should pass. Operators can set `--after-chunk-size` to exercise indexing drift intentionally.
