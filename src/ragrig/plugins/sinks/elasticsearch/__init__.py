"""Elasticsearch sink plugin for RAGRig."""

from ragrig.plugins.sinks.elasticsearch.config import ElasticsearchSinkConfig
from ragrig.plugins.sinks.elasticsearch.connector import (
    ElasticsearchExportReport,
    export_to_elasticsearch,
)
from ragrig.plugins.sinks.elasticsearch.errors import (
    ElasticsearchAuthError,
    ElasticsearchConfigError,
    ElasticsearchSinkError,
)

__all__ = [
    "ElasticsearchAuthError",
    "ElasticsearchConfigError",
    "ElasticsearchExportReport",
    "ElasticsearchSinkConfig",
    "ElasticsearchSinkError",
    "export_to_elasticsearch",
]
