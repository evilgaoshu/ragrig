"""GitHub source connector configuration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GithubSourceConfig:
    repo: str
    token: str = ""
    branch: str = "main"
    path: str = ""
    include_patterns: list[str] = field(default_factory=lambda: ["*.md", "*.txt", "*.rst", "*.py"])
    exclude_patterns: list[str] = field(default_factory=list)
    max_file_size_mb: float = 10.0
    page_size: int = 100

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "GithubSourceConfig":
        from ragrig.plugins.sources.github.errors import GithubConfigError

        repo = str(raw.get("repo") or "").strip()
        if not repo:
            raise GithubConfigError("repo is required (owner/repo format)")
        if "/" not in repo:
            raise GithubConfigError("repo must be in owner/repo format")

        include_patterns = raw.get("include_patterns")
        if include_patterns is None:
            include_patterns = ["*.md", "*.txt", "*.rst", "*.py"]
        elif not isinstance(include_patterns, list):
            include_patterns = list(include_patterns)  # type: ignore[arg-type]

        exclude_patterns = raw.get("exclude_patterns")
        if exclude_patterns is None:
            exclude_patterns = []
        elif not isinstance(exclude_patterns, list):
            exclude_patterns = list(exclude_patterns)  # type: ignore[arg-type]

        return cls(
            repo=repo,
            token=str(raw.get("token") or ""),
            branch=str(raw.get("branch") or "main"),
            path=str(raw.get("path") or ""),
            include_patterns=list(include_patterns),
            exclude_patterns=list(exclude_patterns),
            max_file_size_mb=float(raw.get("max_file_size_mb") or 10.0),
            page_size=int(raw.get("page_size") or 100),
        )
