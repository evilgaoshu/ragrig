from pydantic import Field

from ragrig.settings.base import RagrigBaseSettings


class RateLimitSettings(RagrigBaseSettings):
    ragrig_rate_limit_enabled: bool = Field(
        default=False,
        description="Enable per-workspace in-process rate limiting.",
    )
    ragrig_rate_limit_search_rpm: int = Field(
        default=60,
        description="Max search/answer requests per minute per workspace.",
    )
    ragrig_rate_limit_ingest_rpm: int = Field(
        default=20,
        description="Max ingest/upload requests per minute per workspace.",
    )
    ragrig_rate_limit_burst_factor: float = Field(
        default=1.5,
        description="Burst multiplier applied on top of the RPM limit.",
    )


class RetentionSettings(RagrigBaseSettings):
    ragrig_audit_retention_days: int = Field(
        default=0,
        description=(
            "Global audit-event retention in days. 0 = keep forever. "
            "Applied when POST /admin/retention/run is called."
        ),
    )
