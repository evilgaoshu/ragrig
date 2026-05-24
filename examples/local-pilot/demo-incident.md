# RAGRig Demo Incident Record

IncidentA12 showed why graph retrieval is needed for external demos. DenseMode
found SupportFAQ, but HybridGraphMode linked SupportFAQ, CompanyHandbook, and
EvidenceBridge before returning grounded citation evidence.

CloudKeyPolicy says missing OpenRouter keys are optional readiness signals, not
startup blockers. The Local Pilot must continue to run retrieval and grounded
answer checks when cloud credentials are absent.

WrongEdgeReview captured a bad co-mention relation between CloudKeyPolicy and
BillingPolicy. After RelationFeedback marked the edge incorrect, graph retrieval
stopped using that relation for boosting but still allowed direct source search.
