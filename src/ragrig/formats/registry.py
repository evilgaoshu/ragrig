from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ragrig.formats.model import FormatStatus, SupportedFormat

_BUILTIN_FORMATS_PATH = Path(__file__).with_name("supported_formats.yaml")


def _load_builtin_formats() -> list[dict[str, Any]]:
    if not _BUILTIN_FORMATS_PATH.exists():
        return _DEFAULT_FORMATS
    raw = yaml.safe_load(_BUILTIN_FORMATS_PATH.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and "formats" in raw:
        return raw["formats"]
    return _DEFAULT_FORMATS


_DEFAULT_FORMATS: list[dict[str, Any]] = [
    {
        "extension": ".md",
        "mime_type": "text/markdown",
        "display_name": "Markdown (.md)",
        "parser_id": "parser.markdown",
        "status": "supported",
        "max_file_size_mb": 50,
        "capabilities": ["parse", "chunk", "embed"],
        "limitations": None,
        "docs_reference": "docs/specs/ragrig-processing-profile-spec.md",
    },
    {
        "extension": ".markdown",
        "mime_type": "text/markdown",
        "display_name": "Markdown (.markdown)",
        "parser_id": "parser.markdown",
        "status": "supported",
        "max_file_size_mb": 50,
        "capabilities": ["parse", "chunk", "embed"],
        "limitations": None,
        "docs_reference": "docs/specs/ragrig-processing-profile-spec.md",
    },
    {
        "extension": ".txt",
        "mime_type": "text/plain",
        "display_name": "Plain Text (.txt)",
        "parser_id": "parser.text",
        "status": "supported",
        "max_file_size_mb": 50,
        "capabilities": ["parse", "chunk", "embed"],
        "limitations": None,
        "docs_reference": "docs/specs/ragrig-processing-profile-spec.md",
    },
    {
        "extension": ".text",
        "mime_type": "text/plain",
        "display_name": "Plain Text (.text)",
        "parser_id": "parser.text",
        "status": "supported",
        "max_file_size_mb": 50,
        "capabilities": ["parse", "chunk", "embed"],
        "limitations": None,
        "docs_reference": "docs/specs/ragrig-processing-profile-spec.md",
    },
    {
        "extension": ".rst",
        "mime_type": "text/x-rst",
        "display_name": "reStructuredText (.rst)",
        "parser_id": "parser.text",
        "status": "preview",
        "max_file_size_mb": 50,
        "capabilities": ["parse"],
        "limitations": "Parsed as plain text, no RST structure awareness.",
        "fallback_policy": "parse_as_plaintext",
        "docs_reference": "docs/specs/ragrig-processing-profile-spec.md",
    },
    {
        "extension": ".csv",
        "mime_type": "text/csv",
        "display_name": "CSV (.csv)",
        "parser_id": "parser.csv",
        "status": "preview",
        "max_file_size_mb": 50,
        "capabilities": ["parse"],
        "limitations": "Parsed as plain text, no table awareness.",
        "fallback_policy": "parse_as_plaintext",
        "docs_reference": "docs/specs/ragrig-processing-profile-spec.md",
    },
    {
        "extension": ".json",
        "mime_type": "application/json",
        "display_name": "JSON (.json)",
        "parser_id": "parser.text",
        "status": "preview",
        "max_file_size_mb": 50,
        "capabilities": ["parse"],
        "limitations": "Parsed as plain text.",
        "fallback_policy": "parse_as_plaintext",
        "docs_reference": "docs/specs/ragrig-processing-profile-spec.md",
    },
    {
        "extension": ".xml",
        "mime_type": "application/xml",
        "display_name": "XML (.xml)",
        "parser_id": "parser.text",
        "status": "preview",
        "max_file_size_mb": 50,
        "capabilities": ["parse"],
        "limitations": "Parsed as plain text.",
        "fallback_policy": "parse_as_plaintext",
        "docs_reference": "docs/specs/ragrig-processing-profile-spec.md",
    },
    {
        "extension": ".html",
        "mime_type": "text/html",
        "display_name": "HTML (.html)",
        "parser_id": "parser.html",
        "status": "preview",
        "max_file_size_mb": 50,
        "capabilities": ["parse"],
        "limitations": "Parsed as plain text, tags stripped.",
        "fallback_policy": "strip_tags_then_plaintext",
        "docs_reference": "docs/specs/ragrig-processing-profile-spec.md",
    },
    {
        "extension": ".pdf",
        "mime_type": "application/pdf",
        "display_name": "PDF (.pdf)",
        "parser_id": "parser.advanced_documents",
        "status": "preview",
        "max_file_size_mb": 50,
        "capabilities": ["parse"],
        "limitations": (
            "Advanced document parsing in preview. Requires optional doc-parsers extras."
        ),
        "fallback_policy": "parse_as_plaintext",
        "docs_reference": "docs/specs/ragrig-advanced-parser-corpus-spec.md",
    },
    {
        "extension": ".docx",
        "mime_type": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        "display_name": "Microsoft Word (.docx)",
        "parser_id": "parser.advanced_documents",
        "status": "preview",
        "max_file_size_mb": 50,
        "capabilities": ["parse"],
        "limitations": (
            "Advanced document parsing in preview. Requires optional doc-parsers extras."
        ),
        "fallback_policy": "parse_as_plaintext",
        "docs_reference": "docs/specs/ragrig-advanced-parser-corpus-spec.md",
    },
    {
        "extension": ".xlsx",
        "mime_type": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "display_name": "Microsoft Excel (.xlsx)",
        "parser_id": "parser.advanced_documents",
        "status": "preview",
        "max_file_size_mb": 50,
        "capabilities": ["parse"],
        "limitations": (
            "Advanced document parsing in preview. Requires optional doc-parsers extras."
        ),
        "fallback_policy": "parse_as_plaintext",
        "docs_reference": "docs/specs/ragrig-advanced-parser-corpus-spec.md",
    },
    {
        "extension": ".pptx",
        "mime_type": ("application/vnd.openxmlformats-officedocument.presentationml.presentation"),
        "display_name": "Microsoft PowerPoint (.pptx)",
        "parser_id": "parser.advanced_documents",
        "status": "preview",
        "max_file_size_mb": 50,
        "capabilities": ["parse"],
        "limitations": (
            "Advanced document parsing in preview. Requires optional doc-parsers extras."
        ),
        "fallback_policy": "parse_as_plaintext",
        "docs_reference": "docs/specs/ragrig-advanced-parser-corpus-spec.md",
    },
]


class SupportedFormatRegistry:
    """A registry of file formats that RAGRig knows about.

    Built from a YAML fixture file (src/ragrig/formats/supported_formats.yaml).
    If the fixture file is missing, uses the hardcoded defaults.
    """

    def __init__(self, formats: list[SupportedFormat] | None = None) -> None:
        if formats is not None:
            self._formats: dict[str, SupportedFormat] = {fmt.extension: fmt for fmt in formats}
        else:
            raw = _load_builtin_formats()
            self._formats = {}
            for entry in raw:
                fmt = SupportedFormat(
                    extension=entry["extension"],
                    mime_type=entry["mime_type"],
                    display_name=entry["display_name"],
                    parser_id=entry["parser_id"],
                    default_profile_id=entry.get("default_profile_id"),
                    status=FormatStatus(entry["status"]),
                    max_file_size_mb=entry.get("max_file_size_mb", 50),
                    capabilities=entry.get("capabilities", []),
                    limitations=entry.get("limitations"),
                    fallback_policy=entry.get("fallback_policy"),
                    docs_reference=entry.get("docs_reference"),
                    metadata=entry.get("metadata", {}),
                )
                self._formats[fmt.extension] = fmt

    def list(
        self,
        *,
        status: FormatStatus | None = None,
        extension: str | None = None,
    ) -> list[SupportedFormat]:
        formats = list(self._formats.values())
        if status is not None:
            formats = [fmt for fmt in formats if fmt.status == status]
        if extension is not None:
            ext = extension.lower()
            if not ext.startswith("."):
                ext = f".{ext}"
            formats = [fmt for fmt in formats if fmt.extension == ext]
        return sorted(
            formats,
            key=lambda f: (
                {"supported": 0, "preview": 1, "planned": 2}[f.status.value],
                f.extension,
            ),
        )

    def lookup(self, extension: str) -> SupportedFormat | None:
        ext = extension.lower()
        if not ext.startswith("."):
            ext = f".{ext}"
        return self._formats.get(ext)

    def check(self, extension: str) -> dict[str, object]:
        ext = extension.lower()
        if not ext.startswith("."):
            ext = f".{ext}"
        fmt = self._formats.get(ext)
        if fmt is None:
            return {
                "extension": ext,
                "supported": False,
                "status": "unsupported",
                "parser_id": None,
                "message": (
                    f"File format {ext} is not supported. "
                    f"Supported formats: {', '.join(sorted(self._formats.keys()))}."
                ),
            }
        return {
            "extension": fmt.extension,
            "supported": True,
            "status": fmt.status.value,
            "parser_id": fmt.parser_id,
            "fallback_policy": fmt.fallback_policy,
            "display_name": fmt.display_name,
            "mime_type": fmt.mime_type,
            "capabilities": fmt.capabilities,
            "limitations": fmt.limitations,
            "message": _status_message(fmt),
        }


def _status_message(fmt: SupportedFormat) -> str:
    if fmt.status == FormatStatus.SUPPORTED:
        return f"{fmt.display_name} is fully supported."
    if fmt.status == FormatStatus.PREVIEW:
        lim = fmt.limitations or "Preview status — may have limitations."
        return f"{fmt.display_name} is in preview. {lim}"
    # FormatStatus.PLANNED
    lim = fmt.limitations or "Planned for future release."
    return f"{fmt.display_name} support is planned. {lim}"


_REGISTRY: SupportedFormatRegistry | None = None


def get_format_registry() -> SupportedFormatRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = SupportedFormatRegistry()
    return _REGISTRY
