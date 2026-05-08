from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.db.models import (
    Document,
    DocumentUnderstanding,
    DocumentVersion,
    Source,
)
from ragrig.understanding.provider import (
    compute_input_hash,
    get_understanding_provider,
)
from ragrig.understanding.schema import (
    BatchUnderstandingError,
    BatchUnderstandingResult,
    UnderstandingCoverage,
    UnderstandingRecord,
)


class UnderstandingServiceError(RuntimeError):
    def __init__(self, message: str, *, code: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class DocumentVersionNotFoundError(UnderstandingServiceError):
    def __init__(self, document_version_id: str) -> None:
        super().__init__(
            f"Document version '{document_version_id}' not found",
            code="document_version_not_found",
            details={"document_version_id": document_version_id},
        )


class ProviderUnavailableError(UnderstandingServiceError):
    def __init__(self, provider: str, reason: str) -> None:
        super().__init__(
            f"Provider '{provider}' is unavailable: {reason}",
            code="provider_unavailable",
            details={"provider": provider, "reason": reason},
        )


def _to_record(row: DocumentUnderstanding) -> UnderstandingRecord:
    return UnderstandingRecord(
        id=str(row.id),
        document_version_id=str(row.document_version_id),
        profile_id=row.profile_id,
        provider=row.provider,
        model=row.model,
        input_hash=row.input_hash,
        status=row.status,
        result=dict(row.result_json),
        error=row.error,
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


def get_understanding_by_version(
    session: Session, document_version_id: str
) -> UnderstandingRecord | None:
    version_uuid = uuid.UUID(document_version_id)
    row = (
        session.query(DocumentUnderstanding)
        .filter(DocumentUnderstanding.document_version_id == version_uuid)
        .first()
    )
    if row is None:
        return None
    return _to_record(row)


def generate_document_understanding(
    session: Session,
    *,
    document_version_id: str,
    provider: str = "deterministic-local",
    model: str | None = None,
    profile_id: str = "*.understand.default",
) -> UnderstandingRecord:
    version_uuid = uuid.UUID(document_version_id)
    version = session.get(DocumentVersion, version_uuid)
    if version is None:
        raise DocumentVersionNotFoundError(document_version_id)

    text = version.extracted_text
    input_hash = compute_input_hash(text, profile_id, provider, model or "")

    # Idempotency: if hash matches existing record, return it
    existing = (
        session.query(DocumentUnderstanding)
        .filter(
            DocumentUnderstanding.document_version_id == version_uuid,
            DocumentUnderstanding.profile_id == profile_id,
        )
        .first()
    )
    if existing is not None and existing.input_hash == input_hash:
        return _to_record(existing)

    # If existing but hash changed (text updated), overwrite
    row = existing
    if row is None:
        row = DocumentUnderstanding(
            document_version_id=version_uuid,
            profile_id=profile_id,
            provider=provider,
            model=model or "",
            input_hash=input_hash,
            status="processing",
            result_json={},
        )
        session.add(row)
    else:
        row.status = "processing"
        row.error = None
        row.result_json = {}
        row.provider = provider
        row.model = model or ""
        row.input_hash = input_hash

    session.flush()

    try:
        prov = get_understanding_provider(provider, model=model)
        result = prov.generate(text)
    except Exception as exc:
        row.status = "failed"
        row.error = str(exc)
        session.flush()
        session.commit()
        raise ProviderUnavailableError(provider, str(exc)) from exc

    row.status = "completed"
    row.result_json = result.model_dump(mode="json")
    row.error = None
    session.flush()
    session.commit()

    return _to_record(row)


def delete_document_understanding(session: Session, document_version_id: str) -> bool:
    version_uuid = uuid.UUID(document_version_id)
    row = (
        session.query(DocumentUnderstanding)
        .filter(DocumentUnderstanding.document_version_id == version_uuid)
        .first()
    )
    if row is None:
        return False
    session.delete(row)
    session.flush()
    session.commit()
    return True


def _get_kb_document_versions(session: Session, kb_id: str) -> list[DocumentVersion]:
    """Return all document versions for a knowledge base."""
    kb_uuid = uuid.UUID(kb_id)
    return list(
        session.scalars(
            select(DocumentVersion)
            .join(Document, Document.id == DocumentVersion.document_id)
            .join(Source, Source.id == Document.source_id)
            .where(Source.knowledge_base_id == kb_uuid)
            .order_by(DocumentVersion.created_at)
        )
    )


def understand_all_versions(
    session: Session,
    *,
    knowledge_base_id: str,
    provider: str = "deterministic-local",
    model: str | None = None,
    profile_id: str = "*.understand.default",
) -> BatchUnderstandingResult:
    """Batch-understand all document versions in a knowledge base.

    - missing (no understanding record) → generate new
    - fresh (input_hash matches and status=completed) → skip
    - stale (input_hash mismatch) → regenerate
    - failed → regenerate
    """
    versions = _get_kb_document_versions(session, knowledge_base_id)
    total = len(versions)
    created = 0
    skipped = 0
    failed = 0
    errors: list[BatchUnderstandingError] = []

    effective_model = model or ""

    for version in versions:
        version_id = str(version.id)
        text = version.extracted_text
        input_hash = compute_input_hash(text, profile_id, provider, effective_model)

        existing = (
            session.query(DocumentUnderstanding)
            .filter(
                DocumentUnderstanding.document_version_id == version.id,
                DocumentUnderstanding.profile_id == profile_id,
            )
            .first()
        )

        # Fresh: completed with matching hash → skip
        if (
            existing is not None
            and existing.status == "completed"
            and existing.input_hash == input_hash
        ):
            skipped += 1
            continue

        # Otherwise: missing, stale, or failed → (re)generate
        try:
            generate_document_understanding(
                session,
                document_version_id=version_id,
                provider=provider,
                model=model,
                profile_id=profile_id,
            )
            created += 1
        except (DocumentVersionNotFoundError, ProviderUnavailableError) as exc:
            failed += 1
            errors.append(BatchUnderstandingError(version_id=version_id, error=str(exc)))

    return BatchUnderstandingResult(
        total=total,
        created=created,
        skipped=skipped,
        failed=failed,
        errors=errors,
    )


def get_understanding_coverage(
    session: Session,
    knowledge_base_id: str,
) -> UnderstandingCoverage:
    """Compute understanding coverage for a knowledge base.

    staleness definition: a completed record exists but its input_hash
    does not match the current hash(profile_id + provider + model + extracted_text).
    """
    versions = _get_kb_document_versions(session, knowledge_base_id)
    total_versions = len(versions)
    completed = 0
    missing = 0
    stale = 0
    failed = 0

    for version in versions:
        understanding = (
            session.query(DocumentUnderstanding)
            .filter(DocumentUnderstanding.document_version_id == version.id)
            .first()
        )

        if understanding is None:
            missing += 1
            continue

        if understanding.status == "failed":
            failed += 1
            continue

        # Completed record exists — check staleness
        current_hash = compute_input_hash(
            version.extracted_text,
            understanding.profile_id,
            understanding.provider,
            understanding.model,
        )
        if understanding.input_hash != current_hash:
            stale += 1
        else:
            completed += 1

    completeness_score = completed / total_versions if total_versions > 0 else 0.0

    return UnderstandingCoverage(
        total_versions=total_versions,
        completed=completed,
        missing=missing,
        stale=stale,
        failed=failed,
        completeness_score=round(completeness_score, 4),
    )
