from __future__ import annotations

import re
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ragrig.acl import acl_permits_chunk_metadata, normalize_principal_ids
from ragrig.db.models import (
    Chunk,
    Document,
    DocumentUnderstanding,
    DocumentVersion,
    KnowledgeBase,
    KnowledgeGraphClaim,
    KnowledgeGraphEntity,
    KnowledgeGraphEntityMention,
    KnowledgeGraphRelation,
    KnowledgeGraphRelationEvidence,
)
from ragrig.lexical import token_overlap_score
from ragrig.understanding.provider import compute_input_hash
from ragrig.understanding.schema import UnderstandingResult

from .schema import (
    GraphRetrievalContext,
    KnowledgeGraphClaimRecord,
    KnowledgeGraphEntityRecord,
    KnowledgeGraphMentionRecord,
    KnowledgeGraphRelationEvidenceRecord,
    KnowledgeGraphRelationRecord,
    KnowledgeGraphResult,
    KnowledgeGraphStats,
)

DEFAULT_KG_EXTRACTOR_VERSION = "kg-lite-v1"
_ENTITY_RE = re.compile(r"\b[A-Z][A-Za-z0-9_/-]{2,}(?:[ \t]+[A-Z][A-Za-z0-9_/-]{2,}){0,3}\b")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_ENTITY_STOPWORDS = {
    "a",
    "an",
    "and",
    "does",
    "for",
    "how",
    "should",
    "that",
    "the",
    "then",
    "this",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
}
_RELATION_PREDICATE_WEIGHTS = {
    "co_mentions": 1.0,
    "depends_on": 1.0,
    "references": 0.96,
    "routes_to": 0.95,
    "assigns": 0.9,
}


@dataclass(frozen=True)
class _ChunkRow:
    chunk: Chunk
    version: DocumentVersion
    document: Document


@dataclass(frozen=True)
class _EntityCandidate:
    display_name: str
    entity_type: str = "TERM"
    description: str | None = None
    confidence: float = 0.6
    source: str = "deterministic"


class KnowledgeGraphNotFoundError(ValueError):
    pass


def _canonical_name(value: str) -> str:
    spaced = _CAMEL_RE.sub(" ", value.strip())
    normalized = re.sub(r"[_/-]+", " ", spaced.casefold())
    normalized = re.sub(r"[^a-z0-9 ]+", " ", normalized)
    return " ".join(normalized.split())


def _compact_alias(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _entity_aliases(display_name: str) -> list[str]:
    canonical = _canonical_name(display_name)
    aliases = {
        canonical,
        " ".join(display_name.strip().casefold().split()),
        _compact_alias(display_name),
    }
    parts = [part for part in canonical.split() if part]
    if len(parts) >= 2:
        acronym = "".join(part[0] for part in parts)
        if len(acronym) >= 3:
            aliases.add(acronym)
        aliases.add("".join(parts))
    return sorted(alias for alias in aliases if alias)


def _merge_aliases(existing: list[str] | None, new_aliases: list[str]) -> list[str]:
    merged = {alias for alias in (existing or []) if isinstance(alias, str) and alias}
    merged.update(new_aliases)
    return sorted(merged)


def _preview(text: str, limit: int = 220) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 3] + "..."


def _confidence_from_label(value: str) -> float:
    mapping = {"high": 0.9, "medium": 0.7, "low": 0.45}
    return mapping.get(value.strip().casefold(), 0.6)


def _latest_chunk_rows(session: Session, knowledge_base_id: uuid.UUID) -> list[_ChunkRow]:
    latest_version_numbers = (
        select(
            DocumentVersion.document_id.label("document_id"),
            func.max(DocumentVersion.version_number).label("version_number"),
        )
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(Document.knowledge_base_id == knowledge_base_id)
        .group_by(DocumentVersion.document_id)
        .subquery()
    )
    stmt = (
        select(Chunk, DocumentVersion, Document)
        .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .join(
            latest_version_numbers,
            (DocumentVersion.document_id == latest_version_numbers.c.document_id)
            & (DocumentVersion.version_number == latest_version_numbers.c.version_number),
        )
        .where(Document.knowledge_base_id == knowledge_base_id)
        .order_by(Document.uri, Chunk.chunk_index)
    )
    return [
        _ChunkRow(chunk=chunk, version=version, document=document)
        for chunk, version, document in session.execute(stmt)
    ]


def _fresh_understanding(
    session: Session,
    version: DocumentVersion,
    *,
    profile_id: str,
) -> UnderstandingResult | None:
    row = (
        session.query(DocumentUnderstanding)
        .filter(
            DocumentUnderstanding.document_version_id == version.id,
            DocumentUnderstanding.profile_id == profile_id,
            DocumentUnderstanding.status == "completed",
        )
        .first()
    )
    if row is None:
        return None
    current_hash = compute_input_hash(
        version.extracted_text,
        row.profile_id,
        row.provider,
        row.model,
    )
    if row.input_hash != current_hash:
        return None
    return UnderstandingResult.from_raw(dict(row.result_json or {}))


def _fallback_entities(text: str, *, limit: int = 12) -> list[_EntityCandidate]:
    seen: set[str] = set()
    candidates: list[_EntityCandidate] = []
    for match in _ENTITY_RE.finditer(text):
        display = " ".join(match.group(0).split())
        canonical = _canonical_name(display)
        if not canonical or canonical in seen:
            continue
        if canonical in _ENTITY_STOPWORDS:
            continue
        seen.add(canonical)
        candidates.append(_EntityCandidate(display_name=display, confidence=0.55))
        if len(candidates) >= limit:
            break
    return candidates


def _entity_candidates_for_version(
    result: UnderstandingResult | None,
    version_text: str,
) -> list[_EntityCandidate]:
    if result is None or not result.entities:
        return _fallback_entities(version_text)
    candidates: list[_EntityCandidate] = []
    seen: set[str] = set()
    for entity in result.entities:
        display = entity.name.strip()
        canonical = _canonical_name(display)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        candidates.append(
            _EntityCandidate(
                display_name=display,
                entity_type=entity.type or "TERM",
                description=entity.description,
                confidence=0.8,
                source="understanding",
            )
        )
    return candidates


def _find_mentions(text: str, display_name: str) -> Iterable[tuple[int, int, str]]:
    escaped = re.escape(display_name.strip())
    if not escaped:
        return []
    pattern = re.compile(rf"\b{escaped}\b", flags=re.IGNORECASE)
    return ((m.start(), m.end(), m.group(0)) for m in pattern.finditer(text))


def _first_claim_sentence(text: str) -> str | None:
    for raw in _SENTENCE_RE.split(text.strip()):
        sentence = raw.strip()
        if len(sentence.split()) >= 5:
            return sentence[:500]
    stripped = text.strip()
    if len(stripped.split()) >= 5:
        return stripped[:500]
    return None


def _chunk_for_claim(
    rows: list[_ChunkRow],
    version_id: uuid.UUID,
    evidence_snippet: str | None,
) -> _ChunkRow | None:
    version_rows = [row for row in rows if row.version.id == version_id]
    if not version_rows:
        return None
    if evidence_snippet:
        needle = evidence_snippet.strip().casefold()
        for row in version_rows:
            if needle and needle in row.chunk.text.casefold():
                return row
    return version_rows[0]


def rebuild_knowledge_graph(
    session: Session,
    knowledge_base_id: str,
    *,
    profile_id: str = "*.understand.default",
    extractor_version: str = DEFAULT_KG_EXTRACTOR_VERSION,
    reset: bool = True,
) -> KnowledgeGraphResult:
    kb_uuid = uuid.UUID(knowledge_base_id)
    kb = session.get(KnowledgeBase, kb_uuid)
    if kb is None:
        raise KnowledgeGraphNotFoundError(f"Knowledge base '{knowledge_base_id}' was not found")

    if reset:
        _delete_graph_rows(session, kb_uuid)

    rows = _latest_chunk_rows(session, kb_uuid)
    if not rows:
        session.commit()
        return get_knowledge_graph(session, knowledge_base_id)

    rows_by_version: dict[uuid.UUID, list[_ChunkRow]] = defaultdict(list)
    for row in rows:
        rows_by_version[row.version.id].append(row)

    entity_by_key: dict[str, KnowledgeGraphEntity] = {}
    mentions_by_chunk: dict[uuid.UUID, list[KnowledgeGraphEntityMention]] = defaultdict(list)
    understanding_by_version: dict[uuid.UUID, UnderstandingResult | None] = {}

    for version_id, version_rows in rows_by_version.items():
        version = version_rows[0].version
        understanding = _fresh_understanding(session, version, profile_id=profile_id)
        understanding_by_version[version_id] = understanding
        candidates = _entity_candidates_for_version(understanding, version.extracted_text)

        for candidate in candidates:
            canonical = _canonical_name(candidate.display_name)
            if not canonical:
                continue
            aliases = _entity_aliases(candidate.display_name)
            entity = next(
                (entity_by_key[alias] for alias in aliases if alias in entity_by_key), None
            )
            if entity is None:
                entity = KnowledgeGraphEntity(
                    knowledge_base_id=kb.id,
                    workspace_id=kb.workspace_id,
                    canonical_name=canonical,
                    display_name=candidate.display_name,
                    entity_type=candidate.entity_type,
                    description=candidate.description,
                    confidence=candidate.confidence,
                    extractor_version=extractor_version,
                    metadata_json={
                        "sources": [candidate.source],
                        "profile_id": profile_id,
                        "aliases": aliases,
                    },
                )
                session.add(entity)
                session.flush()
            else:
                entity.confidence = max(entity.confidence, candidate.confidence)
                metadata = dict(entity.metadata_json or {})
                sources = set(metadata.get("sources", []))
                sources.add(candidate.source)
                entity.metadata_json = {
                    **metadata,
                    "sources": sorted(sources),
                    "aliases": _merge_aliases(metadata.get("aliases"), aliases),
                }
            for alias in aliases:
                entity_by_key[alias] = entity

            for row in version_rows:
                for start, end, mention_text in _find_mentions(
                    row.chunk.text, candidate.display_name
                ):
                    absolute_start = (
                        row.chunk.char_start + start if row.chunk.char_start is not None else start
                    )
                    absolute_end = (
                        row.chunk.char_start + end if row.chunk.char_start is not None else end
                    )
                    mention = KnowledgeGraphEntityMention(
                        entity_id=entity.id,
                        chunk_id=row.chunk.id,
                        document_id=row.document.id,
                        document_version_id=row.version.id,
                        mention_text=mention_text,
                        char_start=absolute_start,
                        char_end=absolute_end,
                        confidence=candidate.confidence,
                        extractor_version=extractor_version,
                        metadata_json={"source": candidate.source},
                    )
                    session.add(mention)
                    mentions_by_chunk[row.chunk.id].append(mention)

    session.flush()
    _create_claims(
        session,
        kb,
        rows,
        understanding_by_version,
        extractor_version=extractor_version,
    )
    _create_relations(
        session,
        kb,
        rows,
        mentions_by_chunk,
        extractor_version=extractor_version,
    )
    session.commit()
    return get_knowledge_graph(session, knowledge_base_id)


def _delete_graph_rows(session: Session, knowledge_base_id: uuid.UUID) -> None:
    relation_ids = select(KnowledgeGraphRelation.id).where(
        KnowledgeGraphRelation.knowledge_base_id == knowledge_base_id
    )
    entity_ids = select(KnowledgeGraphEntity.id).where(
        KnowledgeGraphEntity.knowledge_base_id == knowledge_base_id
    )
    session.execute(
        delete(KnowledgeGraphRelationEvidence).where(
            KnowledgeGraphRelationEvidence.relation_id.in_(relation_ids)
        )
    )
    session.execute(
        delete(KnowledgeGraphRelation).where(
            KnowledgeGraphRelation.knowledge_base_id == knowledge_base_id
        )
    )
    session.execute(
        delete(KnowledgeGraphEntityMention).where(
            KnowledgeGraphEntityMention.entity_id.in_(entity_ids)
        )
    )
    session.execute(
        delete(KnowledgeGraphClaim).where(
            KnowledgeGraphClaim.knowledge_base_id == knowledge_base_id
        )
    )
    session.execute(
        delete(KnowledgeGraphEntity).where(
            KnowledgeGraphEntity.knowledge_base_id == knowledge_base_id
        )
    )
    session.flush()


def _create_claims(
    session: Session,
    kb: KnowledgeBase,
    rows: list[_ChunkRow],
    understanding_by_version: dict[uuid.UUID, UnderstandingResult | None],
    *,
    extractor_version: str,
) -> None:
    rows_by_version: dict[uuid.UUID, list[_ChunkRow]] = defaultdict(list)
    for row in rows:
        rows_by_version[row.version.id].append(row)

    for version_id, version_rows in rows_by_version.items():
        understanding = understanding_by_version.get(version_id)
        created = 0
        if understanding is not None:
            for claim in understanding.key_claims[:8]:
                claim_text = claim.claim.strip()
                if not claim_text:
                    continue
                row = _chunk_for_claim(rows, version_id, claim.evidence_snippet)
                if row is None:
                    continue
                session.add(
                    KnowledgeGraphClaim(
                        knowledge_base_id=kb.id,
                        workspace_id=kb.workspace_id,
                        source_chunk_id=row.chunk.id,
                        document_id=row.document.id,
                        document_version_id=row.version.id,
                        claim_text=claim_text,
                        confidence=_confidence_from_label(claim.confidence),
                        extractor_version=extractor_version,
                        metadata_json={
                            "source": "understanding",
                            "evidence_snippet": claim.evidence_snippet,
                        },
                    )
                )
                created += 1
        if created:
            continue
        for row in version_rows[:2]:
            sentence = _first_claim_sentence(row.chunk.text)
            if sentence is None:
                continue
            session.add(
                KnowledgeGraphClaim(
                    knowledge_base_id=kb.id,
                    workspace_id=kb.workspace_id,
                    source_chunk_id=row.chunk.id,
                    document_id=row.document.id,
                    document_version_id=row.version.id,
                    claim_text=sentence,
                    confidence=0.55,
                    extractor_version=extractor_version,
                    metadata_json={"source": "deterministic_sentence"},
                )
            )


def _create_relations(
    session: Session,
    kb: KnowledgeBase,
    rows: list[_ChunkRow],
    mentions_by_chunk: dict[uuid.UUID, list[KnowledgeGraphEntityMention]],
    *,
    extractor_version: str,
) -> None:
    relation_by_triplet: dict[tuple[uuid.UUID, str, uuid.UUID], KnowledgeGraphRelation] = {}
    row_by_chunk_id = {row.chunk.id: row for row in rows}
    for chunk_id, mentions in mentions_by_chunk.items():
        unique_mentions: dict[uuid.UUID, KnowledgeGraphEntityMention] = {}
        for mention in mentions:
            unique_mentions.setdefault(mention.entity_id, mention)
        if len(unique_mentions) < 2:
            continue
        for left, right in combinations(
            sorted(unique_mentions.values(), key=lambda m: str(m.entity_id)), 2
        ):
            subject_id, object_id = sorted([left.entity_id, right.entity_id], key=str)
            triplet = (subject_id, "co_mentions", object_id)
            relation = relation_by_triplet.get(triplet)
            if relation is None:
                relation = KnowledgeGraphRelation(
                    knowledge_base_id=kb.id,
                    workspace_id=kb.workspace_id,
                    subject_entity_id=subject_id,
                    predicate="co_mentions",
                    object_entity_id=object_id,
                    confidence=0.65,
                    extractor_version=extractor_version,
                    metadata_json={"source": "chunk_co_mention"},
                )
                session.add(relation)
                session.flush()
                relation_by_triplet[triplet] = relation
            row = row_by_chunk_id[chunk_id]
            session.add(
                KnowledgeGraphRelationEvidence(
                    relation_id=relation.id,
                    chunk_id=chunk_id,
                    document_id=row.document.id,
                    document_version_id=row.version.id,
                    evidence_text=_preview(row.chunk.text, 500),
                    confidence=0.65,
                    extractor_version=extractor_version,
                    metadata_json={"source": "chunk_co_mention"},
                )
            )


def get_knowledge_graph(session: Session, knowledge_base_id: str) -> KnowledgeGraphResult:
    kb_uuid = uuid.UUID(knowledge_base_id)
    kb = session.get(KnowledgeBase, kb_uuid)
    if kb is None:
        raise KnowledgeGraphNotFoundError(f"Knowledge base '{knowledge_base_id}' was not found")

    chunk_rows = _latest_chunk_rows(session, kb_uuid)
    chunk_by_id = {row.chunk.id: row for row in chunk_rows}
    entities = list(
        session.scalars(
            select(KnowledgeGraphEntity)
            .where(KnowledgeGraphEntity.knowledge_base_id == kb_uuid)
            .order_by(KnowledgeGraphEntity.display_name)
        )
    )
    relations = list(
        session.scalars(
            select(KnowledgeGraphRelation)
            .where(KnowledgeGraphRelation.knowledge_base_id == kb_uuid)
            .order_by(KnowledgeGraphRelation.predicate, KnowledgeGraphRelation.id)
        )
    )
    claims = list(
        session.scalars(
            select(KnowledgeGraphClaim)
            .where(KnowledgeGraphClaim.knowledge_base_id == kb_uuid)
            .order_by(KnowledgeGraphClaim.created_at, KnowledgeGraphClaim.id)
        )
    )
    mention_rows = list(
        session.scalars(
            select(KnowledgeGraphEntityMention)
            .join(
                KnowledgeGraphEntity,
                KnowledgeGraphEntity.id == KnowledgeGraphEntityMention.entity_id,
            )
            .where(KnowledgeGraphEntity.knowledge_base_id == kb_uuid)
            .order_by(KnowledgeGraphEntityMention.created_at)
        )
    )
    evidence_rows = list(
        session.scalars(
            select(KnowledgeGraphRelationEvidence)
            .join(
                KnowledgeGraphRelation,
                KnowledgeGraphRelation.id == KnowledgeGraphRelationEvidence.relation_id,
            )
            .where(KnowledgeGraphRelation.knowledge_base_id == kb_uuid)
            .order_by(KnowledgeGraphRelationEvidence.created_at)
        )
    )
    mentions_by_entity: dict[uuid.UUID, list[KnowledgeGraphEntityMention]] = defaultdict(list)
    for mention in mention_rows:
        mentions_by_entity[mention.entity_id].append(mention)
    evidence_by_relation: dict[uuid.UUID, list[KnowledgeGraphRelationEvidence]] = defaultdict(list)
    for evidence in evidence_rows:
        evidence_by_relation[evidence.relation_id].append(evidence)

    entity_records = [
        _serialize_entity(entity, mentions_by_entity.get(entity.id, []), chunk_by_id)
        for entity in entities
    ]
    relation_records = [
        _serialize_relation(relation, evidence_by_relation.get(relation.id, []), chunk_by_id)
        for relation in relations
    ]
    claim_records = [_serialize_claim(claim, chunk_by_id) for claim in claims]
    stats = KnowledgeGraphStats(
        entity_count=len(entities),
        mention_count=len(mention_rows),
        relation_count=len(relations),
        relation_evidence_count=len(evidence_rows),
        claim_count=len(claims),
        source_chunk_count=len(chunk_rows),
        document_count=len({row.document.id for row in chunk_rows}),
        graph_evidence_chunk_count=len(
            {m.chunk_id for m in mention_rows}
            | {e.chunk_id for e in evidence_rows}
            | {c.source_chunk_id for c in claims}
        ),
    )
    limitations: list[str] = []
    if not chunk_rows:
        limitations.append("Knowledge base has no latest chunks to extract graph evidence from.")
    if chunk_rows and not entities:
        limitations.append("No KG-lite entities have been extracted yet.")
    if entities and not relations:
        limitations.append("No entity pair shares chunk-level evidence yet.")
    status = "empty_kb" if not chunk_rows else "ready" if entities else "no_graph"
    return KnowledgeGraphResult(
        status=status,
        knowledge_base_id=str(kb.id),
        knowledge_base=kb.name,
        stats=stats,
        entities=entity_records,
        relations=relation_records,
        claims=claim_records,
        limitations=limitations,
    )


def _serialize_entity(
    entity: KnowledgeGraphEntity,
    mentions: list[KnowledgeGraphEntityMention],
    chunk_by_id: dict[uuid.UUID, _ChunkRow],
) -> KnowledgeGraphEntityRecord:
    mention_records = []
    for mention in mentions[:8]:
        row = chunk_by_id.get(mention.chunk_id)
        mention_records.append(
            KnowledgeGraphMentionRecord(
                id=str(mention.id),
                chunk_id=str(mention.chunk_id),
                document_id=str(mention.document_id),
                document_version_id=str(mention.document_version_id),
                mention_text=mention.mention_text,
                char_start=mention.char_start,
                char_end=mention.char_end,
                confidence=mention.confidence,
                text_preview=_preview(row.chunk.text if row is not None else ""),
                document_uri=row.document.uri if row is not None else "",
            )
        )
    return KnowledgeGraphEntityRecord(
        id=str(entity.id),
        canonical_name=entity.canonical_name,
        display_name=entity.display_name,
        entity_type=entity.entity_type,
        description=entity.description,
        confidence=entity.confidence,
        extractor_version=entity.extractor_version,
        mention_count=len(mentions),
        evidence_chunks=mention_records,
        metadata=dict(entity.metadata_json or {}),
    )


def _serialize_relation(
    relation: KnowledgeGraphRelation,
    evidence_rows: list[KnowledgeGraphRelationEvidence],
    chunk_by_id: dict[uuid.UUID, _ChunkRow],
) -> KnowledgeGraphRelationRecord:
    evidence = []
    for row_evidence in evidence_rows[:8]:
        row = chunk_by_id.get(row_evidence.chunk_id)
        evidence.append(
            KnowledgeGraphRelationEvidenceRecord(
                id=str(row_evidence.id),
                chunk_id=str(row_evidence.chunk_id),
                document_id=str(row_evidence.document_id),
                document_version_id=str(row_evidence.document_version_id),
                evidence_text=row_evidence.evidence_text,
                text_preview=_preview(
                    row.chunk.text if row is not None else row_evidence.evidence_text
                ),
                document_uri=row.document.uri if row is not None else "",
                confidence=row_evidence.confidence,
            )
        )
    return KnowledgeGraphRelationRecord(
        id=str(relation.id),
        subject_entity_id=str(relation.subject_entity_id),
        subject=relation.subject_entity.display_name,
        predicate=relation.predicate,
        object_entity_id=str(relation.object_entity_id),
        object=relation.object_entity.display_name,
        confidence=relation.confidence,
        extractor_version=relation.extractor_version,
        evidence=evidence,
        metadata=dict(relation.metadata_json or {}),
    )


def _serialize_claim(
    claim: KnowledgeGraphClaim,
    chunk_by_id: dict[uuid.UUID, _ChunkRow],
) -> KnowledgeGraphClaimRecord:
    row = chunk_by_id.get(claim.source_chunk_id)
    return KnowledgeGraphClaimRecord(
        id=str(claim.id),
        claim_text=claim.claim_text,
        confidence=claim.confidence,
        source_chunk_id=str(claim.source_chunk_id),
        document_id=str(claim.document_id),
        document_version_id=str(claim.document_version_id),
        document_uri=row.document.uri if row is not None else "",
        text_preview=_preview(row.chunk.text if row is not None else claim.claim_text),
        extractor_version=claim.extractor_version,
        metadata=dict(claim.metadata_json or {}),
    )


def build_graph_retrieval_context(
    session: Session,
    *,
    knowledge_base_id: uuid.UUID,
    query: str,
    limit: int = 20,
    graph_depth: int = 1,
    principal_ids: list[str] | None = None,
    enforce_acl: bool = True,
) -> GraphRetrievalContext:
    visible_chunk_ids: set[uuid.UUID] | None = None
    visible_entity_ids: set[uuid.UUID] | None = None
    if enforce_acl:
        latest_rows = _latest_chunk_rows(session, knowledge_base_id)
        normalized_principals = normalize_principal_ids(principal_ids)
        effective_principals = normalized_principals if normalized_principals else None
        visible_chunk_ids = {
            row.chunk.id
            for row in latest_rows
            if acl_permits_chunk_metadata(row.chunk.metadata_json, effective_principals)
        }
        if not visible_chunk_ids:
            return GraphRetrievalContext()

    entities = list(
        session.scalars(
            select(KnowledgeGraphEntity)
            .where(KnowledgeGraphEntity.knowledge_base_id == knowledge_base_id)
            .order_by(KnowledgeGraphEntity.display_name)
        )
    )
    if not entities:
        return GraphRetrievalContext(
            degraded=True,
            degraded_reason="knowledge graph has no extracted entities",
        )

    if visible_chunk_ids is not None:
        visible_mentions = list(
            session.scalars(
                select(KnowledgeGraphEntityMention)
                .join(
                    KnowledgeGraphEntity,
                    KnowledgeGraphEntity.id == KnowledgeGraphEntityMention.entity_id,
                )
                .where(KnowledgeGraphEntity.knowledge_base_id == knowledge_base_id)
            )
        )
        visible_entity_ids = {
            mention.entity_id
            for mention in visible_mentions
            if mention.chunk_id in visible_chunk_ids
        }
        if not visible_entity_ids:
            return GraphRetrievalContext()

    query_lc = query.casefold()
    query_terms = set(re.findall(r"[a-z0-9_/-]{3,}", query_lc))
    query_compact = _compact_alias(query)
    matched: list[tuple[KnowledgeGraphEntity, float]] = []
    corpus = [
        alias
        for entity in entities
        for alias in _merge_aliases(
            (entity.metadata_json or {}).get("aliases"),
            _entity_aliases(entity.display_name),
        )
    ]
    for entity in entities:
        if visible_entity_ids is not None and entity.id not in visible_entity_ids:
            continue
        canonical = entity.canonical_name
        aliases = _merge_aliases(
            (entity.metadata_json or {}).get("aliases"),
            _entity_aliases(entity.display_name),
        )
        entity_terms = set(re.findall(r"[a-z0-9_/-]{3,}", canonical))
        if any(alias and (alias in query_lc or alias in query_compact) for alias in aliases):
            matched.append((entity, 1.0))
            continue
        overlap = len(query_terms & entity_terms)
        if overlap:
            matched.append((entity, min(0.95, 0.55 + overlap * 0.15)))
            continue
        lexical = max((token_overlap_score(alias, query, corpus) for alias in aliases), default=0.0)
        if lexical >= 0.45:
            matched.append((entity, min(0.8, lexical)))

    matched.sort(key=lambda item: (-item[1], item[0].display_name))
    matched = matched[:8]
    if not matched:
        return GraphRetrievalContext()

    matched_ids = {entity.id for entity, _score in matched}
    matched_score_by_id = {entity.id: score for entity, score in matched}
    expanded_ids: set[uuid.UUID] = set(matched_ids)
    relation_paths: list[dict[str, Any]] = []
    chunk_scores: dict[str, float] = {}
    suppressed_relations: list[dict[str, Any]] = []

    relation_rows = list(
        session.scalars(
            select(KnowledgeGraphRelation).where(
                KnowledgeGraphRelation.knowledge_base_id == knowledge_base_id,
            )
        )
    )
    if graph_depth > 0:
        for relation in relation_rows:
            touches = (
                relation.subject_entity_id in matched_ids
                or relation.object_entity_id in matched_ids
            )
            if not touches:
                continue
            evidence_rows = list(
                session.scalars(
                    select(KnowledgeGraphRelationEvidence)
                    .where(KnowledgeGraphRelationEvidence.relation_id == relation.id)
                    .limit(4)
                )
            )
            if visible_chunk_ids is not None:
                evidence_rows = [
                    evidence for evidence in evidence_rows if evidence.chunk_id in visible_chunk_ids
                ]
                if not evidence_rows:
                    continue
            expanded_ids.add(relation.subject_entity_id)
            expanded_ids.add(relation.object_entity_id)
            matched_endpoint_count = int(relation.subject_entity_id in matched_ids) + int(
                relation.object_entity_id in matched_ids
            )
            path_score = max(
                matched_score_by_id.get(relation.subject_entity_id, 0.0),
                matched_score_by_id.get(relation.object_entity_id, 0.0),
            )
            predicate_weight = _relation_predicate_weight(relation.predicate)
            feedback_summary = _relation_feedback_summary(relation.metadata_json)
            feedback_weight, feedback_reason = _relation_feedback_weight(feedback_summary)
            if feedback_weight <= 0.0:
                suppressed_relations.append(
                    {
                        "relation_id": str(relation.id),
                        "subject": relation.subject_entity.display_name,
                        "predicate": relation.predicate,
                        "object": relation.object_entity.display_name,
                        "reason": feedback_reason,
                        "feedback_summary": feedback_summary,
                    }
                )
                continue
            evidence_score = _relation_evidence_score(
                relation_confidence=relation.confidence,
                path_score=path_score,
                matched_endpoint_count=matched_endpoint_count,
                predicate_weight=predicate_weight,
                feedback_weight=feedback_weight,
            )
            if evidence_score <= 0.0:
                continue
            relation_paths.append(
                {
                    "relation_id": str(relation.id),
                    "subject_entity_id": str(relation.subject_entity_id),
                    "subject": relation.subject_entity.display_name,
                    "predicate": relation.predicate,
                    "object_entity_id": str(relation.object_entity_id),
                    "object": relation.object_entity.display_name,
                    "confidence": relation.confidence,
                    "matched_endpoint_count": matched_endpoint_count,
                    "path_score": round(path_score, 6),
                    "evidence_score": evidence_score,
                    "predicate_weight": round(predicate_weight, 6),
                    "feedback_weight": round(feedback_weight, 6),
                    "feedback_reason": feedback_reason,
                    "feedback_summary": feedback_summary,
                    "evidence_chunk_ids": [str(e.chunk_id) for e in evidence_rows],
                }
            )
            for evidence in evidence_rows:
                _boost_chunk_score(
                    chunk_scores,
                    evidence.chunk_id,
                    evidence_score,
                )

    mention_rows = list(
        session.scalars(
            select(KnowledgeGraphEntityMention).where(
                KnowledgeGraphEntityMention.entity_id.in_(expanded_ids)
            )
        )
    )
    if visible_chunk_ids is not None:
        mention_rows = [
            mention for mention in mention_rows if mention.chunk_id in visible_chunk_ids
        ]
    for mention in mention_rows:
        if mention.entity_id in matched_ids:
            base = 0.82 + (0.16 * matched_score_by_id.get(mention.entity_id, 0.0))
        else:
            base = 0.68
        _boost_chunk_score(chunk_scores, mention.chunk_id, base * mention.confidence)

    relation_paths.sort(
        key=lambda item: (
            -float(item.get("evidence_score") or 0.0),
            str(item.get("subject") or ""),
            str(item.get("object") or ""),
        )
    )
    ranked_chunk_scores = dict(sorted(chunk_scores.items(), key=lambda item: -item[1])[:limit])
    entity_by_id = {entity.id: entity for entity in entities}
    return GraphRetrievalContext(
        matched_entities=[
            {
                "entity_id": str(entity.id),
                "display_name": entity.display_name,
                "entity_type": entity.entity_type,
                "score": round(score, 6),
            }
            for entity, score in matched
        ],
        expanded_entities=[
            {
                "entity_id": str(entity_id),
                "display_name": entity_by_id[entity_id].display_name,
                "entity_type": entity_by_id[entity_id].entity_type,
            }
            for entity_id in sorted(
                expanded_ids, key=lambda value: entity_by_id[value].display_name
            )
            if entity_id in entity_by_id
        ],
        relation_paths=relation_paths[:limit],
        chunk_scores=ranked_chunk_scores,
        diagnostics={
            "alias_matching": True,
            "relation_feedback_aware": True,
            "suppressed_relation_count": len(suppressed_relations),
            "suppressed_relations": suppressed_relations[:8],
        },
    )


def _boost_chunk_score(scores: dict[str, float], chunk_id: uuid.UUID, score: float) -> None:
    key = str(chunk_id)
    scores[key] = round(max(scores.get(key, 0.0), min(score, 1.0)), 6)


def _relation_feedback_summary(metadata: dict[str, Any] | None) -> dict[str, int]:
    raw = (metadata or {}).get("feedback_summary")
    if not isinstance(raw, dict):
        return {"incorrect": 0, "correct": 0, "needs_review": 0, "total": 0}
    incorrect = int(raw.get("incorrect") or 0)
    correct = int(raw.get("correct") or 0)
    needs_review = int(raw.get("needs_review") or 0)
    return {
        "incorrect": max(incorrect, 0),
        "correct": max(correct, 0),
        "needs_review": max(needs_review, 0),
        "total": max(int(raw.get("total") or incorrect + correct + needs_review), 0),
    }


def _relation_feedback_weight(summary: dict[str, int]) -> tuple[float, str]:
    incorrect = summary.get("incorrect", 0)
    correct = summary.get("correct", 0)
    needs_review = summary.get("needs_review", 0)
    if incorrect >= 1 and correct == 0:
        return 0.0, "relation marked incorrect"
    if incorrect > correct:
        return 0.35, "relation disputed by feedback"
    if needs_review and not correct:
        return 0.7, "relation needs review"
    if correct > incorrect:
        return min(1.12, 1.0 + (correct * 0.04)), "relation confirmed"
    return 1.0, "no feedback"


def _relation_predicate_weight(predicate: str) -> float:
    return _RELATION_PREDICATE_WEIGHTS.get(predicate, 0.55)


def _relation_evidence_score(
    *,
    relation_confidence: float,
    path_score: float,
    matched_endpoint_count: int,
    predicate_weight: float = 1.0,
    feedback_weight: float = 1.0,
) -> float:
    score = (0.72 + (0.18 * path_score)) * relation_confidence
    if matched_endpoint_count >= 2:
        score += 0.25
    elif matched_endpoint_count == 1:
        score += 0.08
    score *= predicate_weight * feedback_weight
    return round(max(0.0, min(score, 1.0)), 6)
