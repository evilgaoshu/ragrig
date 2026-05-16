from __future__ import annotations

from pydantic import Field

from ragrig.plugins.manifest import PluginConfigModel, PluginManifest
from ragrig.plugins.types import Capability, PluginStatus, PluginTier, PluginType


class LocalSourceConfig(PluginConfigModel):
    root_path: str
    include_patterns: list[str] = []
    exclude_patterns: list[str] = []
    max_file_size_bytes: int = Field(default=10 * 1024 * 1024, gt=0)


class CharacterWindowChunkerConfig(PluginConfigModel):
    chunk_size: int = Field(default=500, gt=0)
    chunk_overlap: int = Field(default=50, ge=0)


class DeterministicEmbeddingConfig(PluginConfigModel):
    dimensions: int = Field(default=8, gt=0)


class JsonlSinkConfig(PluginConfigModel):
    output_path: str


class FilesystemSinkConfig(PluginConfigModel):
    base_path: str
    format: str = "jsonl"
    overwrite: bool = True
    dry_run: bool = False


def builtin_manifests() -> list[PluginManifest]:
    return [
        PluginManifest(
            plugin_id="source.local",
            display_name="Local Filesystem Source",
            description="Reads local files from a configured root path without network access.",
            plugin_type=PluginType.SOURCE,
            family="local",
            version="0.1.0",
            owner="ragrig-core",
            tier=PluginTier.BUILTIN,
            status=PluginStatus.READY,
            capabilities=(Capability.READ,),
            docs_reference="README.md",
            config_model=LocalSourceConfig,
            example_config={"root_path": "/tmp/docs"},
        ),
        PluginManifest(
            plugin_id="parser.markdown",
            display_name="Markdown Parser",
            description="Parses Markdown files into deterministic extracted text.",
            plugin_type=PluginType.PARSER,
            family="markdown",
            version="0.1.0",
            owner="ragrig-core",
            tier=PluginTier.BUILTIN,
            status=PluginStatus.READY,
            capabilities=(Capability.READ, Capability.PARSE_TEXT),
            docs_reference="README.md",
        ),
        PluginManifest(
            plugin_id="parser.text",
            display_name="Plain Text Parser",
            description="Parses UTF-8 text files into deterministic extracted text.",
            plugin_type=PluginType.PARSER,
            family="text",
            version="0.1.0",
            owner="ragrig-core",
            tier=PluginTier.BUILTIN,
            status=PluginStatus.READY,
            capabilities=(Capability.READ, Capability.PARSE_TEXT),
            docs_reference="README.md",
        ),
        PluginManifest(
            plugin_id="chunker.character_window",
            display_name="Character Window Chunker",
            description="Splits extracted text into deterministic overlapping character windows.",
            plugin_type=PluginType.CHUNKER,
            family="character_window",
            version="0.1.0",
            owner="ragrig-core",
            tier=PluginTier.BUILTIN,
            status=PluginStatus.READY,
            capabilities=(Capability.WRITE, Capability.CHUNK_TEXT),
            docs_reference="README.md",
            config_model=CharacterWindowChunkerConfig,
            example_config={"chunk_size": 500, "chunk_overlap": 50},
        ),
        PluginManifest(
            plugin_id="embedding.deterministic_local",
            display_name="Deterministic Local Embedding",
            description="Generates reproducible local embeddings for tests and local development.",
            plugin_type=PluginType.EMBEDDING,
            family="deterministic_local",
            version="0.1.0",
            owner="ragrig-core",
            tier=PluginTier.BUILTIN,
            status=PluginStatus.READY,
            capabilities=(Capability.WRITE, Capability.EMBED_TEXT),
            docs_reference="README.md",
            config_model=DeterministicEmbeddingConfig,
            example_config={"dimensions": 8},
        ),
        PluginManifest(
            plugin_id="vector.pgvector",
            display_name="pgvector Backend",
            description="Stores and queries vectors in Postgres using pgvector.",
            plugin_type=PluginType.VECTOR,
            family="pgvector",
            version="0.1.0",
            owner="ragrig-core",
            tier=PluginTier.BUILTIN,
            status=PluginStatus.READY,
            capabilities=(
                Capability.READ,
                Capability.WRITE,
                Capability.VECTOR_READ,
                Capability.VECTOR_WRITE,
            ),
            docs_reference="README.md",
        ),
        PluginManifest(
            plugin_id="sink.jsonl",
            display_name="JSONL Sink",
            description="Writes portable JSONL output for debugging and export.",
            plugin_type=PluginType.SINK,
            family="jsonl",
            version="0.1.0",
            owner="ragrig-core",
            tier=PluginTier.BUILTIN,
            status=PluginStatus.READY,
            capabilities=(Capability.WRITE,),
            docs_reference="README.md",
            config_model=JsonlSinkConfig,
            example_config={"output_path": "/tmp/ragrig-export.jsonl"},
        ),
        PluginManifest(
            plugin_id="sink.filesystem",
            display_name="Filesystem Sink",
            description=(
                "Exports knowledge-base chunks and documents to a local directory as "
                "JSONL, Markdown, or both. Works with any mounted path including NFS shares."
            ),
            plugin_type=PluginType.SINK,
            family="filesystem",
            version="0.1.0",
            owner="ragrig-core",
            tier=PluginTier.BUILTIN,
            status=PluginStatus.READY,
            capabilities=(Capability.WRITE,),
            docs_reference="README.md",
            config_model=FilesystemSinkConfig,
            example_config={
                "base_path": "/mnt/exports",
                "format": "both",
                "overwrite": True,
                "dry_run": False,
            },
        ),
        PluginManifest(
            plugin_id="preview.markdown",
            display_name="Markdown Preview",
            description="Provides a lightweight Markdown preview and draft editing surface.",
            plugin_type=PluginType.PREVIEW,
            family="markdown",
            version="0.1.0",
            owner="ragrig-core",
            tier=PluginTier.BUILTIN,
            status=PluginStatus.READY,
            capabilities=(Capability.PREVIEW_READ, Capability.PREVIEW_WRITE),
            docs_reference="README.md",
        ),
    ]
