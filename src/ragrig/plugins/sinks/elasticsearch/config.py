"""Configuration model for the Elasticsearch sink."""

from __future__ import annotations

from pydantic import Field

from ragrig.plugins.manifest import PluginConfigModel


class ElasticsearchSinkConfig(PluginConfigModel):
    """Configuration for exporting knowledge-base chunks to Elasticsearch / OpenSearch."""

    url: str = Field(
        min_length=1, description="Elasticsearch cluster URL, e.g. http://localhost:9200."
    )
    index: str = Field(min_length=1, description="Name of the Elasticsearch index to write into.")

    # Auth — secrets must use 'env:VAR' references
    api_key: str = Field(
        default="",
        description="Elasticsearch API key (use 'env:VAR' reference).",
    )
    username: str = Field(default="", description="Basic-auth username.")
    password: str = Field(
        default="",
        description="Basic-auth password (use 'env:VAR' reference).",
    )
    ca_cert_path: str = Field(
        default="",
        description="Path to a CA certificate file for TLS verification.",
    )

    pipeline_name: str = Field(
        default="",
        description="Optional Elasticsearch ingest pipeline to apply during indexing.",
    )
    dry_run: bool = Field(
        default=False,
        description="Plan the export without writing any documents to Elasticsearch.",
    )
    batch_size: int = Field(
        default=500,
        gt=0,
        description="Number of documents to send in each bulk-index request.",
    )


__all__ = ["ElasticsearchSinkConfig"]
