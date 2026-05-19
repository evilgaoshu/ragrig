"""GitHub source connector.

Ingests files from a GitHub repository via the GitHub REST API.

Configuration shape::

    {
        "repo": "owner/repo",
        "token": "env:GITHUB_TOKEN",
        "branch": "main",
        "path": "",
        "include_patterns": ["*.md", "*.txt", "*.rst", "*.py"],
        "exclude_patterns": [],
        "max_file_size_mb": 10.0,
        "page_size": 100,
    }
"""

from ragrig.plugins.sources.github.config import GithubSourceConfig
from ragrig.plugins.sources.github.connector import ingest_github_source
from ragrig.plugins.sources.github.errors import (
    GithubAuthError,
    GithubConfigError,
    GithubSourceError,
)

__all__ = [
    "GithubAuthError",
    "GithubConfigError",
    "GithubSourceConfig",
    "GithubSourceError",
    "ingest_github_source",
]
