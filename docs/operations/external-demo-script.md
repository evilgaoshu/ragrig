# External Demo Script

Use this script for the external user demo. The product story is the RAG loop:
source documents become indexed evidence, retrieval stays explainable, answers
stay citation-backed, and evaluation artifacts make quality visible. GraphRAG is
a trust and comparison layer, not the main product surface.

## Preflight

Run these before the call:

```bash
make demo-graph-console-smoke
make demo-graph-console
```

Open:

```text
http://127.0.0.1:8000/
```

Expected proof points:

- Browser smoke status is `passed`.
- Runbook status is `pass`.
- Knowledge Map shows entities, relations, claims, evidence, and relation feedback controls.
- Retrieval Lab shows `hybrid_graph` mode and the comparison board.
- Relation feedback produces a suppressed relation on the next graph retrieval.

## Talk Track

| Time | Surface | Action | Message |
|---|---|---|---|
| 0:00 | Console | Open the Console root. | RAGRig is a local-first RAG workbench with evidence, evals, and operations visibility. |
| 1:00 | Knowledge Map | Show entities, relations, claims, and evidence. | The graph is a retrieval trace layer. It helps explain why chunks were boosted. |
| 2:30 | Retrieval Lab | Show the mode selector and default comparison. | The demo knowledge base is pinned to `hybrid_graph` without changing API defaults. |
| 3:30 | Retrieval Lab | Run Compare Modes. | Dense, graph, and hybrid graph are compared side by side against the same query. |
| 5:30 | Graph feedback | Mark one relation as incorrect. | Reviewers can correct bad graph edges without treating the graph as unquestioned truth. |
| 6:30 | Retrieval Lab | Rerun retrieval. | The next graph trace reports suppressed relations, so feedback changes ranking behavior. |
| 8:00 | Artifacts | Show runbook or JSON evidence. | Demo readiness is repeatable: checks, eval comparison, and smoke evidence are written to artifacts. |

## Demo Queries

Use these in order. They are covered by the demo golden set and avoid wandering
into unsupported product claims.

1. `What makes a Local Pilot answer trustworthy?`
2. `Which workflow steps are visible before trusting the answer?`
3. `Which query mode should show relation paths, matched entities, and boosted chunks?`
4. `Which board compares DenseMode, GraphMode, and HybridGraphMode?`
5. `What should happen to an incorrect graph relation after RelationFeedback?`

## Bad-Weather Playbook

| Symptom | Response |
|---|---|
| Browser smoke fails before the call. | Run `make demo-graph-console-runbook` and use the generated markdown/JSON evidence. Do not live-debug browser dependencies on the call. |
| Graph mode does not beat dense for one query. | Say the graph is an explainability and feedback layer, and the eval compares strategy behavior instead of promising every query improves. |
| Answer provider is unavailable. | Use retrieval results and citations. The demo is valid without cloud keys. |
| Feedback buttons are not visible. | Open Knowledge Map, then use the relation feedback controls in Evidence detail. |
| The question drifts to production knowledge graph scope. | Re-anchor: KG-lite is source-backed retrieval support; Neo4j, community detection, and LLM entity resolution are later phases. |

## Do Not Demo

- Tailwind 4 dependency PR.
- Interactive graph visualization. Current Graph Explorer is intentionally a list/evidence view.
- Production-grade knowledge graph claims such as entity resolution at scale.
- Unsupported connector promises beyond the current roadmap.
- OCR-heavy multimodal parsing as a live path unless optional parser dependencies were validated separately.

## Close

Close with the main product value:

- Ingested documents become indexed, retrievable evidence.
- Users can inspect retrieval traces and citations.
- GraphRAG adds comparison and feedback where multi-document relationships matter.
- Evaluation artifacts make demo readiness reproducible.

After the rehearsal:

```bash
make demo-graph-console-cleanup CONFIRM_DELETE=1
```
