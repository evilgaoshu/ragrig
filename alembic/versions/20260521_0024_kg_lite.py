"""KG-lite persistent graph tables.

Revision ID: 20260521_0024
Revises: 20260518_0023
Create Date: 2026-05-21

Adds source-backed entity, mention, relation, relation evidence, and claim
tables.  The graph is scoped by knowledge base and workspace, and every
relation/claim carries chunk-level evidence so GraphRAG retrieval can be
audited back to the original document text.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260521_0024"
down_revision = "20260518_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kg_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("canonical_name", sa.String(512), nullable=False),
        sa.Column("display_name", sa.String(512), nullable=False),
        sa.Column("entity_type", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("extractor_version", sa.String(128), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_kg_entities_confidence_range",
        ),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "knowledge_base_id",
            "canonical_name",
            name="uq_kg_entities_kb_canonical_name",
        ),
    )
    op.create_index(
        "ix_kg_entities_kb_name", "kg_entities", ["knowledge_base_id", "canonical_name"]
    )
    op.create_index("ix_kg_entities_workspace_id", "kg_entities", ["workspace_id"])

    op.create_table(
        "kg_entity_mentions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mention_text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("extractor_version", sa.String(128), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_kg_entity_mentions_confidence_range",
        ),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["entity_id"], ["kg_entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_kg_entity_mentions_chunk_id", "kg_entity_mentions", ["chunk_id"])
    op.create_index("ix_kg_entity_mentions_document_id", "kg_entity_mentions", ["document_id"])
    op.create_index("ix_kg_entity_mentions_entity_id", "kg_entity_mentions", ["entity_id"])

    op.create_table(
        "kg_relations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("predicate", sa.String(128), nullable=False),
        sa.Column("object_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("extractor_version", sa.String(128), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_kg_relations_confidence_range",
        ),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["object_entity_id"], ["kg_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_entity_id"], ["kg_entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "knowledge_base_id",
            "subject_entity_id",
            "predicate",
            "object_entity_id",
            name="uq_kg_relations_kb_triplet",
        ),
    )
    op.create_index(
        "ix_kg_relations_kb_predicate", "kg_relations", ["knowledge_base_id", "predicate"]
    )
    op.create_index("ix_kg_relations_object_entity_id", "kg_relations", ["object_entity_id"])
    op.create_index("ix_kg_relations_subject_entity_id", "kg_relations", ["subject_entity_id"])
    op.create_index("ix_kg_relations_workspace_id", "kg_relations", ["workspace_id"])

    op.create_table(
        "kg_relation_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("relation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("extractor_version", sa.String(128), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_kg_relation_evidence_confidence_range",
        ),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["relation_id"], ["kg_relations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_kg_relation_evidence_chunk_id", "kg_relation_evidence", ["chunk_id"])
    op.create_index("ix_kg_relation_evidence_relation_id", "kg_relation_evidence", ["relation_id"])

    op.create_table(
        "kg_claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("extractor_version", sa.String(128), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_kg_claims_confidence_range",
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["document_version_id"], ["document_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_chunk_id"], ["chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_kg_claims_knowledge_base_id", "kg_claims", ["knowledge_base_id"])
    op.create_index("ix_kg_claims_source_chunk_id", "kg_claims", ["source_chunk_id"])
    op.create_index("ix_kg_claims_workspace_id", "kg_claims", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_kg_claims_workspace_id", table_name="kg_claims")
    op.drop_index("ix_kg_claims_source_chunk_id", table_name="kg_claims")
    op.drop_index("ix_kg_claims_knowledge_base_id", table_name="kg_claims")
    op.drop_table("kg_claims")

    op.drop_index("ix_kg_relation_evidence_relation_id", table_name="kg_relation_evidence")
    op.drop_index("ix_kg_relation_evidence_chunk_id", table_name="kg_relation_evidence")
    op.drop_table("kg_relation_evidence")

    op.drop_index("ix_kg_relations_workspace_id", table_name="kg_relations")
    op.drop_index("ix_kg_relations_subject_entity_id", table_name="kg_relations")
    op.drop_index("ix_kg_relations_object_entity_id", table_name="kg_relations")
    op.drop_index("ix_kg_relations_kb_predicate", table_name="kg_relations")
    op.drop_table("kg_relations")

    op.drop_index("ix_kg_entity_mentions_entity_id", table_name="kg_entity_mentions")
    op.drop_index("ix_kg_entity_mentions_document_id", table_name="kg_entity_mentions")
    op.drop_index("ix_kg_entity_mentions_chunk_id", table_name="kg_entity_mentions")
    op.drop_table("kg_entity_mentions")

    op.drop_index("ix_kg_entities_workspace_id", table_name="kg_entities")
    op.drop_index("ix_kg_entities_kb_name", table_name="kg_entities")
    op.drop_table("kg_entities")
