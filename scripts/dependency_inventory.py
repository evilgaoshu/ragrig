from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"

OPTIONAL_GROUP_DETAILS = {
    "local-ml": {
        "sdk_examples": ["ollama", "FlagEmbedding", "sentence-transformers", "torch"],
        "category": "local runtime / heavy ML",
        "rule": "Never import from core modules. Install only for plugin or local model work.",
    },
    "cloud-llm": {
        "sdk_examples": ["google-genai", "boto3", "openai", "cohere", "voyageai"],
        "category": "official cloud SDKs",
        "rule": (
            "Cloud providers stay optional and must not affect fresh-clone tests "
            "or local indexing defaults."
        ),
    },
    "cloud-embeddings": {
        "sdk_examples": ["voyageai", "cohere", "openai", "google-genai"],
        "category": "cloud embedding SDKs",
        "rule": (
            "Use only behind explicit plugin extras and document network, auth, and cost metadata."
        ),
    },
    "vectorstores": {
        "sdk_examples": ["qdrant-client", "pymilvus", "weaviate-client", "opensearch-py"],
        "category": "vector database SDKs",
        "rule": (
            "Keep pgvector as the core default. Alternate vector stores must remain "
            "optional plugins."
        ),
    },
    "doc-parsers": {
        "sdk_examples": ["pypdf", "python-docx", "docling", "unstructured", "paddleocr"],
        "category": "document / OCR parsers",
        "rule": (
            "Large parser stacks stay optional because they pull native deps, models, "
            "or extra licenses."
        ),
    },
}


def _base_requirement_name(requirement: str) -> str:
    requirement = requirement.strip()
    for separator in ("<", ">", "=", "!", "~", ";"):
        if separator in requirement:
            requirement = requirement.split(separator, 1)[0]
    return requirement.strip()


def build_inventory_markdown() -> str:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = data["project"]
    dev_dependencies = data["dependency-groups"]["dev"]
    optional_dependencies = data["project"]["optional-dependencies"]

    runtime_rows = "\n".join(
        f"| `{_base_requirement_name(requirement)}` | core runtime | default local-first path |"
        for requirement in project["dependencies"]
    )
    dev_rows = "\n".join(
        "| `{}` | dev / quality gate | test, lint, coverage, or supply-chain tooling |".format(
            _base_requirement_name(requirement)
        )
        for requirement in dev_dependencies
    )
    optional_rows = "\n".join(
        "| `{group}` | {category} | {examples} | {rule} |".format(
            group=group,
            category=OPTIONAL_GROUP_DETAILS[group]["category"],
            examples=", ".join(
                f"`{item}`" for item in OPTIONAL_GROUP_DETAILS[group]["sdk_examples"]
            ),
            rule=OPTIONAL_GROUP_DETAILS[group]["rule"],
        )
        for group in optional_dependencies
    )

    return f"""# RAGRig Dependency Inventory

Generated from `pyproject.toml` by `python -m scripts.dependency_inventory`.

## Core Runtime Dependencies

| Package | Class | Governance |
| --- | --- | --- |
{runtime_rows}

## Development And Quality Gate Dependencies

| Package | Class | Governance |
| --- | --- | --- |
{dev_rows}

## Planned Optional Plugin SDK Groups

The extras are intentionally empty in `pyproject.toml` today. They reserve install
boundaries without pulling real cloud, OCR, or heavy ML SDKs into the default environment.

| Extra group | Category | Preferred SDKs | Governance |
| --- | --- | --- | --- |
{optional_rows}

## Governance Rules

- Core runtime must stay local-first and secret-free for `make test` and `make coverage`.
- Optional SDKs must not be imported from core module top level.
- Heavy ML, cloud, enterprise connector, and document-suite dependencies belong in
  optional extras only.
- Default supply-chain review uses `make licenses`, `make sbom`, and `make audit`.
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the RAGRig dependency inventory document."
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the Markdown output.",
    )
    args = parser.parse_args()

    markdown = build_inventory_markdown()
    if args.output is None:
        print(markdown)
        return

    args.output.write_text(markdown + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
