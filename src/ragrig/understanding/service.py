from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.db.models import (
    Document,
    DocumentUnderstanding,
    DocumentVersion,
    Source,
    UnderstandingRun,
)
from ragrig.understanding.provider import (
    compute_input_hash,
    get_understanding_provider,
)
from ragrig.understanding.schema import (
    BatchUnderstandingError,
    BatchUnderstandingResult,
    CoverageErrorEntry,
    UnderstandingCoverage,
    UnderstandingRecord,
    UnderstandingRunFilter,
    UnderstandingRunRecord,
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


def _run_status_from_result(total: int, failed: int) -> str:
    """Derive deterministic run status from batch counts."""
    if total == 0:
        return "empty_kb"
    if failed == 0:
        return "success"
    if failed == total:
        return "all_failure"
    return "partial_failure"


def _safe_error_summary(errors: list[BatchUnderstandingError]) -> str | None:
    """Build a safe error summary without leaking secrets, full prompts, or full text."""
    if not errors:
        return None
    parts: list[str] = []
    for e in errors:
        msg = str(e.error)
        # Truncate long messages
        if len(msg) > 200:
            msg = msg[:197] + "..."
        parts.append(f"[{e.version_id[:8]}]: {msg}")
    merged = "; ".join(parts)
    if len(merged) > 2000:
        merged = merged[:1997] + "..."
    return merged


def understand_all_versions(
    session: Session,
    *,
    knowledge_base_id: str,
    provider: str = "deterministic-local",
    model: str | None = None,
    profile_id: str = "*.understand.default",
    trigger_source: str = "api",
    operator: str | None = None,
) -> BatchUnderstandingResult:
    """Batch-understand all document versions in a knowledge base.

    - missing (no understanding record) → generate new
    - fresh (input_hash matches and status=completed) → skip
    - stale (input_hash mismatch) → regenerate
    - failed → regenerate

    Persists an UnderstandingRun record for audit trail.
    """
    kb_uuid = uuid.UUID(knowledge_base_id)
    effective_model = model or ""

    # Create the run record (started = now)
    run = UnderstandingRun(
        knowledge_base_id=kb_uuid,
        provider=provider,
        model=effective_model,
        profile_id=profile_id,
        trigger_source=trigger_source,
        operator=operator,
        status="processing",
        total=0,
        created=0,
        skipped=0,
        failed=0,
        started_at=datetime.now(timezone.utc),
    )
    session.add(run)
    session.flush()

    versions = _get_kb_document_versions(session, knowledge_base_id)
    total = len(versions)
    created = 0
    skipped = 0
    failed = 0
    errors: list[BatchUnderstandingError] = []

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

    # Finalise run record
    run.total = total
    run.created = created
    run.skipped = skipped
    run.failed = failed
    run.status = _run_status_from_result(total, failed)
    run.error_summary = _safe_error_summary(errors)
    run.finished_at = datetime.now(timezone.utc)
    session.flush()
    session.commit()

    result = BatchUnderstandingResult(
        total=total,
        created=created,
        skipped=skipped,
        failed=failed,
        errors=errors,
    )
    return result


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

    # Collect recent errors (up to 10 most recent failed understanding records)
    failed_rows = (
        session.query(DocumentUnderstanding)
        .filter(
            DocumentUnderstanding.document_version_id.in_([v.id for v in versions]),
            DocumentUnderstanding.status == "failed",
        )
        .order_by(DocumentUnderstanding.updated_at.desc())
        .limit(10)
        .all()
    )
    recent_errors = [
        CoverageErrorEntry(
            document_version_id=str(row.document_version_id),
            profile_id=row.profile_id,
            provider=row.provider,
            error=row.error or "unknown error",
        )
        for row in failed_rows
    ]

    return UnderstandingCoverage(
        total_versions=total_versions,
        completed=completed,
        missing=missing,
        stale=stale,
        failed=failed,
        completeness_score=round(completeness_score, 4),
        recent_errors=recent_errors,
    )


def _to_run_record(row: UnderstandingRun) -> UnderstandingRunRecord:
    return UnderstandingRunRecord(
        id=str(row.id),
        knowledge_base_id=str(row.knowledge_base_id),
        provider=row.provider,
        model=row.model,
        profile_id=row.profile_id,
        trigger_source=row.trigger_source,
        operator=row.operator,
        status=row.status,
        total=row.total,
        created=row.created,
        skipped=row.skipped,
        failed=row.failed,
        error_summary=row.error_summary,
        started_at=row.started_at.isoformat() if row.started_at else None,
        finished_at=row.finished_at.isoformat() if row.finished_at else None,
    )


def get_understanding_runs(
    session: Session,
    knowledge_base_id: str,
    *,
    filters: UnderstandingRunFilter | None = None,
) -> list[UnderstandingRunRecord]:
    """Return understanding runs for a knowledge base, most recent first."""
    kb_uuid = uuid.UUID(knowledge_base_id)
    query = session.query(UnderstandingRun).filter(UnderstandingRun.knowledge_base_id == kb_uuid)

    if filters is not None:
        if filters.provider is not None:
            query = query.filter(UnderstandingRun.provider == filters.provider)
        if filters.model is not None:
            query = query.filter(UnderstandingRun.model == filters.model)
        if filters.profile_id is not None:
            query = query.filter(UnderstandingRun.profile_id == filters.profile_id)
        if filters.status is not None:
            query = query.filter(UnderstandingRun.status == filters.status)
        if filters.started_after is not None:
            query = query.filter(UnderstandingRun.started_at >= filters.started_after)
        if filters.started_before is not None:
            query = query.filter(UnderstandingRun.started_at <= filters.started_before)

    rows = (
        query.order_by(UnderstandingRun.started_at.desc(), UnderstandingRun.id.desc())
        .limit(filters.limit if filters is not None else 50)
        .all()
    )
    return [_to_run_record(r) for r in rows]


def get_understanding_run(session: Session, run_id: str) -> UnderstandingRunRecord | None:
    """Return a single understanding run by ID."""
    run_uuid = uuid.UUID(run_id)
    row = session.get(UnderstandingRun, run_uuid)
    if row is None:
        return None
    return _to_run_record(row)


# ---------------------------------------------------------------------------
# Safe JSON export
# ---------------------------------------------------------------------------

_EXPORT_SENSITIVE_KEYS = frozenset(
    {
        "extracted_text",
        "prompt",
        "full_prompt",
        "system_prompt",
        "user_prompt",
        "messages",
        "raw_response",
    }
)

_EXPORT_SECRET_PATTERNS = (
    "api_key",
    "access_key",
    "secret",
    "session_token",
    "token",
    "password",
    "private_key",
    "credential",
)


def _sanitize_value(value: object) -> object:
    """Recursively remove sensitive keys and secret-like values."""
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for k, v in value.items():
            if k.lower() in _EXPORT_SENSITIVE_KEYS:
                result[k] = "[REDACTED]"
                continue
            if _looks_like_secret(k, v):
                result[k] = "[REDACTED]"
                continue
            result[k] = _sanitize_value(v)
        return result
    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]
    return value


def _looks_like_secret(key: str, value: object) -> bool:
    """Check if a key/value pair looks like a secret."""
    key_lower = key.lower()
    if any(pattern in key_lower for pattern in _EXPORT_SECRET_PATTERNS):
        if isinstance(value, (str, int, float)) and value:
            return True
    return False


def export_understanding_run(session: Session, run_id: str) -> dict[str, object] | None:
    """Export a single understanding run with safe JSON sanitisation.

    Strips secret-like values and redacts sensitive fields (extracted_text,
    full prompts, raw responses) from any nested metadata or config.
    """
    run_uuid = uuid.UUID(run_id)
    row = session.get(UnderstandingRun, run_uuid)
    if row is None:
        return None

    kb_name = None
    from ragrig.db.models import KnowledgeBase

    kb = session.get(KnowledgeBase, row.knowledge_base_id)
    if kb is not None:
        kb_name = kb.name

    generated = datetime.now(timezone.utc)
    exported: dict[str, object] = {
        "schema_version": "1.0",
        "generated_at": generated.isoformat(),
        "filter": {},
        "run_count": 1,
        "run_ids": [str(row.id)],
        "id": str(row.id),
        "knowledge_base_id": str(row.knowledge_base_id),
        "knowledge_base": kb_name,
        "provider": row.provider,
        "model": row.model,
        "profile_id": row.profile_id,
        "trigger_source": row.trigger_source,
        "operator": row.operator,
        "status": row.status,
        "total": row.total,
        "created": row.created,
        "skipped": row.skipped,
        "failed": row.failed,
        "error_summary": row.error_summary,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }
    return _sanitize_value(exported)  # type: ignore[return-value]


def export_understanding_runs(
    session: Session,
    knowledge_base_id: str,
    *,
    filters: UnderstandingRunFilter | None = None,
) -> dict[str, object]:
    """Export a filtered list of understanding runs with safe JSON sanitisation."""
    records = get_understanding_runs(session, knowledge_base_id, filters=filters)

    kb_name = None
    from ragrig.db.models import KnowledgeBase

    kb_uuid = uuid.UUID(knowledge_base_id)
    kb = session.get(KnowledgeBase, kb_uuid)
    if kb is not None:
        kb_name = kb.name

    items: list[dict[str, object]] = []
    for rec in records:
        item: dict[str, object] = {
            "id": rec.id,
            "knowledge_base_id": rec.knowledge_base_id,
            "provider": rec.provider,
            "model": rec.model,
            "profile_id": rec.profile_id,
            "trigger_source": rec.trigger_source,
            "operator": rec.operator,
            "status": rec.status,
            "total": rec.total,
            "created": rec.created,
            "skipped": rec.skipped,
            "failed": rec.failed,
            "error_summary": rec.error_summary,
            "started_at": rec.started_at,
            "finished_at": rec.finished_at,
        }
        items.append(_sanitize_value(item))  # type: ignore[arg-type]

    filter_info: dict[str, object] = {
        "provider": filters.provider if filters else None,
        "model": filters.model if filters else None,
        "profile_id": filters.profile_id if filters else None,
        "status": filters.status if filters else None,
        "started_after": filters.started_after if filters else None,
        "started_before": filters.started_before if filters else None,
        "limit": filters.limit if filters else None,
    }
    run_ids = [item["id"] for item in items]
    result: dict[str, object] = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filter": filter_info,
        "run_count": len(items),
        "run_ids": run_ids,
        "knowledge_base": kb_name,
        "knowledge_base_id": knowledge_base_id,
        "runs": items,
    }
    return _sanitize_value(result)  # type: ignore[return-value]


def compare_understanding_runs(
    session: Session, run_id_a: str, run_id_b: str
) -> dict[str, object] | None:
    """Compare two understanding runs (best-effort diff).

    Returns a structured diff showing differences in counts and status.
    """
    rec_a = get_understanding_run(session, run_id_a)
    rec_b = get_understanding_run(session, run_id_b)
    if rec_a is None or rec_b is None:
        return None

    changes: list[dict[str, object]] = []

    for field_name, label in [
        ("total", "Total versions"),
        ("created", "Created"),
        ("skipped", "Skipped"),
        ("failed", "Failed"),
        ("status", "Status"),
        ("provider", "Provider"),
        ("model", "Model"),
        ("profile_id", "Profile ID"),
        ("trigger_source", "Trigger source"),
    ]:
        val_a = getattr(rec_a, field_name, None)
        val_b = getattr(rec_b, field_name, None)
        change: dict[str, object] = {
            "field": field_name,
            "label": label,
            "run_a": val_a,
            "run_b": val_b,
            "changed": val_a != val_b,
        }
        if isinstance(val_a, (int, float)) and isinstance(val_b, (int, float)):
            change["delta"] = val_b - val_a  # type: ignore[operator]
        changes.append(change)

    return {
        "run_a": {
            "id": rec_a.id,
            "started_at": rec_a.started_at,
            "status": rec_a.status,
        },
        "run_b": {
            "id": rec_b.id,
            "started_at": rec_b.started_at,
            "status": rec_b.status,
        },
        "changes": changes,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }
