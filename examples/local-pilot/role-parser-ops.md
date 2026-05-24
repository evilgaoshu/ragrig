# RAGRig Role and Parser Operations

RoleModelRouter persists role-specific model configuration at the knowledge-base
level. AdminReviewer uses precise-answer models, ViewerAnalyst uses economical
local models, and GraphExtraction uses a cheap structured extraction model.

RoleUsageLedger groups cost and latency by role so operators can compare
AdminReviewer, ViewerAnalyst, GraphExtraction, and ParserOCR behavior over time.

ParserBridge selects DoclingAdapter before MinerUAdapter for layout-aware PDF,
DOCX, PPTX, and XLSX extraction. If optional parser dependencies are missing,
the bridge records skipped adapters and falls back to the standard parser path.

ParserCorpusGate reports healthy, degraded, skipped, and failed fixture counts
for advanced parser coverage. It should expose real parser availability instead
of pretending optional dependencies are installed.
