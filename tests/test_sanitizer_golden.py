"""Golden-snapshot regression tests for the preview metadata sanitizer.

Each sensitive fixture (CSV, HTML, plaintext, markdown) has a corresponding
golden JSON file under tests/goldens/ that records the expected
sanitizer output: parser_id, status, text_summary, redaction_count, and
(degraded_reason).

When the sanitizer is updated, run::

    python -m scripts.snapshot_update

to regenerate the golden files, then review the diff.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ragrig.parsers.csv import CsvParser
from ragrig.parsers.html import HtmlParser
from ragrig.parsers.markdown import MarkdownParser
from ragrig.parsers.plaintext import PlainTextParser

pytestmark = pytest.mark.unit

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "preview"
GOLDENS_DIR = Path(__file__).resolve().parent / "goldens"

# ── Fixture → Parser → Golden mapping ──────────────────────────────────────

_GOLDEN_MAPPING: list[tuple[type, str, str]] = [
    (CsvParser, "sensitive.csv", "sanitizer_csv_sensitive.json"),
    (HtmlParser, "sensitive.html", "sanitizer_html_sensitive.json"),
    (PlainTextParser, "sensitive.txt", "sanitizer_plaintext_sensitive.json"),
    (MarkdownParser, "sensitive.md", "sanitizer_markdown_sensitive.json"),
]

# Fields that MUST be present in every golden snapshot.
_REQUIRED_GOLDEN_FIELDS = frozenset({"parser_id", "status", "text_summary", "redaction_count"})


def _build_golden_record(metadata: dict[str, Any]) -> dict[str, Any]:
    """Extract the golden record from parser metadata.

    Only includes the fields required by the contract.  Secret-like
    patterns are never written to disk.
    """
    record: dict[str, Any] = {
        "parser_id": metadata["parser_id"],
        "status": metadata["status"],
        "text_summary": metadata["text_summary"],
        "redaction_count": metadata["redaction_count"],
    }
    if "degraded_reason" in metadata:
        record["degraded_reason"] = metadata["degraded_reason"]
    if "csv_parse_error" in metadata:
        record["csv_parse_error"] = metadata["csv_parse_error"]
    return record


def _assert_required_fields(present: set[str], golden_path: Path) -> None:
    missing = _REQUIRED_GOLDEN_FIELDS - present
    assert not missing, (
        f"Golden file {golden_path.name} is missing required fields: {', '.join(sorted(missing))}"
    )


def _assert_no_raw_secret_in_text(record: dict[str, Any], golden_path: Path) -> None:
    """Verify the golden snapshot itself never contains raw secret values.

    We check the text_summary and every string value for known secret
    fragments that must never be written to disk.
    """
    forbidden = (
        "sk-live-9876543210abcdef",
        "sk-proj-abcdefghijklmnop",
        "sk-ant-api03-xyz1234567890",
        "super_secret_db_pass",
        "db-super-secret-999",
        "prod-api-secret-key-2024",
        "ghp_abcdefghijklmno12345",
        "sk-embedded-secret-key-12345",
        # Private key PEM fragments
        "MIIEvQIBADANBgkqhkiG9w0BAQ",
        "MIIEpA",
    )
    for key, value in record.items():
        if isinstance(value, str):
            for fragment in forbidden:
                assert fragment not in value, (
                    f"Golden file {golden_path.name}: field '{key}' contains raw secret fragment"
                )


# ── Per-fixture golden regression tests ────────────────────────────────────


def _run_golden_test(parser_cls: type, fixture_name: str, golden_name: str) -> None:
    fixture_path = FIXTURES_DIR / fixture_name
    golden_path = GOLDENS_DIR / golden_name

    assert fixture_path.is_file(), f"Fixture missing: {fixture_path}"
    assert golden_path.is_file(), (
        f"Golden missing: {golden_path}\nRun: python -m scripts.snapshot_update"
    )

    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    _assert_required_fields(set(golden.keys()), golden_path)
    _assert_no_raw_secret_in_text(golden, golden_path)

    result = parser_cls().parse(fixture_path)

    actual = _build_golden_record(result.metadata)

    # Compare field-by-field for clear failure messages.
    for field in _REQUIRED_GOLDEN_FIELDS:
        assert actual[field] == golden[field], (
            f"Golden mismatch in {golden_name}: field '{field}'\n"
            f"  expected: {golden[field]!r}\n"
            f"  actual:   {actual[field]!r}\n"
            f"Run 'python -m scripts.snapshot_update' if this change is intentional."
        )

    # degraded_reason and csv_parse_error are optional, but if present in
    # golden they must match.
    for opt_field in ("degraded_reason", "csv_parse_error"):
        if opt_field in golden or opt_field in actual:
            assert actual.get(opt_field) == golden.get(opt_field), (
                f"Golden mismatch in {golden_name}: field '{opt_field}'\n"
                f"  expected: {golden.get(opt_field)!r}\n"
                f"  actual:   {actual.get(opt_field)!r}"
            )


@pytest.mark.parametrize(
    "parser_cls,fixture_name,golden_name",
    _GOLDEN_MAPPING,
)
def test_sanitizer_golden_regression(parser_cls: type, fixture_name: str, golden_name: str) -> None:
    """Each parser's sensitive fixture output matches the checked-in golden."""
    _run_golden_test(parser_cls, fixture_name, golden_name)


# ── Coverage Summary ───────────────────────────────────────────────────────


def _coverage_row(
    parser_id: str, fixture_count: int, redacted: int, degraded: int
) -> dict[str, Any]:
    return {
        "parser_id": parser_id,
        "fixture_count": fixture_count,
        "redacted_count": redacted,
        "degraded_count": degraded,
    }


def test_sanitizer_coverage_summary() -> None:
    """Collect and assert the sanitizer coverage summary across all parsers.

    This test serves as both a documentation point and a regression guard:
    if a parser stops producing redaction or a fixture goes missing,
    the counts here will change and the test will fail.
    """
    summary_rows: list[dict[str, Any]] = []

    for _parser_cls, _fixture_name, golden_name in _GOLDEN_MAPPING:
        golden_path = GOLDENS_DIR / golden_name

        assert golden_path.is_file(), f"Golden missing: {golden_path}"

        golden = json.loads(golden_path.read_text(encoding="utf-8"))

        parser_id = golden["parser_id"]
        redacted = golden["redaction_count"]
        degraded = 1 if golden.get("status") == "degraded" else 0

        summary_rows.append(
            _coverage_row(parser_id, fixture_count=1, redacted=redacted, degraded=degraded)
        )

    # Print summary for human-readable test output
    print("\n── Sanitizer Coverage Summary ──")
    print(f"{'Parser ID':<22} {'Fixtures':>9} {'Redacted':>9} {'Degraded':>9}")
    print("-" * 51)
    for row in summary_rows:
        print(
            f"{row['parser_id']:<22} "
            f"{row['fixture_count']:>9} "
            f"{row['redacted_count']:>9} "
            f"{row['degraded_count']:>9}"
        )

    total_fixtures = sum(r["fixture_count"] for r in summary_rows)
    total_redacted = sum(r["redacted_count"] for r in summary_rows)
    total_degraded = sum(r["degraded_count"] for r in summary_rows)
    print("-" * 51)
    print(f"{'TOTAL':<22} {total_fixtures:>9} {total_redacted:>9} {total_degraded:>9}")

    # Regression assertions
    assert total_fixtures == 4, f"Expected 4 parser fixtures, got {total_fixtures}"
    # Every sensitive fixture must have redaction_count >= 1
    for row in summary_rows:
        assert row["redacted_count"] >= 1, (
            f"Parser '{row['parser_id']}' has 0 redactions in its sensitive fixture. "
            f"The fixture may have been accidentally cleaned or the sanitizer "
            f"regressed."
        )


def test_golden_snapshots_never_contain_raw_secrets() -> None:
    """Audit every checked-in golden snapshot for raw secret values.

    This is a secondary safety net beyond _assert_no_raw_secret_in_text:
    it reads all golden files from disk regardless of the test mapping.
    """
    if not GOLDENS_DIR.is_dir():
        pytest.skip("No goldens directory present")

    golden_files = sorted(GOLDENS_DIR.glob("sanitizer_*.json"))
    if not golden_files:
        pytest.skip("No golden files found")

    # Patterns that must NOT appear in any golden file on disk
    forbidden_anywhere = (
        # API key patterns
        "sk-live-",
        "sk-proj-",
        "sk-ant-",
        "ghp_abcdef",
        "eyJhbGci",
        # PEM private key
        "PRIVATE KEY-----",
        # Credential fragments from fixtures
        "super_secret_db_pass",
        "db-super-secret-999",
        "prod-api-secret-key-2024",
    )

    for golden_path in golden_files:
        content = golden_path.read_text(encoding="utf-8")
        for fragment in forbidden_anywhere:
            assert fragment not in content, (
                f"Golden file {golden_path.name} contains raw secret fragment "
                f"on disk. This is a critical sanitization failure."
            )
