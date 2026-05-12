"""Tests for ACL metadata model and filtering logic."""

from __future__ import annotations

import pytest

from ragrig.acl import (
    AclMetadata,
    Principal,
    acl_permits_chunk_metadata,
    acl_summary_from_metadata,
)

pytestmark = pytest.mark.unit


def test_public_document_permits_without_principal() -> None:
    """Public document has no principal and is retrievable."""
    acl = AclMetadata(visibility="public")
    assert acl.permits(None) is True
    assert acl.permits([]) is True
    assert acl.permits(["anyone"]) is True


def test_protected_document_permits_with_valid_principal() -> None:
    """Protected document + valid principal → returns True."""
    acl = AclMetadata(
        visibility="protected",
        allowed_principals=["alice", "group:engineering"],
    )
    assert acl.permits(["alice"]) is True
    assert acl.permits(["group:engineering"]) is True
    assert acl.permits(["alice", "extra"]) is True


def test_protected_document_denies_without_principal() -> None:
    """Protected document + no principal → returns False."""
    acl = AclMetadata(
        visibility="protected",
        allowed_principals=["alice"],
    )
    assert acl.permits(None) is False
    assert acl.permits([]) is False


def test_protected_document_denies_blocked_principal() -> None:
    """Protected document + denied principal → returns False."""
    acl = AclMetadata(
        visibility="protected",
        allowed_principals=["alice", "bob"],
        denied_principals=["bob"],
    )
    assert acl.permits(["bob"]) is False
    assert acl.permits(["alice"]) is True
    assert acl.permits(["alice", "bob"]) is False  # denied takes precedence


def test_unknown_visibility_blocks_all() -> None:
    """Unknown visibility blocks regardless of principal."""
    acl = AclMetadata(
        visibility="unknown",
        allowed_principals=["alice"],
    )
    assert acl.permits(["alice"]) is False
    assert acl.permits(None) is False
    assert acl.permits([]) is False


def test_default_acl_is_public() -> None:
    """Default AclMetadata (no args) is public."""
    acl = AclMetadata()
    assert acl.visibility == "public"
    assert acl.permits(None) is True


def test_case_insensitive_principal_matching() -> None:
    """Principal matching is case-insensitive."""
    acl = AclMetadata(
        visibility="protected",
        allowed_principals=["Alice"],
        denied_principals=["bob"],
    )
    assert acl.permits(["alice"]) is True
    assert acl.permits(["ALICE"]) is True
    assert acl.permits(["BOB"]) is False


def test_principal_expands_user_and_group_subjects() -> None:
    principal = Principal(user_id="Alice", group_ids=["Engineering", "Engineering"])
    assert principal.subject_ids() == ["user:alice", "alice", "group:engineering"]

    acl = AclMetadata(visibility="protected", allowed_principals=["group:engineering"])
    assert acl.permits(principal.subject_ids()) is True


def test_from_metadata_extracts_acl_correctly() -> None:
    """AclMetadata.from_metadata extracts ACL from metadata_json."""
    metadata = {
        "acl": {
            "visibility": "protected",
            "allowed_principals": ["alice"],
            "denied_principals": ["bob"],
            "acl_source": "fileshare:alice:eng",
            "acl_source_hash": "abc123",
            "inheritance": "document",
        }
    }
    acl = AclMetadata.from_metadata(metadata)
    assert acl.visibility == "protected"
    assert acl.allowed_principals == ["alice"]
    assert acl.denied_principals == ["bob"]
    assert acl.acl_source == "fileshare:alice:eng"
    assert acl.acl_source_hash == "abc123"
    assert acl.inheritance == "document"


def test_from_metadata_without_acl_key_returns_public() -> None:
    """Metadata without 'acl' key returns public default."""
    acl = AclMetadata.from_metadata({"other": "data"})
    assert acl.visibility == "public"
    assert acl.permits(None) is True


def test_from_metadata_with_none_returns_public() -> None:
    """None metadata returns public default."""
    acl = AclMetadata.from_metadata(None)
    assert acl.visibility == "public"


def test_from_metadata_with_non_dict_acl_returns_public() -> None:
    """Non-dict acl field returns public default."""
    acl = AclMetadata.from_metadata({"acl": "not-a-dict"})
    assert acl.visibility == "public"


def test_from_metadata_coerces_invalid_visibility() -> None:
    """Invalid visibility values coerce to 'unknown'."""
    acl = AclMetadata.from_metadata({"acl": {"visibility": "secret"}})
    assert acl.visibility == "unknown"


def test_from_metadata_coerces_non_list_principals() -> None:
    """Non-list principals coerce to empty lists."""
    acl = AclMetadata.from_metadata(
        {"acl": {"visibility": "protected", "allowed_principals": "not-a-list"}}
    )
    assert acl.allowed_principals == []


def test_to_dict_round_trip() -> None:
    """AclMetadata.to_dict produces input for from_metadata."""
    original = AclMetadata(
        visibility="protected",
        allowed_principals=["alice", "group:eng"],
        denied_principals=["bob"],
        acl_source="test",
        acl_source_hash="hash1",
        inheritance="document",
        ttl="2026-06-01T00:00:00+00:00",
    )
    d = original.to_dict()
    restored = AclMetadata.from_metadata({"acl": d})
    assert restored.visibility == original.visibility
    assert restored.allowed_principals == original.allowed_principals
    assert restored.denied_principals == original.denied_principals
    assert restored.ttl == original.ttl


def test_summary_hides_full_principal_lists() -> None:
    """Summary does not expose full allowed/denied principal lists."""
    acl = AclMetadata(
        visibility="protected",
        allowed_principals=["alice-admin", "bob-user", "charlie-viewer"],
        denied_principals=["xavier-blocked"],
        acl_source="fileshare_test",
    )
    summary = acl.summary()
    assert summary["visibility"] == "protected"
    assert summary["has_allowed_principals"] is True
    assert summary["has_denied_principals"] is True
    # Principal identities must not appear in summary dict values
    summary_values = " ".join(str(v) for v in summary.values())
    assert "alice-admin" not in summary_values
    assert "xavier-blocked" not in summary_values
    assert summary["acl_source"] == "fileshare_test"
    assert summary["stale"] is False


def test_summary_detects_stale_ttl() -> None:
    """Summary detects stale TTL."""
    acl = AclMetadata(
        visibility="protected",
        allowed_principals=["alice"],
        ttl="2020-01-01T00:00:00+00:00",
    )
    summary = acl.summary()
    assert summary["stale"] is True
    assert summary["stale_hint"] == "acl_ttl_expired"


def test_summary_handles_invalid_ttl() -> None:
    """Summary handles invalid TTL gracefully."""
    acl = AclMetadata(
        visibility="protected",
        allowed_principals=["alice"],
        ttl="not-a-date",
    )
    summary = acl.summary()
    assert summary["stale"] is False
    assert summary["stale_hint"] is None


def test_for_propagation_clones_and_sets_inheritance() -> None:
    """for_propagation clones ACL and sets inheritance to 'propagated'."""
    acl = AclMetadata(
        visibility="protected",
        allowed_principals=["alice"],
        denied_principals=["bob"],
        acl_source="fileshare",
        acl_source_hash="abc",
        inheritance="document",
    )
    propagated = acl.for_propagation("doc-id")
    assert propagated.visibility == "protected"
    assert propagated.allowed_principals == ["alice"]
    assert propagated.denied_principals == ["bob"]
    assert propagated.inheritance == "propagated"
    # Verify it's a copy, not same list reference
    assert propagated.allowed_principals is not acl.allowed_principals


def test_acl_permits_chunk_metadata_convenience() -> None:
    """acl_permits_chunk_metadata works as convenience function."""
    metadata = {"acl": {"visibility": "protected", "allowed_principals": ["alice"]}}
    assert acl_permits_chunk_metadata(metadata, ["alice"]) is True
    assert acl_permits_chunk_metadata(metadata, ["bob"]) is False
    assert acl_permits_chunk_metadata(None, None) is True  # public default


def test_acl_summary_from_metadata_convenience() -> None:
    """acl_summary_from_metadata works as convenience function."""
    metadata = {"acl": {"visibility": "public"}}
    summary = acl_summary_from_metadata(metadata)
    assert summary["visibility"] == "public"
    assert summary["has_allowed_principals"] is False


def test_document_id_not_in_summary() -> None:
    """Verify document_id is not leaked in ACL summary."""
    acl = AclMetadata(
        visibility="protected",
        allowed_principals=["doc-123"],
    )
    summary = acl.summary()
    assert "doc-123" not in str(summary)
