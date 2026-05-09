from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class FormatStatus(str, Enum):
    SUPPORTED = "supported"
    PREVIEW = "preview"
    PLANNED = "planned"


@dataclass(frozen=True)
class SupportedFormat:
    """A file format that RAGRig knows how to process."""

    extension: str
    """File extension including dot, e.g. '.docx', '.pdf', '.md'. Must be lowercase."""

    mime_type: str
    """Standard MIME type."""

    display_name: str
    """Human-readable format name, e.g. 'Microsoft Word (.docx)'."""

    parser_id: str
    """Plugin ID of the parser that handles this format, e.g. 'parser.markdown'."""

    default_profile_id: str | None = None
    """Default ProcessingProfile ID for this format."""

    status: FormatStatus = FormatStatus.SUPPORTED
    """Current implementation status."""

    max_file_size_mb: int = 50
    """Maximum recommended file size in megabytes."""

    capabilities: list[str] = field(default_factory=list)
    """What this format supports: ['parse', 'chunk', 'embed']."""

    limitations: str | None = None
    """Known limitations, displayed to users."""

    fallback_policy: str | None = None
    """What happens when this preview format fails or degrades, e.g. 'parse_as_plaintext'."""

    docs_reference: str | None = None
    """Link to documentation for this format's processing pipeline."""

    metadata: dict[str, Any] = field(default_factory=dict)
