from pydantic import Field

from ragrig.settings.base import RagrigBaseSettings


class AppSettings(RagrigBaseSettings):
    app_name: str = "ragrig"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000


class RuntimePolicySettings(RagrigBaseSettings):
    ragrig_pii_redaction_enabled: bool = Field(
        default=False,
        description="Redact detected PII patterns from chunk text before storing.",
    )
    ragrig_allow_fake_reranker: bool = Field(
        default=False,
        description=(
            "Allow the deterministic fake reranker fallback in production. "
            "Use only for demos or explicitly accepted degraded environments."
        ),
    )


class CorsSettings(RagrigBaseSettings):
    ragrig_cors_origins: str = Field(
        default="",
        description=(
            "Comma-separated allowed CORS origins for separate frontend deployments. "
            "Empty disables CORS middleware."
        ),
    )
    ragrig_cors_allow_origin_regex: str = Field(
        default="",
        description="Optional CORS allowed-origin regex.",
    )
    ragrig_cors_allow_credentials: bool = Field(
        default=False,
        description="Allow browsers to include credentials on configured CORS origins.",
    )


class PathPolicySettings(RagrigBaseSettings):
    ragrig_evaluation_extra_allowed_roots: str = Field(
        default="",
        description=(
            "Comma-separated extra filesystem roots accepted by evaluation APIs. "
            "Default evaluation roots are evaluation_runs, evaluation_baselines, and tests."
        ),
    )
    ragrig_ingestion_extra_allowed_roots: str = Field(
        default="",
        description=(
            "Comma-separated extra filesystem roots accepted by local ingestion APIs. "
            "Default roots are data, docs, and uploads."
        ),
    )
