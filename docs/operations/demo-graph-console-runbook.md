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

Artifacts:

- `docs/operations/artifacts/demo-graph-console-runbook.json`
- `docs/operations/artifacts/demo-graph-console-runbook.md`
- `docs/operations/artifacts/demo-rc-gate.json`
- `docs/operations/artifacts/demo-rc-gate.md`

Expected Console path:

1. Open Graph Explorer and confirm entities, relations, claims, evidence, and
   feedback counts are visible.
2. Open Retrieval Lab and load the saved mode preference.
3. Run Compare Modes for `dense`, `graph`, and `hybrid_graph`.
4. Mark an incorrect relation from Graph Explorer or Graph Context and rerun
   retrieval; the suppressed relation count should update on the next graph
   retrieval trace.
