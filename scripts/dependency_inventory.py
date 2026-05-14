from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"

OPTIONAL_GROUP_DETAILS = {
    "cloud-aws": {
        "sdk_examples": ["boto3"],
        "category": "official cloud SDKs",
        "rule": "Use the official AWS SDK behind explicit Bedrock and AWS storage plugins.",
    },
    "cloud-cohere": {
        "sdk_examples": ["cohere"],
        "category": "official cloud SDKs",
        "rule": "Use only behind explicit Cohere model and rerank plugins.",
    },
    "cloud-google": {
        "sdk_examples": ["google-genai", "google-cloud-aiplatform"],
        "category": "official cloud SDKs",
        "rule": "Use official Gemini and Vertex SDKs behind explicit cloud model plugins.",
    },
    "cloud-jina": {
        "sdk_examples": ["Jina HTTP API"],
        "category": "cloud embedding / rerank API",
        "rule": "Prefer official SDKs when available; otherwise isolate HTTP clients in plugins.",
    },
    "cloud-openai": {
        "sdk_examples": ["openai"],
        "category": "official cloud SDKs",
        "rule": "Use the official OpenAI SDK behind explicit cloud model plugins.",
    },
    "cloud-voyage": {
        "sdk_examples": ["voyageai"],
        "category": "official cloud SDKs",
        "rule": "Use only behind explicit Voyage embedding and rerank plugins.",
    },
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
    "s3": {
        "sdk_examples": ["boto3", "S3-compatible API"],
        "category": "object storage SDKs",
        "rule": "Keep S3-compatible storage connectors optional and plugin-scoped.",
    },
    "parquet": {
        "sdk_examples": ["pyarrow"],
        "category": "analytics export SDKs",
        "rule": "Install only for structured export and lakehouse connector work.",
    },
    "fileshare": {
        "sdk_examples": ["httpx", "paramiko", "smbprotocol"],
        "category": "file share connector SDKs",
        "rule": "Keep network filesystem clients optional and isolate credential handling.",
    },
}

DEFAULT_OPTIONAL_GROUP_DETAIL = {
    "sdk_examples": ["plugin-scoped SDKs"],
    "category": "optional plugin SDKs",
    "rule": "Keep optional dependencies out of core imports and document network/auth impact.",
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
            category=OPTIONAL_GROUP_DETAILS.get(group, DEFAULT_OPTIONAL_GROUP_DETAIL)["category"],
            examples=", ".join(
                f"`{item}`"
                for item in OPTIONAL_GROUP_DETAILS.get(group, DEFAULT_OPTIONAL_GROUP_DETAIL)[
                    "sdk_examples"
                ]
            ),
            rule=OPTIONAL_GROUP_DETAILS.get(group, DEFAULT_OPTIONAL_GROUP_DETAIL)["rule"],
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

Optional extras keep cloud, storage, parsing, and heavy ML SDKs behind explicit
install boundaries instead of pulling them into the default local-first environment.

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
