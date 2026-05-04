from __future__ import annotations

import ast
from pathlib import Path

from ragrig import __version__
from ragrig.db import SessionLocal, create_db_engine, get_db_engine, get_db_session
from ragrig.db.models import Base, Chunk, Document, DocumentVersion, Embedding, KnowledgeBase
from ragrig.embeddings import DeterministicEmbeddingProvider
from ragrig.health import create_database_check
from ragrig.indexing import IndexingReport, index_knowledge_base
from ragrig.ingestion import IngestionReport, ingest_local_directory
from ragrig.parsers import MarkdownParser, ParseResult, PlainTextParser
from ragrig.providers import ProviderRegistry, get_provider_registry
from ragrig.repositories import (
    create_pipeline_run,
    create_pipeline_run_item,
    get_document_by_uri,
    get_knowledge_base_by_name,
    get_next_version_number,
    get_or_create_document,
    get_or_create_knowledge_base,
    get_or_create_source,
    list_latest_document_versions,
)
from ragrig.retrieval import search_knowledge_base

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_PATHS = [
    REPO_ROOT / "src/ragrig/db",
    REPO_ROOT / "src/ragrig/repositories",
    REPO_ROOT / "src/ragrig/ingestion",
    REPO_ROOT / "src/ragrig/parsers",
    REPO_ROOT / "src/ragrig/chunkers",
    REPO_ROOT / "src/ragrig/embeddings",
    REPO_ROOT / "src/ragrig/indexing",
    REPO_ROOT / "src/ragrig/providers",
    REPO_ROOT / "src/ragrig/retrieval.py",
    REPO_ROOT / "src/ragrig/config.py",
    REPO_ROOT / "src/ragrig/health.py",
    REPO_ROOT / "src/ragrig/__init__.py",
]
OPTIONAL_IMPORT_ROOTS = {
    "azure",
    "boto3",
    "cohere",
    "docling",
    "FlagEmbedding",
    "google",
    "googleapiclient",
    "minio",
    "msgraph",
    "ollama",
    "openai",
    "opensearchpy",
    "paddleocr",
    "paramiko",
    "pymilvus",
    "qdrant_client",
    "redis",
    "sentence_transformers",
    "smbprotocol",
    "snowflake",
    "torch",
    "transformers",
    "unstructured",
    "voyageai",
    "weaviate",
}


def _iter_core_files() -> list[Path]:
    files: list[Path] = []
    for path in CORE_PATHS:
        if path.is_dir():
            files.extend(sorted(path.rglob("*.py")))
        else:
            files.append(path)
    return files


def _top_level_import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_core_package_exports_are_available_without_optional_dependencies() -> None:
    assert __version__ == "0.1.0"
    assert Base is not None
    assert KnowledgeBase is not None
    assert Document is not None
    assert DocumentVersion is not None
    assert Chunk is not None
    assert Embedding is not None
    assert SessionLocal is not None
    assert create_db_engine is not None
    assert get_db_engine is not None
    assert get_db_session is not None
    assert get_knowledge_base_by_name is not None
    assert get_or_create_knowledge_base is not None
    assert get_or_create_source is not None
    assert get_or_create_document is not None
    assert get_document_by_uri is not None
    assert get_next_version_number is not None
    assert list_latest_document_versions is not None
    assert create_pipeline_run is not None
    assert create_pipeline_run_item is not None
    assert ingest_local_directory is not None
    assert IngestionReport is not None
    assert MarkdownParser is not None
    assert PlainTextParser is not None
    assert ParseResult is not None
    assert DeterministicEmbeddingProvider is not None
    assert ProviderRegistry is not None
    assert get_provider_registry is not None
    assert index_knowledge_base is not None
    assert IndexingReport is not None
    assert search_knowledge_base is not None
    assert create_database_check is not None


def test_core_modules_do_not_import_optional_sdks_at_top_level() -> None:
    offenders: dict[str, list[str]] = {}

    for path in _iter_core_files():
        roots = sorted(_top_level_import_roots(path) & OPTIONAL_IMPORT_ROOTS)
        if roots:
            offenders[str(path.relative_to(REPO_ROOT))] = roots

    assert offenders == {}
