# Graph Retrieval Evaluation Comparison

- Generated at: `2026-06-09T07:53:16.142815Z`
- Knowledge base: `local-pilot-graph-compare`
- Baseline mode: `dense`
- Winner: `hybrid_graph`
- Quality gate: `pass`

## Metrics

| Metric | dense | graph | hybrid_graph |
|---|---:|---:|---:|
| hit_at_1 | 0.1875 | 0.1875 | **0.3750** |
| hit_at_3 | 0.5000 | **0.6875** | 0.6875 |
| hit_at_5 | 0.6250 | **0.7500** | 0.7500 |
| mrr | 0.3479 | 0.4115 | **0.5333** |
| citation_coverage_mean | 0.6823 | 0.7483 | **0.7835** |
| context_precision_mean | 0.0267 | 0.0800 | **0.0933** |
| context_recall_mean | 0.1333 | 0.2667 | **0.3333** |
| zero_result_rate | **0.0000** | 0.0000 | 0.0000 |
| latency_ms_mean | **7.6900** | 75.6200 | 73.7900 |
| latency_ms_p95 | **10.7000** | 105.6300 | 103.6200 |

## Graph Value Summary

| Mode | Improved | Regressed | New hits | Lost hits | Graph-focus improvements |
|---|---:|---:|---:|---:|---:|
| graph | 4 | 2 | 3 | 1 | 3 |
| hybrid_graph | 7 | 3 | 4 | 2 | 3 |

## Soft Quality Gate

| Mode | Status | hit_at_5 Δ | zero_result_rate Δ |
|---|---|---:|---:|
| graph | pass | +0.1250 | +0.0000 |
| hybrid_graph | pass | +0.1250 | +0.0000 |

## Graph-RAG Contract Gate

- Status: `pass`
- x_y_relationship_query: `pass`
- cross_document_relation: `pass`
- feedback_suppresses_relation: `pass`
- feedback_changes_chunk_scores: `pass`
- citations_are_chunk_and_document_backed: `pass`

## Graph-Focused Per-Tag Delta

| Mode | Tag | hit_at_5 Δ | MRR Δ | context_recall_mean Δ |
|---|---|---:|---:|---:|
| graph | graph | +0.2857 | +0.1976 | +0.1428 |
| graph | multi-hop | +0.6667 | +0.4444 | +0.3333 |
| graph | cross-doc | +0.6667 | +0.4444 | +0.3333 |
| hybrid_graph | graph | +0.1428 | +0.2333 | +0.1428 |
| hybrid_graph | multi-hop | +0.6667 | +0.6111 | +0.3333 |
| hybrid_graph | cross-doc | +0.6667 | +0.6111 | +0.3333 |

## Question-Level Movement

| Mode | Question | Tags | Dense rank | Mode rank | Rank Δ | Recall Δ |
|---|---|---|---:|---:|---:|---:|
| graph | What makes a Local Pilot answer trustworthy? | demo, single-hop, citation-trust |  | 3 | +99.0000 | +0.0000 |
| graph | How do the handbook and FAQ together explain grounded citations? | demo, multi-hop, cross-doc, graph |  | 1 | +99.0000 | +1.0000 |
| graph | Why did IncidentA12 need graph retrieval? | demo, graph, multi-hop, cross-doc |  | 3 | +99.0000 | +0.0000 |
| hybrid_graph | What makes a Local Pilot answer trustworthy? | demo, single-hop, citation-trust |  | 2 | +99.0000 | +1.0000 |
| hybrid_graph | How do the handbook and FAQ together explain grounded citations? | demo, multi-hop, cross-doc, graph |  | 1 | +99.0000 | +1.0000 |
| hybrid_graph | Should missing OpenRouter keys block the local pilot demo? | demo, conflict-sensitive, credentials |  | 5 | +99.0000 | +0.0000 |
| hybrid_graph | Why did IncidentA12 need graph retrieval? | demo, graph, multi-hop, cross-doc |  | 3 | +99.0000 | +0.0000 |
| hybrid_graph | Where is role-specific model configuration persisted? | demo, role-models, cost-latency | 3 | 1 | +2.0000 | +0.0000 |
| hybrid_graph | What does ParserCorpusGate report for advanced parser coverage? | demo, multimodal, parser-adapter | 3 | 1 | +2.0000 | +0.0000 |
| graph | How should reviewers handle a wrong graph edge? | demo, graph, feedback | 5 | 4 | +1.0000 | +0.0000 |
| hybrid_graph | How does EvidenceBridge connect CompanyHandbook and SupportFAQ for grounded cita | demo, graph, multi-hop, cross-doc | 2 | 1 | +1.0000 | +0.0000 |
| graph | Summarize the demo's end-to-end RAG workflow. | demo, global, synthesis |  |  |  |  |
