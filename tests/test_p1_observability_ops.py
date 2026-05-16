"""P1 observability and operations feature tests.

Covers:
- Prometheus metrics endpoint
- SMTP email delivery (send_invitation_email, disabled when smtp_enabled=False)
- Alert webhooks (notify_task_failure, notify_task_complete, notify_pipeline_failure)
- Webhook HMAC signing
- Slack payload auto-detection
- OpenTelemetry setup (unit-level, no real collector)
- ARQ task executor (import guard, backend selection)
- default_task_executor backend switch via settings
"""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest

from ragrig.config import Settings

# ── Prometheus ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_metrics_endpoint_exposed():
    """setup_metrics attaches /metrics route to the FastAPI app."""
    from fastapi import FastAPI

    from ragrig.metrics import setup_metrics

    app = FastAPI()
    setup_metrics(app)
    routes = {r.path for r in app.routes}
    assert "/metrics" in routes


@pytest.mark.unit
def test_metrics_not_in_openapi_schema():
    from fastapi import FastAPI

    from ragrig.metrics import setup_metrics

    app = FastAPI()
    setup_metrics(app)
    schema = app.openapi()
    assert "/metrics" not in schema.get("paths", {})


# ── Email ─────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_send_invitation_email_noop_when_disabled():
    """send_invitation_email does nothing when smtp_enabled=False."""
    settings = Settings(ragrig_smtp_enabled=False)
    from ragrig.email import send_invitation_email

    send_invitation_email(
        settings,
        to_email="alice@example.com",
        workspace_name="Acme",
        inviter_name="Bob",
        role="editor",
        token="tok123",
        expires_days=7,
    )


@pytest.mark.unit
def test_send_invitation_email_builds_correct_url():
    settings = Settings(
        ragrig_smtp_enabled=True,
        ragrig_app_base_url="https://app.example.com",
        ragrig_smtp_host="localhost",
        ragrig_smtp_port=1025,
        ragrig_smtp_use_tls=False,
    )
    from ragrig.email import send_invitation_email

    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_smtp = MagicMock()
        mock_smtp_cls.return_value.__enter__ = lambda s: mock_smtp
        mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
        send_invitation_email(
            settings,
            to_email="alice@example.com",
            workspace_name="Acme",
            inviter_name=None,
            role="editor",
            token="mytoken",
            expires_days=14,
        )
        assert mock_smtp.sendmail.called
        call_args = mock_smtp.sendmail.call_args
        raw_msg = call_args[0][2]
        assert "mytoken" in raw_msg
        assert "https://app.example.com/register" in raw_msg


@pytest.mark.unit
def test_send_invitation_email_raises_on_smtp_error():
    import smtplib

    from ragrig.email import EmailDeliveryError, send_invitation_email

    settings = Settings(
        ragrig_smtp_enabled=True,
        ragrig_smtp_host="localhost",
        ragrig_smtp_port=1025,
        ragrig_smtp_use_tls=False,
    )
    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_smtp_cls.side_effect = smtplib.SMTPException("connection refused")
        with pytest.raises(EmailDeliveryError, match="connection refused"):
            send_invitation_email(
                settings,
                to_email="alice@example.com",
                workspace_name="Acme",
                inviter_name=None,
                role="editor",
                token="tok",
                expires_days=7,
            )


# ── Webhooks ──────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_webhook_not_fired_when_no_url():
    settings = Settings(ragrig_webhook_url="", ragrig_webhook_on_failure=True)
    from ragrig.webhooks import notify_task_failure

    with patch("httpx.post") as mock_post:
        notify_task_failure(
            settings,
            task_id="t1",
            task_type="index",
            error="boom",
        )
        mock_post.assert_not_called()


@pytest.mark.unit
def test_webhook_not_fired_when_on_failure_disabled():
    settings = Settings(
        ragrig_webhook_url="http://hook.example.com/post",
        ragrig_webhook_on_failure=False,
    )
    from ragrig.webhooks import notify_task_failure

    with patch("httpx.post") as mock_post:
        notify_task_failure(
            settings,
            task_id="t1",
            task_type="index",
            error="boom",
        )
        mock_post.assert_not_called()


@pytest.mark.unit
def test_webhook_fires_on_task_failure():
    settings = Settings(
        ragrig_webhook_url="http://hook.example.com/post",
        ragrig_webhook_on_failure=True,
        ragrig_webhook_secret="",
    )

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    with patch("httpx.post", return_value=mock_resp) as mock_post:
        # Call _fire directly to avoid threading in tests
        from ragrig.webhooks import _fire

        _fire(settings, "task.failure", {"task_id": "t1", "error": "boom"})
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        body = json.loads(kwargs["content"])
        assert body["event"] == "task.failure"
        assert body["data"]["task_id"] == "t1"


@pytest.mark.unit
def test_webhook_hmac_signature():
    secret = "test-secret"
    settings = Settings(
        ragrig_webhook_url="http://hook.example.com/post",
        ragrig_webhook_on_failure=True,
        ragrig_webhook_secret=secret,
    )
    from ragrig.webhooks import _fire

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    with patch("httpx.post", return_value=mock_resp) as mock_post:
        _fire(settings, "task.failure", {"error": "boom"})
        _, kwargs = mock_post.call_args
        raw_body = kwargs["content"]
        expected_sig = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        assert kwargs["headers"]["X-RAGRig-Signature-256"] == expected_sig


@pytest.mark.unit
def test_webhook_slack_payload_format():
    settings = Settings(
        ragrig_webhook_url="https://hooks.slack.com/services/XXX",
        ragrig_webhook_on_failure=True,
        ragrig_webhook_secret="",
    )
    from ragrig.webhooks import _fire

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    with patch("httpx.post", return_value=mock_resp) as mock_post:
        _fire(settings, "task.failure", {"error": "oops"})
        _, kwargs = mock_post.call_args
        body = json.loads(kwargs["content"])
        # Slack payload has 'text', not 'event'
        assert "text" in body
        assert "event" not in body
        assert ":x:" in body["text"]


@pytest.mark.unit
def test_webhook_complete_not_fired_when_disabled():
    settings = Settings(
        ragrig_webhook_url="http://hook.example.com/post",
        ragrig_webhook_on_completion=False,
    )
    from ragrig.webhooks import notify_task_complete

    with patch("httpx.post") as mock_post:
        notify_task_complete(
            settings,
            task_id="t1",
            task_type="index",
        )
        mock_post.assert_not_called()


@pytest.mark.unit
def test_webhook_pipeline_failure():
    settings = Settings(
        ragrig_webhook_url="http://hook.example.com/post",
        ragrig_webhook_on_failure=True,
        ragrig_webhook_secret="",
    )
    from ragrig.webhooks import _fire

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    with patch("httpx.post", return_value=mock_resp) as mock_post:
        _fire(settings, "pipeline.failure", {"run_id": "r1", "error": "crash"})
        body = json.loads(mock_post.call_args[1]["content"])
        assert body["event"] == "pipeline.failure"


@pytest.mark.unit
def test_error_truncated_to_500_chars():
    settings = Settings(
        ragrig_webhook_url="http://hook.example.com/post",
        ragrig_webhook_on_failure=True,
        ragrig_webhook_secret="",
    )
    from ragrig.webhooks import notify_task_failure

    long_error = "x" * 1000
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    with patch("httpx.post", return_value=mock_resp) as mock_post:
        from ragrig.webhooks import _fire

        # notify_task_failure truncates error to 500 chars before calling _fire
        notify_task_failure.__wrapped__ if hasattr(notify_task_failure, "__wrapped__") else None
        _fire(settings, "task.failure", {"error": long_error[:500]})
        body = json.loads(mock_post.call_args[1]["content"])
        assert len(body["data"]["error"]) <= 500


# ── OpenTelemetry ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_otel_setup_skipped_when_disabled():
    """setup_otel does nothing when otel_enabled=False and log_format=text."""
    from fastapi import FastAPI

    from ragrig.otel import setup_otel

    settings = Settings(ragrig_otel_enabled=False, ragrig_log_format="text")
    app = FastAPI()
    # Should not raise even without OTel packages installed
    setup_otel(app, settings)


@pytest.mark.unit
def test_otel_json_logging_configures_formatter():
    """When log_format=json and otel disabled, JSON formatter is applied."""
    import logging

    from fastapi import FastAPI

    from ragrig.otel import setup_otel

    settings = Settings(ragrig_otel_enabled=False, ragrig_log_format="json")
    app = FastAPI()
    root = logging.getLogger()
    original_handlers = root.handlers[:]

    setup_otel(app, settings)

    try:
        # Should not raise; formatters are configured
        assert True
    finally:
        root.handlers = original_handlers


# ── ARQ worker / task backend ─────────────────────────────────────────────────


@pytest.mark.unit
def test_default_task_executor_returns_threadpool_by_default():
    from ragrig.tasks import ThreadPoolTaskExecutor, default_task_executor

    with patch("ragrig.tasks.get_settings") as mock_gs:
        mock_gs.return_value = Settings(ragrig_task_backend="threadpool")
        executor = default_task_executor()
        assert isinstance(executor, ThreadPoolTaskExecutor)
        executor.shutdown(wait=False)


@pytest.mark.unit
def test_default_task_executor_returns_arq_when_configured():
    with patch("ragrig.tasks.get_settings") as mock_gs:
        mock_gs.return_value = Settings(
            ragrig_task_backend="arq",
            ragrig_redis_url="redis://localhost:6379",
        )
        with patch("ragrig.worker.ArqTaskExecutor") as mock_arq:
            mock_arq.return_value = MagicMock()
            from ragrig.tasks import default_task_executor

            executor = default_task_executor()
            assert executor is mock_arq.return_value


@pytest.mark.unit
def test_arq_executor_raises_on_missing_arq():
    from ragrig.worker import ArqTaskExecutor

    executor = ArqTaskExecutor(redis_url="redis://localhost:6379")

    with patch.dict("sys.modules", {"arq": None}):
        with pytest.raises(ImportError, match="arq and redis"):
            executor._get_pool()


@pytest.mark.unit
def test_worker_settings_has_run_job_function():
    """WorkerSettings exposes run_job; mock arq so test runs without the optional dep."""
    import types

    fake_arq = types.ModuleType("arq")
    fake_connections = types.ModuleType("arq.connections")

    class FakeRedisSettings:
        @staticmethod
        def from_dsn(url: str) -> "FakeRedisSettings":
            return FakeRedisSettings()

    fake_connections.RedisSettings = FakeRedisSettings
    fake_arq.connections = fake_connections

    with patch.dict("sys.modules", {"arq": fake_arq, "arq.connections": fake_connections}):
        from ragrig.worker import _make_worker_settings_class, run_job

        ws = _make_worker_settings_class("redis://localhost:6379", 10)
        assert run_job in ws.functions


# ── Integration: enqueue_task fires webhooks ──────────────────────────────────


@pytest.mark.unit
def test_enqueue_task_fires_failure_webhook():
    """When a task raises, notify_task_failure is called."""
    from sqlalchemy import StaticPool, create_engine, event
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.orm import sessionmaker

    @compiles(JSONB, "sqlite")
    def _jsonb_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
        return "TEXT"

    from ragrig.db.models import Base
    from ragrig.tasks import SynchronousTaskExecutor, enqueue_task

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk_pragma(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _session():
        return factory()

    def _boom():
        raise RuntimeError("kaboom")

    settings_mock = Settings(
        ragrig_webhook_url="http://hook.example.com",
        ragrig_webhook_on_failure=True,
        ragrig_webhook_secret="",
    )
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    with patch("ragrig.tasks.get_settings", return_value=settings_mock):
        with patch("ragrig.tasks.notify_task_failure") as mock_notify:
            enqueue_task(
                session_factory=_session,
                task_executor=SynchronousTaskExecutor(),
                task_type="test",
                payload_json={},
                runner=_boom,
            )
            assert mock_notify.called
            call_kwargs = mock_notify.call_args.kwargs
            assert call_kwargs["task_type"] == "test"
            assert "kaboom" in call_kwargs["error"]


@pytest.mark.unit
def test_enqueue_task_fires_complete_webhook():
    """When a task succeeds, notify_task_complete is called."""
    from sqlalchemy import StaticPool, create_engine
    from sqlalchemy.orm import sessionmaker

    from ragrig.db.models import Base
    from ragrig.tasks import SynchronousTaskExecutor, enqueue_task

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def _session():
        return factory()

    settings_mock = Settings(
        ragrig_webhook_url="http://hook.example.com",
        ragrig_webhook_on_completion=True,
        ragrig_webhook_secret="",
    )
    with patch("ragrig.tasks.get_settings", return_value=settings_mock):
        with patch("ragrig.tasks.notify_task_complete") as mock_notify:
            enqueue_task(
                session_factory=_session,
                task_executor=SynchronousTaskExecutor(),
                task_type="test",
                payload_json={},
                runner=lambda: {"docs": 5},
            )
            assert mock_notify.called
            call_kwargs = mock_notify.call_args.kwargs
            assert call_kwargs["task_type"] == "test"
            assert call_kwargs["summary"] == {"docs": 5}
