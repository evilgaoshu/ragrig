"""Validate that the domain-specific golden question YAML fixture files are
well-formed, schema-compliant, and internally consistent."""

from __future__ import annotations

from pathlib import Path

import pytest

from ragrig.evaluation.fixture import load_golden_question_set

pytestmark = pytest.mark.unit

FIXTURES_DIR = Path(__file__).parent / "fixtures"

GOLDEN_FILES = [
    "evaluation_golden.yaml",
    "evaluation_golden_retrieval.yaml",
    "evaluation_golden_edge_cases.yaml",
    "evaluation_golden_multi_doc.yaml",
]


@pytest.mark.parametrize("filename", GOLDEN_FILES)
def test_golden_fixture_loads_without_error(filename: str) -> None:
    """Each golden YAML file must parse into a valid GoldenQuestionSet."""
    path = FIXTURES_DIR / filename
    assert path.exists(), f"Fixture file missing: {path}"
    gqs = load_golden_question_set(path)
    assert gqs.name, f"{filename}: name must not be empty"
    assert gqs.questions, f"{filename}: questions list must not be empty"
    assert gqs.version, f"{filename}: version must not be empty"


@pytest.mark.parametrize("filename", GOLDEN_FILES)
def test_every_question_has_a_query(filename: str) -> None:
    """Every GoldenQuestion must have a non-empty query string."""
    gqs = load_golden_question_set(FIXTURES_DIR / filename)
    for i, q in enumerate(gqs.questions):
        assert q.query.strip(), f"{filename}[{i}]: query must not be blank"


@pytest.mark.parametrize("filename", GOLDEN_FILES)
def test_every_question_has_at_least_one_expectation(filename: str) -> None:
    """Each question must carry at least one expectation so the evaluator can score it."""
    gqs = load_golden_question_set(FIXTURES_DIR / filename)
    for i, q in enumerate(gqs.questions):
        has_expectation = bool(
            q.expected_doc_uri
            or q.expected_chunk_uri
            or q.expected_chunk_text is not None
            or q.expected_citation
            or q.expected_answer_keywords
        )
        assert has_expectation, (
            f"{filename}[{i}] (query={q.query!r}): "
            "must have at least one of expected_doc_uri, expected_chunk_uri, "
            "expected_chunk_text, expected_citation, or expected_answer_keywords"
        )


@pytest.mark.parametrize("filename", GOLDEN_FILES)
def test_every_question_has_tags(filename: str) -> None:
    """Every question should have at least one tag for filtering."""
    gqs = load_golden_question_set(FIXTURES_DIR / filename)
    for i, q in enumerate(gqs.questions):
        assert q.tags, f"{filename}[{i}] (query={q.query!r}): must have at least one tag"


def test_retrieval_set_has_hit_and_miss_questions() -> None:
    """The main retrieval fixture should contain both hit and miss-tagged questions."""
    gqs = load_golden_question_set(FIXTURES_DIR / "evaluation_golden_retrieval.yaml")
    tags_all = {tag for q in gqs.questions for tag in q.tags}
    assert "hit" in tags_all
    assert "lexical" in tags_all
    assert "semantic" in tags_all


def test_edge_cases_set_has_zero_result_questions() -> None:
    """The edge-cases fixture must include zero-result miss questions."""
    gqs = load_golden_question_set(FIXTURES_DIR / "evaluation_golden_edge_cases.yaml")
    zero_result_qs = [q for q in gqs.questions if "zero-results" in q.tags]
    assert len(zero_result_qs) >= 2, "edge-cases set should have at least 2 zero-result questions"


def test_edge_cases_set_has_adversarial_questions() -> None:
    """The edge-cases fixture must include adversarial query questions."""
    gqs = load_golden_question_set(FIXTURES_DIR / "evaluation_golden_edge_cases.yaml")
    adversarial = [q for q in gqs.questions if "adversarial" in q.tags]
    assert len(adversarial) >= 1


def test_multi_doc_set_has_disambiguation_questions() -> None:
    """The multi-doc fixture must include questions tagged for disambiguation."""
    gqs = load_golden_question_set(FIXTURES_DIR / "evaluation_golden_multi_doc.yaml")
    disambig = [q for q in gqs.questions if "disambiguation" in q.tags]
    assert len(disambig) >= 2


def test_multi_doc_set_covers_all_fixture_docs() -> None:
    """The multi-doc fixture should have questions targeting all three fixture docs."""
    gqs = load_golden_question_set(FIXTURES_DIR / "evaluation_golden_multi_doc.yaml")
    doc_uris = {q.expected_doc_uri for q in gqs.questions if q.expected_doc_uri}
    assert "guide.md" in doc_uris
    assert "notes.txt" in doc_uris
    assert "nested/deep.md" in doc_uris


def test_golden_default_set_has_smoke_questions() -> None:
    """The default golden set must contain smoke-tagged questions for CI."""
    gqs = load_golden_question_set(FIXTURES_DIR / "evaluation_golden.yaml")
    smoke_qs = [q for q in gqs.questions if "smoke" in q.tags]
    assert len(smoke_qs) >= 3, "default set should have at least 3 smoke questions"


def test_no_duplicate_queries_within_set() -> None:
    """Queries within a single golden set should be unique to avoid redundant evaluation."""
    for filename in GOLDEN_FILES:
        gqs = load_golden_question_set(FIXTURES_DIR / filename)
        queries = [q.query.strip().lower() for q in gqs.questions]
        seen: set[str] = set()
        for q in queries:
            assert q not in seen, f"{filename}: duplicate query {q!r}"
            seen.add(q)
