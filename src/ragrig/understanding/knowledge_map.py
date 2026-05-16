from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy.orm import Session

from ragrig.db.models import DocumentUnderstanding, KnowledgeBase
from ragrig.repositories import list_latest_document_versions
from ragrig.understanding.provider import compute_input_hash
from ragrig.understanding.schema import (
    KnowledgeMapEdge,
    KnowledgeMapNode,
    KnowledgeMapResult,
    KnowledgeMapStats,
    KnowledgeMapTopicCoverage,
    UnderstandingResult,
)

DEFAULT_KNOWLEDGE_MAP_PROFILE_ID = "*.understand.default"
_ENTITY_ID_SAFE_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class _MapEntity:
    key: str
    label: str
    entity_type: str
    mentions: int


@dataclass(frozen=True)
class _MapDocument:
    node_id: str
    document_id: str
    document_version_id: str
    understanding_id: str
    uri: str
    title: str
    topics: list[str]
    entities: dict[str, _MapEntity]


def build_knowledge_map(
    session: Session,
    knowledge_base_id: str,
    *,
    profile_id: str = DEFAULT_KNOWLEDGE_MAP_PROFILE_ID,
    generated_at: datetime | None = None,
) -> KnowledgeMapResult | None:
    """Build a cross-document knowledge map from fresh understanding records.

    The map is derived from the latest document version in the knowledge base.
    Completed but stale understanding records are excluded so the graph does not
    present outdated relationships as current evidence.
    """
    try:
        kb_uuid = uuid.UUID(knowledge_base_id)
    except ValueError:
        return None

    kb = session.get(KnowledgeBase, kb_uuid)
    if kb is None:
        return None

    versions = list_latest_document_versions(session, knowledge_base_id=kb_uuid)
    completed = 0
    missing = 0
    stale = 0
    failed = 0
    documents: list[_MapDocument] = []

    for version in versions:
        row = (
            session.query(DocumentUnderstanding)
            .filter(
                DocumentUnderstanding.document_version_id == version.id,
                DocumentUnderstanding.profile_id == profile_id,
            )
            .first()
        )
        if row is None:
            missing += 1
            continue
        if row.status == "failed":
            failed += 1
            continue
        if row.status != "completed":
            missing += 1
            continue

        current_hash = compute_input_hash(
            version.extracted_text,
            row.profile_id,
            row.provider,
            row.model,
        )
        if row.input_hash != current_hash:
            stale += 1
            continue

        completed += 1
        result = UnderstandingResult.from_raw(dict(row.result_json or {}))
        entities = _entities_from_result(result)
        documents.append(
            _MapDocument(
                node_id=f"document:{version.document_id}",
                document_id=str(version.document_id),
                document_version_id=str(version.id),
                understanding_id=str(row.id),
                uri=version.document.uri,
                title=_document_title(version.document.uri, result),
                topics=_document_topics(result, entities),
                entities=entities,
            )
        )

    nodes, edges, topic_coverage, edge_counts, cross_doc_entities = _build_graph(documents)
    isolated_documents = _count_isolated_documents(documents, edges)
    limitations = _limitations(
        total_versions=len(versions),
        completed=completed,
        missing=missing,
        stale=stale,
        failed=failed,
        included_documents=len(documents),
        document_relationship_edges=edge_counts["document_relationship"],
        cross_document_entity_count=cross_doc_entities,
    )
    status = _status(
        total_versions=len(versions),
        included_documents=len(documents),
        document_relationship_edges=edge_counts["document_relationship"],
    )

    stats = KnowledgeMapStats(
        total_versions=len(versions),
        completed=completed,
        missing=missing,
        stale=stale,
        failed=failed,
        included_documents=len(documents),
        document_nodes=sum(1 for node in nodes if node.kind == "document"),
        entity_nodes=sum(1 for node in nodes if node.kind == "entity"),
        document_relationship_edges=edge_counts["document_relationship"],
        mention_edges=edge_counts["mention"],
        co_mention_edges=edge_counts["co_mention"],
        cross_document_entity_count=cross_doc_entities,
        isolated_document_count=isolated_documents,
    )
    generated = generated_at or datetime.now(timezone.utc)
    return KnowledgeMapResult(
        generated_at=generated.isoformat(),
        knowledge_base_id=str(kb.id),
        knowledge_base=kb.name,
        profile_id=profile_id,
        status=status,
        nodes=nodes,
        edges=edges,
        topic_coverage=topic_coverage,
        stats=stats,
        limitations=limitations,
    )


def _entities_from_result(result: UnderstandingResult) -> dict[str, _MapEntity]:
    entities: dict[str, _MapEntity] = {}
    for entity in result.entities:
        label = entity.name.strip()
        if not label:
            continue
        key = _normalize_entity(label)
        if not key:
            continue
        mentions = max(1, int(entity.mentions or 1))
        existing = entities.get(key)
        if existing is not None:
            entities[key] = _MapEntity(
                key=key,
                label=existing.label,
                entity_type=existing.entity_type,
                mentions=existing.mentions + mentions,
            )
            continue
        entities[key] = _MapEntity(
            key=key,
            label=label,
            entity_type=entity.type or "TERM",
            mentions=mentions,
        )
    return entities


def _document_title(uri: str, result: UnderstandingResult) -> str:
    for entry in result.table_of_contents:
        if entry.level == 1 and entry.title.strip():
            return entry.title.strip()
    for entry in result.table_of_contents:
        if entry.title.strip():
            return entry.title.strip()
    name = PurePosixPath(uri).name
    return name or uri


def _document_topics(result: UnderstandingResult, entities: dict[str, _MapEntity]) -> list[str]:
    topics: list[str] = []
    for entry in result.table_of_contents:
        title = entry.title.strip()
        if title and title not in topics:
            topics.append(title)
    for entity in entities.values():
        if entity.label not in topics:
            topics.append(entity.label)
    return topics[:8]


def _build_graph(
    documents: list[_MapDocument],
) -> tuple[
    list[KnowledgeMapNode],
    list[KnowledgeMapEdge],
    list[KnowledgeMapTopicCoverage],
    dict[str, int],
    int,
]:
    nodes: list[KnowledgeMapNode] = []
    edges: list[KnowledgeMapEdge] = []
    entity_documents: dict[str, set[str]] = defaultdict(set)
    entity_labels: dict[str, str] = {}
    entity_types: dict[str, str] = {}
    entity_mentions: dict[str, int] = defaultdict(int)

    for doc in sorted(documents, key=lambda item: item.uri):
        nodes.append(
            KnowledgeMapNode(
                id=doc.node_id,
                kind="document",
                label=doc.title,
                document_id=doc.document_id,
                document_version_id=doc.document_version_id,
                uri=doc.uri,
                entity_count=len(doc.entities),
                topics=doc.topics,
                metadata={"understanding_id": doc.understanding_id},
            )
        )
        for entity in doc.entities.values():
            entity_documents[entity.key].add(doc.document_id)
            entity_labels.setdefault(entity.key, entity.label)
            entity_types.setdefault(entity.key, entity.entity_type)
            entity_mentions[entity.key] += entity.mentions

    for key in sorted(entity_labels, key=lambda item: entity_labels[item].lower()):
        nodes.append(
            KnowledgeMapNode(
                id=_entity_node_id(key),
                kind="entity",
                label=entity_labels[key],
                entity_type=entity_types[key],
                mentions=entity_mentions[key],
                document_count=len(entity_documents[key]),
                metadata={"document_ids": sorted(entity_documents[key])},
            )
        )

    mention_edges = _mention_edges(documents)
    document_edges = _document_relationship_edges(documents)
    co_mention_edges = _co_mention_edges(documents)
    edges.extend(document_edges)
    edges.extend(mention_edges)
    edges.extend(co_mention_edges)

    included_document_count = max(1, len(documents))
    topic_coverage = [
        KnowledgeMapTopicCoverage(
            topic=entity_labels[key],
            document_count=len(doc_ids),
            coverage_pct=round((len(doc_ids) / included_document_count) * 100, 2),
            document_ids=sorted(doc_ids),
        )
        for key, doc_ids in sorted(
            entity_documents.items(),
            key=lambda item: (-len(item[1]), entity_labels[item[0]].lower()),
        )
    ][:20]

    edge_counts = {
        "document_relationship": len(document_edges),
        "mention": len(mention_edges),
        "co_mention": len(co_mention_edges),
    }
    cross_document_entities = sum(1 for doc_ids in entity_documents.values() if len(doc_ids) > 1)
    return nodes, edges, topic_coverage, edge_counts, cross_document_entities


def _mention_edges(documents: list[_MapDocument]) -> list[KnowledgeMapEdge]:
    edges: list[KnowledgeMapEdge] = []
    max_mentions = max(
        (entity.mentions for doc in documents for entity in doc.entities.values()),
        default=1,
    )
    for doc in sorted(documents, key=lambda item: item.uri):
        for entity in sorted(doc.entities.values(), key=lambda item: item.label.lower()):
            strength = round(min(1.0, entity.mentions / max_mentions), 4)
            edges.append(
                KnowledgeMapEdge(
                    id=f"mentions:{doc.document_id}:{_entity_slug(entity.key)}",
                    source=doc.node_id,
                    target=_entity_node_id(entity.key),
                    relationship="mentions",
                    strength=strength,
                    evidence=f"{doc.title} mentions {entity.label}.",
                    metadata={"mentions": entity.mentions},
                )
            )
    return edges


def _document_relationship_edges(documents: list[_MapDocument]) -> list[KnowledgeMapEdge]:
    edges: list[KnowledgeMapEdge] = []
    for left, right in combinations(sorted(documents, key=lambda item: item.uri), 2):
        left_entities = set(left.entities)
        right_entities = set(right.entities)
        shared = sorted(left_entities & right_entities)
        if not shared:
            continue
        union_count = len(left_entities | right_entities) or 1
        labels = [_entity_label(left, right, key) for key in shared]
        edges.append(
            KnowledgeMapEdge(
                id=f"shares_entities:{left.document_id}:{right.document_id}",
                source=left.node_id,
                target=right.node_id,
                relationship="shares_entities",
                strength=round(len(shared) / union_count, 4),
                evidence="Shared entities: " + ", ".join(labels),
                shared_entities=labels,
                document_count=2,
            )
        )
    return edges


def _co_mention_edges(documents: list[_MapDocument]) -> list[KnowledgeMapEdge]:
    pair_documents: dict[tuple[str, str], set[str]] = defaultdict(set)
    for doc in documents:
        for left, right in combinations(sorted(doc.entities), 2):
            pair_documents[(left, right)].add(doc.document_id)

    document_count = max(1, len(documents))
    edges: list[KnowledgeMapEdge] = []
    entity_lookup = {
        entity.key: entity.label for doc in documents for entity in doc.entities.values()
    }
    for (left, right), doc_ids in sorted(
        pair_documents.items(),
        key=lambda item: (-len(item[1]), item[0][0], item[0][1]),
    ):
        left_label = entity_lookup.get(left, left)
        right_label = entity_lookup.get(right, right)
        edges.append(
            KnowledgeMapEdge(
                id=f"co_mentions:{_entity_slug(left)}:{_entity_slug(right)}",
                source=_entity_node_id(left),
                target=_entity_node_id(right),
                relationship="co_mentioned",
                strength=round(len(doc_ids) / document_count, 4),
                evidence=f"{left_label} and {right_label} appear together.",
                document_count=len(doc_ids),
                metadata={"document_ids": sorted(doc_ids)},
            )
        )
    return edges


def _count_isolated_documents(documents: list[_MapDocument], edges: list[KnowledgeMapEdge]) -> int:
    connected: set[str] = set()
    document_node_ids = {doc.node_id for doc in documents}
    for edge in edges:
        if edge.relationship != "shares_entities":
            continue
        if edge.source in document_node_ids:
            connected.add(edge.source)
        if edge.target in document_node_ids:
            connected.add(edge.target)
    return len(document_node_ids - connected)


def _limitations(
    *,
    total_versions: int,
    completed: int,
    missing: int,
    stale: int,
    failed: int,
    included_documents: int,
    document_relationship_edges: int,
    cross_document_entity_count: int,
) -> list[str]:
    limitations: list[str] = []
    if total_versions == 0:
        limitations.append("Knowledge base has no document versions to map.")
    if missing:
        limitations.append(
            f"{missing} latest document version(s) are missing understanding output."
        )
    if stale:
        limitations.append(f"{stale} understanding output(s) are stale and were excluded.")
    if failed:
        limitations.append(f"{failed} understanding output(s) failed and were excluded.")
    if completed and included_documents < 2:
        limitations.append("At least two fresh understanding outputs are needed for relationships.")
    if included_documents >= 2 and document_relationship_edges == 0:
        limitations.append("No document pair shares extracted entities yet.")
    if included_documents >= 2 and cross_document_entity_count == 0:
        limitations.append("No extracted entity appears in more than one document.")
    return limitations


def _status(
    *,
    total_versions: int,
    included_documents: int,
    document_relationship_edges: int,
) -> str:
    if total_versions == 0:
        return "empty_kb"
    if included_documents == 0:
        return "no_understanding"
    if document_relationship_edges == 0:
        return "limited"
    return "ready"


def _entity_label(left: _MapDocument, right: _MapDocument, key: str) -> str:
    if key in left.entities:
        return left.entities[key].label
    return right.entities[key].label


def _normalize_entity(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def _entity_slug(value: str) -> str:
    slug = _ENTITY_ID_SAFE_RE.sub("-", value.casefold()).strip("-")
    return slug or "unknown"


def _entity_node_id(key: str) -> str:
    return f"entity:{_entity_slug(key)}"


def knowledge_map_to_dict(result: KnowledgeMapResult) -> dict[str, Any]:
    return result.model_dump(mode="json")
