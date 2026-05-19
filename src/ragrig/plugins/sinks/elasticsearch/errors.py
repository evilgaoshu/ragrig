"""Errors raised by the Elasticsearch sink connector."""

from __future__ import annotations


class ElasticsearchSinkError(RuntimeError):
    """Base error for the Elasticsearch sink."""


class ElasticsearchAuthError(ElasticsearchSinkError):
    """Authentication / authorisation failure with the Elasticsearch cluster."""


class ElasticsearchConfigError(ElasticsearchSinkError):
    """Invalid or missing configuration for the Elasticsearch sink."""


__all__ = [
    "ElasticsearchAuthError",
    "ElasticsearchConfigError",
    "ElasticsearchSinkError",
]
