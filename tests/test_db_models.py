from sqlalchemy import MetaData

from ragrig.db.models import Base


def test_phase_1a_metadata_defines_core_tables() -> None:
    metadata: MetaData = Base.metadata

    assert {
        "knowledge_bases",
        "sources",
        "documents",
        "document_versions",
        "chunks",
        "embeddings",
        "pipeline_runs",
        "pipeline_run_items",
    }.issubset(metadata.tables.keys())

    documents = metadata.tables["documents"]
    document_versions = metadata.tables["document_versions"]
    embeddings = metadata.tables["embeddings"]
    pipeline_runs = metadata.tables["pipeline_runs"]

    assert documents.c.id.primary_key
    assert document_versions.c.document_id.references(documents.c.id)
    assert embeddings.c.chunk_id.references(metadata.tables["chunks"].c.id)
    assert embeddings.c.dimensions.nullable is False
    assert str(embeddings.c.embedding.type) == "VECTOR"

    document_fk_targets = {
        element.target_fullname
        for fk in documents.foreign_key_constraints
        for element in fk.elements
    }
    pipeline_run_fk_targets = {
        element.target_fullname
        for fk in pipeline_runs.foreign_key_constraints
        for element in fk.elements
    }

    assert {"sources.knowledge_base_id", "sources.id"}.issubset(document_fk_targets)
    assert {"sources.knowledge_base_id", "sources.id"}.issubset(pipeline_run_fk_targets)


def test_chunks_and_embeddings_support_one_to_many_embeddings() -> None:
    embeddings = Base.metadata.tables["embeddings"]

    fk_targets = {
        element.target_fullname
        for fk in embeddings.foreign_key_constraints
        for element in fk.elements
    }

    assert fk_targets == {"chunks.id"}


def test_sources_expose_composite_key_for_same_knowledge_base_references() -> None:
    sources = Base.metadata.tables["sources"]

    composite_uniques = [
        tuple(column.name for column in constraint.columns)
        for constraint in sources.constraints
        if getattr(constraint, "__visit_name__", None) == "unique_constraint"
    ]

    assert ("knowledge_base_id", "id") in composite_uniques
