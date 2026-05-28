# Demo Graph Console Runbook

Use this for the external GraphRAG demo path:

```bash
make demo-graph-console
```

The target prepares `docs/operations/artifacts/demo-graph-console.db`, runs the
demo RC gate, saves the Console retrieval mode preference as `hybrid_graph`, and
starts the Web Console at `http://127.0.0.1:8000/console`.

For CI or PR evidence without starting a blocking web server:

```bash
make demo-graph-console-runbook
```

For a browser-level rehearsal without a blocking server:

```bash
make demo-graph-console-smoke
```

For the live talk track, fixed questions, and fallback responses, use
`docs/operations/external-demo-script.md`.

Artifacts:

- `docs/operations/artifacts/demo-graph-console-runbook.json`
- `docs/operations/artifacts/demo-graph-console-runbook.md`
- `docs/operations/artifacts/demo-rc-gate.json`
- `docs/operations/artifacts/demo-rc-gate.md`
- `docs/operations/artifacts/demo-graph-console-smoke.json`

One-page external demo checklist:

| Moment | Pass Signal |
|---|---|
| Preflight | `make demo-graph-console-runbook` returns `pass`. |
| Browser smoke | `make demo-graph-console-smoke` records graph, retrieval, compare, and feedback evidence. |
| Opening | Graph Explorer shows entities, relations, claims, evidence, and feedback controls. |
| Core loop | Retrieval Lab loads `hybrid_graph`, compares `dense`, `graph`, and `hybrid_graph`, then shows graph context. |
| Feedback | Marking a bad relation increments feedback and the next graph trace reports suppressed relations. |
| Cleanup | `make demo-graph-console-cleanup CONFIRM_DELETE=1` removes local demo artifacts after rehearsal. |

Expected Console path:

1. Open Graph Explorer and confirm entities, relations, claims, evidence, and
   feedback counts are visible.
2. Open Retrieval Lab and load the saved mode preference.
3. Run Compare Modes for `dense`, `graph`, and `hybrid_graph`.
4. Mark an incorrect relation from Graph Explorer or Graph Context and rerun
   retrieval; the suppressed relation count should update on the next graph
   retrieval trace.

Cleanup after a local rehearsal:

```bash
make demo-graph-console-cleanup CONFIRM_DELETE=1
```
