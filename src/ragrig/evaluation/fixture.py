"""Load golden question fixtures from YAML or JSON files.

Expected YAML format:

    golden_question_set:
      name: "default"
      description: "Example golden question set"
      version: "1.0.0"
      questions:
        - query: "What is RAGRig?"
          expected_doc_uri: "guide.md"
          expected_citation: "RAGRig is a retrieval-augmented generation framework"
          expected_answer_keywords: ["retrieval", "generation"]
        - query: "How to configure?"
          expected_chunk_uri: "guide.md#configuration"
          expected_chunk_text: "configure the settings"
          tags: ["config"]

JSON format uses the same structure with camelCase keys.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from ragrig.evaluation.models import GoldenQuestionSet


def load_golden_question_set_from_yaml(path: Path) -> GoldenQuestionSet:
    """Load a golden question set from a YAML file."""
    if not path.exists():
        raise FileNotFoundError(f"Golden question set file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return _parse_golden_document(raw, str(path))


def load_golden_question_set_from_json(path: Path) -> GoldenQuestionSet:
    """Load a golden question set from a JSON file."""
    if not path.exists():
        raise FileNotFoundError(f"Golden question set file not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _parse_golden_document(raw, str(path))


def load_golden_question_set(path: Path) -> GoldenQuestionSet:
    """Load a golden question set, auto-detecting YAML or JSON format."""
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        return load_golden_question_set_from_yaml(path)
    if suffix == ".json":
        return load_golden_question_set_from_json(path)
    raise ValueError(f"Unsupported golden fixture format: {suffix}. Use .yaml, .yml, or .json")


def _parse_golden_document(raw: dict, source: str) -> GoldenQuestionSet:
    """Parse a loaded golden document dict into a GoldenQuestionSet."""
    if not isinstance(raw, dict) or "golden_question_set" not in raw:
        raise ValueError(
            f"Invalid golden fixture at {source}: expected a top-level 'golden_question_set' key"
        )
    gqs_raw = raw["golden_question_set"]
    if not isinstance(gqs_raw, dict):
        raise ValueError(
            f"Invalid golden fixture at {source}: 'golden_question_set' must be a mapping"
        )
    return GoldenQuestionSet.model_validate(gqs_raw)
