from pydantic import Field

from ragrig.settings.base import RagrigBaseSettings


class ObservabilitySettings(RagrigBaseSettings):
    ragrig_metrics_enabled: bool = Field(
        default=True,
        description="Expose Prometheus /metrics endpoint.",
    )
    ragrig_metrics_workspace_labels_enabled: bool = Field(
        default=False,
        description=(
            "Also emit low-cardinality workspace-hash labels on selected business metrics. "
            "Disabled by default to keep Prometheus cardinality predictable."
        ),
    )
    ragrig_otel_enabled: bool = Field(
        default=False,
        description="Enable OpenTelemetry tracing and structured log export.",
    )
    ragrig_otel_endpoint: str = Field(
        default="http://localhost:4318",
        description="OTLP HTTP collector endpoint (e.g. http://otel-collector:4318).",
    )
    ragrig_otel_service_name: str = Field(
        default="ragrig",
        description="Service name reported to the OTel collector.",
    )
    ragrig_log_format: str = Field(
        default="plain",
        description="Log format: 'plain'/'text' (human-readable) or 'json' (structured).",
    )
    ragrig_log_level: str = Field(
        default="INFO",
        description="Root logging level, e.g. DEBUG, INFO, WARNING, ERROR.",
    )
    ragrig_log_file: str = Field(
        default="",
        description="Optional file path for rotating application logs. Empty disables file logs.",
    )
    ragrig_log_max_bytes: int = Field(
        default=10 * 1024 * 1024,
        description="Maximum bytes per rotating log file before rollover.",
    )
    ragrig_log_backup_count: int = Field(
        default=5,
        description="Number of rotated log files to keep when RAGRIG_LOG_FILE is set.",
    )
