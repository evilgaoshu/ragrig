# RAGRig Local Pilot Graph Playbook

AtlasRunbook links PipelineRun and CitationPanel so reviewers can trace upload,
parsing, retrieval, and grounded answer evidence.

EvidenceBridge connects CompanyHandbook and SupportFAQ. It shows that handbook
workflow steps and FAQ evidence chunks must be read together before trusting
grounded citations.

ModeSwitcher compares DenseMode and HybridGraphMode for one query.
HybridGraphMode should surface relation paths, matched entities, and boosted
chunks.

RelationFeedback lets reviewers mark a wrong edge as incorrect without deleting
source chunks.

RoleModelRouter assigns AdminReviewer to precise-answer models and ViewerAnalyst
to economical local models, then records role cost and latency.

ParserBridge routes scanned PDFs through DoclingAdapter or MinerUAdapter when
layout tables or OCR evidence are needed.
