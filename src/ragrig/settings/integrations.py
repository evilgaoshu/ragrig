from pydantic import Field

from ragrig.settings.base import RagrigBaseSettings


class EmailSettings(RagrigBaseSettings):
    ragrig_smtp_enabled: bool = Field(default=False, description="Enable SMTP email delivery.")
    ragrig_smtp_host: str = Field(default="localhost", description="SMTP server host.")
    ragrig_smtp_port: int = Field(default=587, description="SMTP server port.")
    ragrig_smtp_use_tls: bool = Field(default=True, description="Use STARTTLS.")
    ragrig_smtp_username: str = Field(default="", description="SMTP username.")
    ragrig_smtp_password: str = Field(default="", description="SMTP password.")
    ragrig_smtp_from: str = Field(
        default="noreply@ragrig.local",
        description="From address for outbound emails.",
    )
    ragrig_app_base_url: str = Field(
        default="http://localhost:8000",
        description="Public base URL, used to build invitation links.",
    )


class WebhookSettings(RagrigBaseSettings):
    ragrig_webhook_url: str = Field(
        default="",
        description=(
            "Outbound webhook URL. Receives JSON POST on pipeline failure/completion. "
            "Supports Slack Incoming Webhook, generic HTTP endpoints."
        ),
    )
    ragrig_webhook_secret: str = Field(
        default="",
        description="Optional HMAC-SHA256 signing secret for outbound webhooks.",
    )
    ragrig_webhook_on_failure: bool = Field(
        default=True, description="Fire webhook on pipeline/task failure."
    )
    ragrig_webhook_on_completion: bool = Field(
        default=False, description="Fire webhook on pipeline/task completion."
    )


class TaskQueueSettings(RagrigBaseSettings):
    ragrig_task_backend: str = Field(
        default="threadpool",
        description="Task execution backend: 'threadpool' (default) or 'arq' (Redis-backed).",
    )
    ragrig_redis_url: str = Field(
        default="redis://localhost:6379",
        description="Redis URL for the ARQ task queue backend.",
    )
    ragrig_task_queue_max_jobs: int = Field(
        default=10,
        description="Max concurrent jobs in the ARQ worker.",
    )
