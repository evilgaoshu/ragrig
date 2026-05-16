# Evaluation Reindex Diff SPEC

**Version**: 1.0.0
**Last Updated**: 2026-05-16
**Status**: Implemented

## Scope

The evaluation reindex diff workflow runs the same golden question set before and after a forced reindex, then emits a JSON and Markdown report that reviewers can use to detect retrieval regressions caused by indexing changes.

Default command:

```bash
make eval-reindex-diff
```

Default artifacts:

```text
docs/operations/artifacts/eval-reindex-diff.json
docs/operations/artifacts/eval-reindex-diff.md
```

## Workflow

1. Create an ephemeral SQLite database.
2. Ingest `tests/fixtures/local_ingestion`.
3. Index the fixture knowledge base with the before chunking config.
4. Run the golden evaluation.
5. Force a reindex with the after chunking config.
6. Run the golden evaluation again.
7. Compare metrics and per-question outputs.

The default before and after chunking config is identical, so the fixture workflow is expected to pass with no regressions. Operators can pass a different `--after-chunk-size` to intentionally test indexing drift.

## Report Contract

The JSON artifact includes:

- `artifact="evaluation-reindex-diff"`
- `schema_version`
- `status`: `pass`, `degraded`, or `failure`
- `workflow`: knowledge base, fixture paths, chunking config, and backend mode
- `before` / `after`: run IDs, indexing summaries, and metrics
- `metric_deltas`: before/after/delta/status rows
- `item_diffs`: per-question hit/rank/MRR/citation/top-document changes
- `summary`: regression and change counts
- `markdown_summary`: the Markdown report body

Status semantics:

- `pass`: both evaluation runs completed and no metric or item regression was detected.
- `degraded`: the workflow completed but at least one metric or item regressed.
- `failure`: indexing failed, an evaluation run failed, or the artifact could not be produced.

## CI

The `Evaluation Diff` workflow runs `make eval-reindex-diff` on pull requests and uploads the JSON/Markdown artifacts with the evaluation artifact bundle.
