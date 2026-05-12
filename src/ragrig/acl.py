"""ACL metadata model and filtering logic.

Defines the canonical ACL contract for documents and chunks, and
provides helpers to evaluate access decisions across ingestion,
indexing, and retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Visibility = Literal["public", "protected", "unknown"]
AclSummaryVisibility = Literal["public", "protected", "unknown"]
AclExplainReason = Literal[
    "public",
    "allowed_principal",
    "denied_principal",
    "no_matching_principal",
    "no_principal",
    "unknown_visibility",
]


@dataclass(frozen=True)
class AclExplain:
    """Per-chunk ACL explanation safe for API responses.

    Must NOT contain raw principal lists, full chunk text, or secrets.
    """

    chunk_id: str
    visibility: Visibility
    permitted: bool
    reason: AclExplainReason


@dataclass(frozen=True)
class AclMetadata:
    """Canonical ACL metadata stored in document/chunk metadata_json."""

    visibility: Visibility = "public"
    allowed_principals: list[str] = field(default_factory=list)
    denied_principals: list[str] = field(default_factory=list)
    acl_source: str = "default"
    acl_source_hash: str = ""
    inheritance: str = "document"  # "document" | "propagated"
    ttl: str | None = None  # ISO-8601 datetime string for staleness detection

    _ACL_KEY = "acl"

    def permits(self, principal_ids: list[str] | None) -> bool:
        """Return True when *any* supplied principal is permitted on this resource."""
        if self.visibility == "public":
            return True
        if self.visibility == "unknown":
            return False
        if not principal_ids:
            return False
        # denied principals are excluded first
        allowed = {pid.lower() for pid in self.allowed_principals}
        denied = {pid.lower() for pid in self.denied_principals}
        request_principals = {pid.lower() for pid in principal_ids}
        if denied & request_principals:
            return False
        return bool(allowed & request_principals)

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any] | None) -> AclMetadata:
        """Extract AclMetadata from a metadata_json dict, with safe defaults."""
        if not metadata or cls._ACL_KEY not in metadata:
            return cls()
        raw = metadata[cls._ACL_KEY]
        if not isinstance(raw, dict):
            return cls()
        return cls(
            visibility=_coerce_visibility(raw.get("visibility")),
            allowed_principals=_coerce_str_list(raw.get("allowed_principals")),
            denied_principals=_coerce_str_list(raw.get("denied_principals")),
            acl_source=str(raw.get("acl_source", "default")),
            acl_source_hash=str(raw.get("acl_source_hash", "")),
            inheritance=str(raw.get("inheritance", "document")),
            ttl=raw.get("ttl") if isinstance(raw.get("ttl"), str) else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "visibility": self.visibility,
            "allowed_principals": self.allowed_principals,
            "denied_principals": self.denied_principals,
            "acl_source": self.acl_source,
            "acl_source_hash": self.acl_source_hash,
            "inheritance": self.inheritance,
            "ttl": self.ttl,
        }

    def summary(self) -> dict[str, Any]:
        """Return a summary safe for public-facing APIs (no full principal lists)."""
        is_stale = False
        stale_hint: str | None = None
        if self.ttl:
            try:
                expiry = datetime.fromisoformat(self.ttl)
                if datetime.now().astimezone() > expiry:
                    is_stale = True
                    stale_hint = "acl_ttl_expired"
            except ValueError:
                pass
        return {
            "visibility": self.visibility,
            "has_allowed_principals": len(self.allowed_principals) > 0,
            "has_denied_principals": len(self.denied_principals) > 0,
            "acl_source": self.acl_source,
            "inheritance": self.inheritance,
            "stale": is_stale,
            "stale_hint": stale_hint,
        }

    def for_propagation(self, document_id: str) -> AclMetadata:
        """Return a copy suitable for propagating from document to chunk."""
        return AclMetadata(
            visibility=self.visibility,
            allowed_principals=list(self.allowed_principals),
            denied_principals=list(self.denied_principals),
            acl_source=self.acl_source,
            acl_source_hash=self.acl_source_hash,
            inheritance="propagated",
            ttl=self.ttl,
        )


def _coerce_visibility(value: Any) -> Visibility:
    if value in ("public", "protected", "unknown"):
        return value
    return "unknown"


def _coerce_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, str)]
    return []


def acl_explain_reason(
    chunk_metadata: dict[str, Any] | None,
    principal_ids: list[str] | None,
) -> tuple[bool, AclExplainReason]:
    acl = AclMetadata.from_metadata(chunk_metadata)
    if acl.visibility == "public":
        return True, "public"
    if acl.visibility == "unknown":
        return False, "unknown_visibility"
    if not principal_ids:
        return False, "no_principal"
    allowed = {pid.lower() for pid in acl.allowed_principals}
    denied = {pid.lower() for pid in acl.denied_principals}
    request_principals = {pid.lower() for pid in principal_ids}
    if denied & request_principals:
        return False, "denied_principal"
    if allowed & request_principals:
        return True, "allowed_principal"
    return False, "no_matching_principal"


def build_acl_explain(
    chunk_id: str,
    chunk_metadata: dict[str, Any] | None,
    principal_ids: list[str] | None,
) -> AclExplain:
    permitted, reason = acl_explain_reason(chunk_metadata, principal_ids)
    acl = AclMetadata.from_metadata(chunk_metadata)
    return AclExplain(
        chunk_id=str(chunk_id),
        visibility=acl.visibility,
        permitted=permitted,
        reason=reason,
    )


def acl_permits_chunk_metadata(
    chunk_metadata: dict[str, Any] | None,
    principal_ids: list[str] | None,
) -> bool:
    return AclMetadata.from_metadata(chunk_metadata).permits(principal_ids)


def acl_summary_from_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    return AclMetadata.from_metadata(metadata).summary()
