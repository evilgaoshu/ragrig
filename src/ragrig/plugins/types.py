from __future__ import annotations

from enum import StrEnum


class PluginType(StrEnum):
    SOURCE = "source"
    PARSER = "parser"
    CHUNKER = "chunker"
    EMBEDDING = "embedding"
    MODEL = "model"
    RERANKER = "reranker"
    VECTOR = "vector"
    SINK = "sink"
    PREVIEW = "preview"
    OCR = "ocr"


class PluginTier(StrEnum):
    BUILTIN = "builtin"
    OFFICIAL = "official"
    COMMUNITY = "community"


class PluginStatus(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class Capability(StrEnum):
    READ = "read"
    WRITE = "write"
    PARSE_TEXT = "parse_text"
    CHUNK_TEXT = "chunk_text"
    EMBED_TEXT = "embed_text"
    GENERATE_TEXT = "generate_text"
    RERANK = "rerank"
    VECTOR_READ = "vector_read"
    VECTOR_WRITE = "vector_write"
    PREVIEW_READ = "preview_read"
    PREVIEW_WRITE = "preview_write"
    OCR_TEXT = "ocr_text"
    INCREMENTAL_SYNC = "incremental_sync"
    DELETE_DETECTION = "delete_detection"
    PERMISSION_MAPPING = "permission_mapping"


ALLOWED_CAPABILITIES: dict[PluginType, set[Capability]] = {
    PluginType.SOURCE: {
        Capability.READ,
        Capability.INCREMENTAL_SYNC,
        Capability.DELETE_DETECTION,
        Capability.PERMISSION_MAPPING,
    },
    PluginType.PARSER: {Capability.READ, Capability.PARSE_TEXT},
    PluginType.CHUNKER: {Capability.WRITE, Capability.CHUNK_TEXT},
    PluginType.EMBEDDING: {Capability.WRITE, Capability.EMBED_TEXT},
    PluginType.MODEL: {
        Capability.GENERATE_TEXT,
        Capability.EMBED_TEXT,
        Capability.RERANK,
    },
    PluginType.RERANKER: {Capability.RERANK},
    PluginType.VECTOR: {
        Capability.READ,
        Capability.WRITE,
        Capability.VECTOR_READ,
        Capability.VECTOR_WRITE,
    },
    PluginType.SINK: {Capability.WRITE},
    PluginType.PREVIEW: {Capability.PREVIEW_READ, Capability.PREVIEW_WRITE},
    PluginType.OCR: {Capability.READ, Capability.OCR_TEXT},
}
