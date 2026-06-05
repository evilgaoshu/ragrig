"""Compatibility exports for ORM entities.

Model definitions live in the domain modules next to this file. Keep this
module import-compatible for older callers that import from
``ragrig.db.models.entities`` directly.
"""

from ragrig.db.models.corpus import (
    Chunk,
    Document,
    DocumentSummary,
    DocumentVersion,
    Embedding,
    KnowledgeBase,
    Source,
)
from ragrig.db.models.graph import (
    ConflictReview,
    KnowledgeGraphClaim,
    KnowledgeGraphEntity,
    KnowledgeGraphEntityMention,
    KnowledgeGraphRelation,
    KnowledgeGraphRelationEvidence,
    SemanticCacheEntry,
)
from ragrig.db.models.identity import (
    ApiKey,
    KnowledgeBasePermission,
    User,
    UserSession,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from ragrig.db.models.interaction import (
    AnswerFeedback,
    Budget,
    Conversation,
    ConversationTurn,
    UsageEvent,
)
from ragrig.db.models.pipeline import (
    AuditEvent,
    DocumentUnderstanding,
    PipelineRun,
    PipelineRunItem,
    ProcessingProfileAuditLog,
    ProcessingProfileOverride,
    TaskRecord,
    UnderstandingRun,
)

__all__ = [
    "Workspace",
    "User",
    "WorkspaceMembership",
    "KnowledgeBasePermission",
    "ApiKey",
    "UserSession",
    "WorkspaceInvitation",
    "KnowledgeBase",
    "Source",
    "Document",
    "DocumentVersion",
    "Chunk",
    "Embedding",
    "DocumentSummary",
    "KnowledgeGraphEntity",
    "KnowledgeGraphEntityMention",
    "KnowledgeGraphRelation",
    "KnowledgeGraphRelationEvidence",
    "KnowledgeGraphClaim",
    "SemanticCacheEntry",
    "ConflictReview",
    "PipelineRun",
    "PipelineRunItem",
    "DocumentUnderstanding",
    "ProcessingProfileOverride",
    "ProcessingProfileAuditLog",
    "AuditEvent",
    "TaskRecord",
    "UnderstandingRun",
    "Conversation",
    "ConversationTurn",
    "AnswerFeedback",
    "UsageEvent",
    "Budget",
]
