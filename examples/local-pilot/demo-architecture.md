# RAGRig Demo Architecture Notes

AtlasRunbook owns PipelineRun recovery. PipelineRun emits CitationPanel trace
identifiers so reviewers can verify which source chunk supported an answer.

StrategyCompareBoard runs DenseMode, GraphMode, and HybridGraphMode against the
same query. The board records top document, score movement, relation path count,
and graph diagnostics for each strategy.

FeedbackAwareRetrieval reads RelationFeedback before graph expansion. A relation
marked incorrect should be suppressed from graph boosting while the original
source chunks remain searchable.

GraphQualityGate compares dense and graph modes on multi-hop and cross-document
tags. The gate is useful only when it reports question-level rank movement, new
hits, lost hits, and graph-focus improvements.
