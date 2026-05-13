from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ragrig.parsers.advanced import (
    AdvancedParseResult,
    AdvancedParserRunner,
    CorpusSummary,
    DegradedReason,
    ParserStatus,
)
from ragrig.parsers.advanced.adapter import AdvancedParserAdapter
from ragrig.parsers.advanced.docling import DoclingAdapter
from ragrig.parsers.advanced.mineru import MinerUAdapter
from ragrig.parsers.advanced.ocr import OcrFallbackHandler
from ragrig.parsers.advanced.unstructured import UnstructuredAdapter

pytestmark = pytest.mark.unit

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "advanced_documents"


# ── Fixture verification ──


def test_fixtures_exist() -> None:
    assert FIXTURES_DIR.exists(), f"Fixtures directory not found: {FIXTURES_DIR}"
    expected = {"sample.pdf", "sample.docx", "sample.pptx", "sample.xlsx"}
    actual = {p.name for p in FIXTURES_DIR.iterdir() if p.is_file()}
    assert expected.issubset(actual), f"Missing fixtures: {expected - actual}"


def test_fixtures_are_non_empty() -> None:
    for path in FIXTURES_DIR.iterdir():
        if path.is_file() and path.suffix.lower() in {".pdf", ".docx", ".pptx", ".xlsx"}:
            assert path.stat().st_size > 0, f"Fixture {path.name} is empty"


def test_fixtures_content_hash_stable() -> None:
    known = {
        "sample.pdf": "af374b5aaba5da2182acf9839f9500e410a6398f969f7658e9c0387b8a783da4",
        "sample.docx": "035e426783dac184f6c1cb585fd2cf5c1a2a07125887fec5d8fa677485b0657c",
        "sample.pptx": "39f3fe1ae72bc4b824da925126b60bcb6b04dc3afb3c7e94b670f07bd684da00",
        "sample.xlsx": "971dd620655877d52381532760a0c863fda0a560b43de34b9468b952aca50009",
    }
    for filename, expected_hash in known.items():
        path = FIXTURES_DIR / filename
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual_hash == expected_hash, f"Hash mismatch for {filename}"


# ── Adapter tests ──


def test_docling_adapter_can_parse_pdf() -> None:
    adapter = DoclingAdapter()
    pdf_path = FIXTURES_DIR / "sample.pdf"
    assert adapter.can_parse(pdf_path)
    assert adapter.parser_name == "advanced.docling"


def test_docling_adapter_rejects_unknown_format() -> None:
    adapter = DoclingAdapter()
    assert not adapter.can_parse(Path("foo.xyz"))
    assert not adapter.can_parse(Path("foo.txt"))


def test_docling_adapter_check_dependencies_returns_false() -> None:
    adapter = DoclingAdapter()
    assert not adapter.check_dependencies()


def test_docling_adapter_returns_skip_when_not_installed() -> None:
    adapter = DoclingAdapter()
    pdf_path = FIXTURES_DIR / "sample.pdf"
    result = adapter.parse(pdf_path)
    assert result.status == ParserStatus.SKIP
    assert result.degraded_reason == "missing_dependency"
    assert result.format == "docling"
    assert result.fixture_id == "sample"


def test_mineru_adapter_check_dependencies_returns_false() -> None:
    adapter = MinerUAdapter()
    assert not adapter.check_dependencies()


def test_unstructured_adapter_check_dependencies_returns_false() -> None:
    adapter = UnstructuredAdapter()
    assert not adapter.check_dependencies()


def test_adapter_display_name() -> None:
    assert DoclingAdapter().display_name == "Advanced.Docling"
    assert MinerUAdapter().display_name == "Advanced.Mineru"
    assert UnstructuredAdapter().display_name == "Advanced.Unstructured"


# ── Runner tests: discover ──


def test_runner_discovers_fixtures() -> None:
    runner = AdvancedParserRunner(fixtures_dir=FIXTURES_DIR)
    fixtures = runner.discover_fixtures()
    assert len(fixtures) >= 4
    formats = {f["format"] for f in fixtures}
    assert formats == {"pdf", "docx", "pptx", "xlsx"}


def test_runner_discovers_empty_dir(tmp_path) -> None:
    runner = AdvancedParserRunner(fixtures_dir=tmp_path)
    fixtures = runner.discover_fixtures()
    assert fixtures == []


def test_runner_discovers_nonexistent_dir() -> None:
    runner = AdvancedParserRunner(fixtures_dir=Path("/nonexistent/path"))
    fixtures = runner.discover_fixtures()
    assert fixtures == []


# ── Runner tests: run_all ──


def test_runner_run_all_returns_summary() -> None:
    runner = AdvancedParserRunner(fixtures_dir=FIXTURES_DIR)
    summary = runner.run_all()
    assert isinstance(summary, CorpusSummary)
    assert summary.total_fixtures >= 4
    assert summary.healthy == 0
    # With no parser deps, all should be skipped
    assert summary.skipped >= 4
    assert summary.degraded == 0
    assert summary.failed == 0


def test_runner_run_all_results_sorted() -> None:
    runner = AdvancedParserRunner(fixtures_dir=FIXTURES_DIR)
    summary = runner.run_all()
    formats = [r.format for r in summary.results]
    assert formats == sorted(formats)
    assert summary.generated_at is not None


def test_runner_run_all_each_result_has_expected_fields() -> None:
    runner = AdvancedParserRunner(fixtures_dir=FIXTURES_DIR)
    summary = runner.run_all()
    for r in summary.results:
        assert r.format in {"pdf", "docx", "pptx", "xlsx"}
        assert r.fixture_id == "sample"
        assert r.parser in {"advanced.docling", "advanced.mineru", "advanced.unstructured"}
        assert r.status in {ParserStatus.SKIP}
        assert r.degraded_reason == "missing_dependency"
        assert isinstance(r.text_length, int)
        assert isinstance(r.table_count, int)
        assert isinstance(r.page_or_slide_count, int)


# ── Runner tests: corrupt/empty fixtures ──


def test_runner_handles_empty_file(tmp_path) -> None:
    empty_path = tmp_path / "empty.pdf"
    empty_path.write_bytes(b"")
    runner = AdvancedParserRunner(fixtures_dir=tmp_path)
    summary = runner.run_all()
    assert summary.total_fixtures == 1
    assert summary.degraded == 1
    r = summary.results[0]
    assert r.status == ParserStatus.DEGRADED
    assert r.degraded_reason == DegradedReason.CORRUPT_ARTIFACT.value


def test_runner_handles_corrupt_file(tmp_path) -> None:
    corrupt_path = tmp_path / "corrupt.docx"
    corrupt_path.write_bytes(b"\x00\x01\x02\xff\xfe\xfd")
    runner = AdvancedParserRunner(fixtures_dir=tmp_path)
    summary = runner.run_all()
    assert summary.total_fixtures == 1
    r = summary.results[0]
    # The runner can read the file (it's non-empty), and docling adapter
    # claims .docx but has missing deps, so it is skipped
    assert r.status == ParserStatus.SKIP
    assert r.degraded_reason == DegradedReason.MISSING_DEPENDENCY.value


def test_runner_handles_missing_file_via_adapter(tmp_path, monkeypatch) -> None:
    path = tmp_path / "ghost.pdf"
    path.write_bytes(b"some content")

    class BrokenAdapter(AdvancedParserAdapter):
        parser_name = "test.broken"

        def can_parse(self, p: Path) -> bool:
            return p.suffix == ".pdf"

        def check_dependencies(self) -> bool:
            return True

        def parse(self, p: Path) -> AdvancedParseResult:
            raise FileNotFoundError("file vanished")

    runner = AdvancedParserRunner(fixtures_dir=tmp_path, adapters=[BrokenAdapter()])
    summary = runner.run_all()
    assert summary.total_fixtures == 1
    r = summary.results[0]
    assert r.status == ParserStatus.FAILURE
    assert r.degraded_reason == DegradedReason.PARSER_ERROR.value


# ── Runner tests: unsupported format ──


def test_runner_handles_unsupported_format(tmp_path) -> None:
    path = tmp_path / "test.xyz"
    path.write_text("hello", encoding="utf-8")
    runner = AdvancedParserRunner(fixtures_dir=tmp_path)
    fixtures = runner.discover_fixtures()
    # discover_fixtures only returns .pdf/.docx/.pptx/.xlsx
    assert fixtures == []


# ── Runner tests: missing fixture detection ──


def test_runner_reports_missing_known_fixtures(tmp_path) -> None:
    runner = AdvancedParserRunner(
        fixtures_dir=tmp_path,
        known_fixtures=[
            {"fixture_id": "doc1", "format": "pdf", "filename": "doc1.pdf"},
            {"fixture_id": "doc2", "format": "docx", "filename": "doc2.docx"},
        ],
    )
    summary = runner.run_all()
    assert summary.total_fixtures == 2
    assert summary.failed == 2
    for r in summary.results:
        assert r.status == ParserStatus.FAILURE
        assert r.degraded_reason == "corrupt_artifact"
        assert "missing expected fixture" in r.metadata.get("error", "")


def test_runner_partial_known_fixtures_missing(tmp_path) -> None:
    (tmp_path / "doc1.pdf").write_bytes(b"%PDF content")
    runner = AdvancedParserRunner(
        fixtures_dir=tmp_path,
        known_fixtures=[
            {"fixture_id": "doc1", "format": "pdf", "filename": "doc1.pdf"},
            {"fixture_id": "doc2", "format": "docx", "filename": "doc2.docx"},
        ],
    )
    summary = runner.run_all()
    assert summary.total_fixtures == 2
    assert summary.failed == 1
    assert summary.skipped == 1 or summary.healthy == 1


def test_runner_no_false_missing_without_known_fixtures(tmp_path) -> None:
    (tmp_path / "custom.pdf").write_bytes(b"%PDF data")
    runner = AdvancedParserRunner(fixtures_dir=tmp_path)
    summary = runner.run_all()
    assert summary.total_fixtures == 1


# ── OCR fallback tests ──


def test_ocr_handler_disabled_by_default() -> None:
    handler = OcrFallbackHandler()
    assert not handler.enabled


def test_ocr_handler_enabled() -> None:
    handler = OcrFallbackHandler(enabled=True)
    assert handler.enabled


def test_ocr_needs_ocr_empty_text() -> None:
    handler = OcrFallbackHandler()
    result = AdvancedParseResult(
        format="pdf",
        fixture_id="test",
        parser="test",
        status=ParserStatus.HEALTHY,
        text_length=0,
    )
    assert handler.needs_ocr(result)


def test_ocr_needs_ocr_nonempty_text() -> None:
    handler = OcrFallbackHandler()
    result = AdvancedParseResult(
        format="pdf",
        fixture_id="test",
        parser="test",
        status=ParserStatus.HEALTHY,
        text_length=100,
    )
    assert not handler.needs_ocr(result)


def test_ocr_needs_ocr_non_healthy() -> None:
    handler = OcrFallbackHandler()
    result = AdvancedParseResult(
        format="pdf",
        fixture_id="test",
        parser="test",
        status=ParserStatus.SKIP,
        text_length=0,
    )
    assert not handler.needs_ocr(result)


def test_ocr_fallback_disabled() -> None:
    handler = OcrFallbackHandler(enabled=False)
    primary = AdvancedParseResult(
        format="pdf",
        fixture_id="scanned",
        parser="test.parser",
        status=ParserStatus.HEALTHY,
        text_length=0,
    )
    result = handler.apply_ocr_fallback(Path("test.pdf"), primary)
    # When OCR is disabled, primary result is returned unchanged
    assert result is primary


def test_ocr_fallback_disabled_with_text() -> None:
    handler = OcrFallbackHandler(enabled=False)
    primary = AdvancedParseResult(
        format="pdf",
        fixture_id="scanned",
        parser="test.parser",
        status=ParserStatus.HEALTHY,
        text_length=100,
    )
    result = handler.apply_ocr_fallback(Path("test.pdf"), primary)
    assert result is primary


def test_ocr_fallback_enabled_missing_deps() -> None:
    handler = OcrFallbackHandler(enabled=True)
    primary = AdvancedParseResult(
        format="pdf",
        fixture_id="scanned",
        parser="test.parser",
        status=ParserStatus.DEGRADED,
        text_length=0,
    )
    result = handler.apply_ocr_fallback(Path("test.pdf"), primary)
    assert result.status == ParserStatus.DEGRADED
    assert result.degraded_reason == "ocr_fallback"
    assert result.metadata["ocr_available"] is False
    assert result.metadata["ocr_applied"] is False


def test_ocr_mark_ocr_fallback_already_marked() -> None:
    handler = OcrFallbackHandler()
    result = AdvancedParseResult(
        format="pdf",
        fixture_id="test",
        parser="test",
        status=ParserStatus.DEGRADED,
        degraded_reason="ocr_fallback",
    )
    marked = handler.mark_ocr_fallback(result)
    assert marked is result


def test_ocr_mark_ocr_fallback_new_mark() -> None:
    handler = OcrFallbackHandler()
    result = AdvancedParseResult(
        format="pdf",
        fixture_id="test",
        parser="test",
        status=ParserStatus.DEGRADED,
        degraded_reason="parser_error",
        text_length=42,
        extracted_text="hello",
    )
    marked = handler.mark_ocr_fallback(result)
    assert marked.degraded_reason == "ocr_fallback"
    assert marked.metadata["ocr_fallback_marked"] is True
    assert marked.text_length == 42
    assert marked.extracted_text == "hello"


# ── Summary output tests ──


def test_summary_to_json_contains_expected_fields() -> None:
    runner = AdvancedParserRunner(fixtures_dir=FIXTURES_DIR)
    summary = runner.run_all()
    json_str = runner.summary_to_json(summary)
    data = json.loads(json_str)
    assert "generated_at" in data
    assert "total_fixtures" in data
    assert "healthy" in data
    assert "degraded" in data
    assert "skipped" in data
    assert "failed" in data
    assert "results" in data
    assert len(data["results"]) >= 4
    for r in data["results"]:
        assert "format" in r
        assert "fixture_id" in r
        assert "parser" in r
        assert "status" in r
        assert "text_length" in r
        assert "table_count" in r
        assert "page_or_slide_count" in r
        assert "degraded_reason" in r


def test_summary_to_markdown_contains_table() -> None:
    runner = AdvancedParserRunner(fixtures_dir=FIXTURES_DIR)
    summary = runner.run_all()
    md = runner.summary_to_markdown(summary)
    assert "## Results" in md
    assert "| Fmt | Fixture ID |" in md
    for r in summary.results:
        assert r.format in md
        assert r.fixture_id in md


def test_summary_counts_correct() -> None:
    runner = AdvancedParserRunner(fixtures_dir=FIXTURES_DIR)
    summary = runner.run_all()
    assert (
        summary.healthy + summary.degraded + summary.skipped + summary.failed
        == summary.total_fixtures
    )
    assert 0 <= summary.healthy <= summary.total_fixtures
    assert 0 <= summary.degraded <= summary.total_fixtures
    assert 0 <= summary.skipped <= summary.total_fixtures
    assert 0 <= summary.failed <= summary.total_fixtures


# ── Artifact schema tests ──


def test_artifact_schema_generation() -> None:
    runner = AdvancedParserRunner(fixtures_dir=FIXTURES_DIR)
    summary = runner.run_all()
    schema = runner.generate_artifact_schema(summary)
    assert schema.version == "1.0.0"
    assert len(schema.artifacts) >= 4
    for a in schema.artifacts:
        assert a.fixture_id == "sample"
        assert a.format in {"pdf", "docx", "pptx", "xlsx"}
        assert len(a.content_hash) == 64
        assert a.size_bytes > 0
        assert a.created_at is not None


def test_artifact_schema_hash_consistency() -> None:
    runner = AdvancedParserRunner(fixtures_dir=FIXTURES_DIR)
    summary = runner.run_all()
    schema = runner.generate_artifact_schema(summary)
    for a in schema.artifacts:
        path = Path(a.path)
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        assert a.content_hash == actual_hash, f"Hash mismatch for {a.path}"


# ── Secret leakage prevention tests ──


def test_runner_sanitizes_secrets_in_custom_adapter_output(tmp_path) -> None:
    class LeakyAdapter(AdvancedParserAdapter):
        parser_name = "test.leaky"

        def can_parse(self, p: Path) -> bool:
            return p.suffix == ".pdf"

        def check_dependencies(self) -> bool:
            return True

        def parse(self, p: Path) -> AdvancedParseResult:
            return AdvancedParseResult(
                format="pdf",
                fixture_id=p.stem,
                parser=self.parser_name,
                status=ParserStatus.HEALTHY,
                text_length=100,
                extracted_text="some content",
                metadata={
                    "text_summary": "Using key sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ for auth",
                    "config": "api_key=sk-live-1234567890abcdef",
                    "safe_field": "hello world",
                },
            )

    path = tmp_path / "test.pdf"
    path.write_bytes(b"%PDF some content")
    runner = AdvancedParserRunner(
        fixtures_dir=tmp_path,
        adapters=[LeakyAdapter()],
    )
    summary = runner.run_all()
    assert summary.total_fixtures == 1
    r = summary.results[0]
    meta = r.metadata
    assert "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in meta.get("text_summary", "")
    assert "[API KEY REDACTED]" in meta.get("text_summary", "")
    assert meta.get("redaction_count", 0) >= 1


def test_runner_sanitizes_real_adapter_output_when_available(tmp_path) -> None:
    class AdapterWithSecret(AdvancedParserAdapter):
        parser_name = "test.withsecret"

        def can_parse(self, p: Path) -> bool:
            return p.suffix == ".pdf"

        def check_dependencies(self) -> bool:
            return True

        def parse(self, p: Path) -> AdvancedParseResult:
            return AdvancedParseResult(
                format="pdf",
                fixture_id=p.stem,
                parser=self.parser_name,
                status=ParserStatus.HEALTHY,
                text_length=100,
                extracted_text="password=supersecret123\napi_key=sk-live-test",
                metadata={
                    "db_password": "supersecret123",
                },
            )

    path = tmp_path / "test.pdf"
    path.write_bytes(b"%PDF data")
    runner = AdvancedParserRunner(
        fixtures_dir=tmp_path,
        adapters=[AdapterWithSecret()],
    )
    summary = runner.run_all()
    r = summary.results[0]
    assert "[REDACTED]" in r.metadata.get("text_summary", "")
    assert r.metadata.get("redaction_count", 0) >= 1
    assert r.metadata.get("db_password") == "supersecret123"


def test_runner_redaction_count_increments_for_secret_content(tmp_path) -> None:
    class SecretAdapter(AdvancedParserAdapter):
        parser_name = "test.secret"

        def can_parse(self, p: Path) -> bool:
            return p.suffix == ".pdf"

        def check_dependencies(self) -> bool:
            return True

        def parse(self, p: Path) -> AdvancedParseResult:
            return AdvancedParseResult(
                format="pdf",
                fixture_id=p.stem,
                parser=self.parser_name,
                status=ParserStatus.HEALTHY,
                text_length=50,
                extracted_text="api_key=sk-abc\npassword=xyz\n",
                metadata={
                    "text_summary": "api_key=sk-abc\npassword=xyz",
                },
            )

    path = tmp_path / "test.pdf"
    path.write_bytes(b"%PDF data")
    runner = AdvancedParserRunner(
        fixtures_dir=tmp_path,
        adapters=[SecretAdapter()],
    )
    summary = runner.run_all()
    r = summary.results[0]
    assert r.metadata["redaction_count"] >= 1


# ── Corpus check script integration (via runner) ──


def test_corpus_check_script_output_matches_runner(tmp_path) -> None:
    from scripts.advanced_parser_corpus_check import _make_json, _make_markdown

    runner = AdvancedParserRunner(fixtures_dir=FIXTURES_DIR)
    summary = runner.run_all()

    json_str = _make_json(summary)
    md_str = _make_markdown(summary)

    data = json.loads(json_str)
    assert data["total_fixtures"] == summary.total_fixtures
    assert data["healthy"] == summary.healthy
    assert data["degraded"] == summary.degraded
    assert data["skipped"] == summary.skipped
    assert data["failed"] == summary.failed
    assert "| pdf" in md_str


def test_corpus_check_exit_code_healthy(tmp_path) -> None:
    from scripts.advanced_parser_corpus_check import main as check_main

    path = tmp_path / "test.pdf"
    path.write_bytes(b"%PDF-1.4 some content")
    import os
    import sys

    old_argv = sys.argv
    old_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        sys.argv = ["prog", "--json-output", str(tmp_path / "out.json")]

        class FakeRunner:
            def __init__(self, *args, **kwargs):
                pass

            def run_all(self):
                return CorpusSummary(
                    generated_at="2026-01-01T00:00:00Z",
                    total_fixtures=1,
                    healthy=0,
                    degraded=0,
                    skipped=1,
                    failed=0,
                    results=[
                        AdvancedParseResult(
                            format="pdf",
                            fixture_id="test",
                            parser="skip",
                            status=ParserStatus.SKIP,
                            degraded_reason="missing_dependency",
                        )
                    ],
                )

        import scripts.advanced_parser_corpus_check as mod

        original_runner = mod.AdvancedParserRunner
        mod.AdvancedParserRunner = FakeRunner
        try:
            exit_code = check_main()
            assert exit_code == 0
        finally:
            mod.AdvancedParserRunner = original_runner
    finally:
        sys.argv = old_argv
        os.chdir(old_cwd)


# ── Edge cases ──


def test_parse_result_frozen() -> None:
    result = AdvancedParseResult(
        format="pdf", fixture_id="t", parser="p", status=ParserStatus.HEALTHY
    )
    with pytest.raises(AttributeError):
        result.format = "docx"


def test_parse_result_defaults() -> None:
    result = AdvancedParseResult(
        format="pdf", fixture_id="t", parser="p", status=ParserStatus.HEALTHY
    )
    assert result.text_length == 0
    assert result.table_count == 0
    assert result.page_or_slide_count == 0
    assert result.degraded_reason is None
    assert result.extracted_text == ""
    assert result.metadata == {}


def test_degraded_reason_values() -> None:
    reasons = [
        DegradedReason.MISSING_DEPENDENCY,
        DegradedReason.CORRUPT_ARTIFACT,
        DegradedReason.STALE_ARTIFACT,
        DegradedReason.PARSER_TIMEOUT,
        DegradedReason.PARSER_ERROR,
        DegradedReason.OCR_FALLBACK,
        DegradedReason.UNSUPPORTED_FORMAT,
    ]
    for reason in reasons:
        assert isinstance(reason.value, str)


def test_parser_status_values() -> None:
    statuses = [
        ParserStatus.HEALTHY,
        ParserStatus.DEGRADED,
        ParserStatus.SKIP,
        ParserStatus.FAILURE,
    ]
    for s in statuses:
        assert isinstance(s.value, str)


def test_runner_with_custom_adapters(tmp_path) -> None:
    path = tmp_path / "test.pdf"
    path.write_bytes(b"%PDF some content")

    class CustomAdapter(AdvancedParserAdapter):
        parser_name = "test.custom"

        def can_parse(self, p: Path) -> bool:
            return p.suffix == ".pdf"

        def check_dependencies(self) -> bool:
            return True

        def parse(self, p: Path) -> AdvancedParseResult:
            return AdvancedParseResult(
                format="pdf",
                fixture_id=p.stem,
                parser=self.parser_name,
                status=ParserStatus.HEALTHY,
                text_length=100,
                page_or_slide_count=1,
                extracted_text="test content",
            )

    runner = AdvancedParserRunner(fixtures_dir=tmp_path, adapters=[CustomAdapter()])
    summary = runner.run_all()
    assert summary.total_fixtures == 1
    assert summary.healthy == 1
    r = summary.results[0]
    assert r.parser == "test.custom"
    assert r.text_length == 100
    assert r.page_or_slide_count == 1
    assert r.extracted_text == "test content"
