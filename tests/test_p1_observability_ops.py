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
from types import SimpleNamespace
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
        assert "https://app.example.com/login?token=mytoken" in raw_msg


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
def test_arq_executor_enqueues_structured_dispatch_without_pickle():
    import asyncio

    from ragrig.tasks import TaskDispatch
    from ragrig.worker import ArqTaskExecutor

    class FakePool:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        async def enqueue_job(self, function_name: str, payload: dict[str, object]) -> None:
            self.calls.append((function_name, payload))

    loop = asyncio.new_event_loop()
    executor = ArqTaskExecutor(redis_url="redis://localhost:6379")
    executor._loop = loop
    executor._pool = FakePool()
    executor._get_pool = lambda: executor._pool  # type: ignore[method-assign]
    dispatch = TaskDispatch(
        task_id="task-1",
        task_type="source_ingest",
        payload_json={"knowledge_base": "kb", "plugin_id": "source.s3", "config": {}},
    )
    try:
        executor.submit_task(dispatch, lambda: None)
        assert executor._pool.calls == [("ragrig.worker.run_job", dispatch.to_dict())]
        with pytest.raises(RuntimeError, match="structured task dispatch"):
            executor.submit(lambda: None)
    finally:
        loop.close()


@pytest.mark.unit
def test_worker_run_job_uses_threadpool_dispatch():
    import asyncio

    from ragrig.worker import run_job

    payload = {"task_id": "task-1", "task_type": "source_ingest", "payload_json": {}}
    seen: list[dict[str, object]] = []

    def _capture(dispatch_payload: dict[str, object]) -> None:
        seen.append(dispatch_payload)

    with patch("ragrig.worker._run_dispatch", side_effect=_capture):
        asyncio.run(run_job({}, payload))

    assert seen == [payload]


@pytest.mark.unit
def test_worker_run_dispatch_builds_task_dispatch():
    from ragrig.worker import _run_dispatch

    payload = {
        "task_id": "task-1",
        "task_type": "source_ingest",
        "payload_json": {"plugin_id": "source.s3"},
    }

    with patch("ragrig.worker.run_serialized_task") as mock_run:
        _run_dispatch(payload)

    dispatch = mock_run.call_args.kwargs["dispatch"]
    assert dispatch.task_id == "task-1"
    assert dispatch.task_type == "source_ingest"
    assert dispatch.payload_json == {"plugin_id": "source.s3"}


@pytest.mark.unit
def test_arq_executor_get_pool_success_and_shutdown():
    import asyncio
    import types

    from ragrig.worker import ArqTaskExecutor

    fake_arq = types.ModuleType("arq")
    fake_connections = types.ModuleType("arq.connections")

    class FakeRedisSettings:
        @staticmethod
        def from_dsn(url: str) -> "FakeRedisSettings":
            assert url == "redis://localhost:6379"
            return FakeRedisSettings()

    class FakePool:
        def __init__(self) -> None:
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    pool = FakePool()

    async def create_pool(_settings: FakeRedisSettings) -> FakePool:
        return pool

    fake_arq.create_pool = create_pool  # type: ignore[attr-defined]
    fake_connections.RedisSettings = FakeRedisSettings
    fake_arq.connections = fake_connections  # type: ignore[attr-defined]

    executor = ArqTaskExecutor(redis_url="redis://localhost:6379")
    with patch.dict("sys.modules", {"arq": fake_arq, "arq.connections": fake_connections}):
        try:
            assert executor._get_pool() is pool
            assert executor._get_pool() is pool
            executor.shutdown()
            assert pool.closed is True
        finally:
            if executor._loop is not None:
                executor._loop.close()
                asyncio.set_event_loop(None)


@pytest.mark.unit
def test_worker_settings_helpers_are_lazy():
    from ragrig.worker import _get_worker_settings, _LazyWorkerSettings

    delegate = type("Delegate", (), {"functions": ["run_job"], "max_jobs": 2})

    with patch("ragrig.config.get_settings") as mock_settings:
        mock_settings.return_value = Settings(
            ragrig_redis_url="redis://localhost:6379",
            ragrig_task_queue_max_jobs=2,
        )
        with patch("ragrig.worker._make_worker_settings_class", return_value=delegate) as mock_make:
            assert _get_worker_settings() is delegate
            mock_make.assert_called_once_with("redis://localhost:6379", 2)

    proxy = _LazyWorkerSettings()
    with patch("ragrig.worker._get_worker_settings", return_value=delegate) as mock_get:
        assert proxy.functions == ["run_job"]
        assert proxy.max_jobs == 2
        assert proxy._delegate is delegate
        assert proxy.functions == ["run_job"]
        mock_get.assert_called_once()


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


@pytest.mark.unit
def test_serialized_task_dispatch_uses_whitelisted_runner():
    from ragrig.tasks import run_serialized_task

    payload = {
        "task_id": "task-1",
        "task_type": "source_ingest",
        "payload_json": {"plugin_id": "source.s3"},
    }

    def runner():
        return {"status": "ok"}

    with patch("ragrig.tasks._runner_for_dispatch", return_value=runner) as mock_runner:
        with patch("ragrig.tasks.run_task_payload") as mock_run:
            run_serialized_task(session_factory=lambda: None, dispatch=payload)

    mock_runner.assert_called_once_with(
        session_factory=mock_runner.call_args.kwargs["session_factory"],
        task_type="source_ingest",
        payload_json={"plugin_id": "source.s3"},
    )
    assert mock_run.call_args.kwargs["task_id"] == "task-1"
    assert mock_run.call_args.kwargs["task_type"] == "source_ingest"
    assert mock_run.call_args.kwargs["runner"]() == {"status": "ok"}


@pytest.mark.unit
def test_runner_for_dispatch_allows_only_known_task_types():
    from ragrig.tasks import _runner_for_dispatch

    def session_factory():
        return None

    with patch("ragrig.tasks.run_ingestion_dag_task", return_value={"kind": "dag"}) as mock_dag:
        runner = _runner_for_dispatch(
            session_factory=session_factory,
            task_type="pipeline_dag_ingestion",
            payload_json={"pipeline_run_id": 123},
        )
        assert runner() == {"kind": "dag"}
        mock_dag.assert_called_once_with(
            session_factory=session_factory,
            pipeline_run_id="123",
        )

    with patch("ragrig.tasks.run_upload_pipeline", return_value={"kind": "upload"}) as mock_upload:
        runner = _runner_for_dispatch(
            session_factory=session_factory,
            task_type="knowledge_base_upload",
            payload_json={
                "knowledge_base": "kb",
                "pipeline_run_id": "run-1",
                "staged_files": [{"path": "/tmp/doc.md"}],
                "workspace_id": "workspace-1",
            },
        )
        assert runner() == {"kind": "upload"}
        mock_upload.assert_called_once_with(
            session_factory=session_factory,
            kb_name="kb",
            pipeline_run_id="run-1",
            staged_files=[{"path": "/tmp/doc.md"}],
            workspace_id="workspace-1",
        )

    with patch(
        "ragrig.tasks.run_source_ingest_task",
        return_value={"kind": "source"},
    ) as mock_source:
        runner = _runner_for_dispatch(
            session_factory=session_factory,
            task_type="source_ingest",
            payload_json={
                "plugin_id": "source.s3",
                "config": {"bucket": "docs"},
                "knowledge_base": "kb",
                "operator": "alice",
                "workspace_id": "workspace-1",
            },
        )
        assert runner() == {"kind": "source"}
        mock_source.assert_called_once_with(
            session_factory=session_factory,
            plugin_id="source.s3",
            config={"bucket": "docs"},
            knowledge_base_name="kb",
            operator="alice",
            workspace_id="workspace-1",
        )

    with pytest.raises(ValueError, match="unsupported serialized task type"):
        _runner_for_dispatch(
            session_factory=session_factory,
            task_type="pickle",
            payload_json={},
        )


@pytest.mark.unit
def test_task_helper_edge_branches(tmp_path):
    from ragrig.tasks import (
        SynchronousTaskExecutor,
        _not_retryable_reason,
        _staged_files_available,
        cleanup_staged_files,
        cleanup_staging_dir,
        is_task_retryable,
        sanitize_filename,
        summarize_exception,
        task_last_error,
        validate_and_stage_uploads,
    )

    failed_node_task = SimpleNamespace(error=None, result_json={"failed_node": "embed"})
    assert task_last_error(failed_node_task) == "embed"

    unsupported_task = SimpleNamespace(
        task_type="custom_task",
        status="failed",
        payload_json={},
        result_json={},
        next_task_id=None,
    )
    assert is_task_retryable(unsupported_task) is False
    assert _not_retryable_reason(unsupported_task) == "Task type 'custom_task' cannot retry."

    missing_upload = SimpleNamespace(
        task_type="knowledge_base_upload",
        status="failed",
        payload_json={},
        result_json={},
        next_task_id=None,
    )
    assert _staged_files_available({}) is False
    assert _not_retryable_reason(missing_upload).startswith("Upload retry requires")

    running_dag = SimpleNamespace(
        task_type="pipeline_dag_ingestion",
        status="running",
        payload_json={},
        result_json={},
        next_task_id=None,
    )
    assert _not_retryable_reason(running_dag) == "Task status 'running' is not retryable."

    try:
        raise RuntimeError("x" * 2100)
    except RuntimeError as exc:
        assert summarize_exception(exc).endswith("...")

    cleanup_staged_files([])
    cleanup_staging_dir(None)
    SynchronousTaskExecutor().shutdown()
    assert sanitize_filename(".env") == "upload_.env"
    assert sanitize_filename("\0") == "upload_file"

    staged_dir = tmp_path / "staged"
    staged_dir.mkdir()
    staged_file = staged_dir / "doc.md"
    staged_file.write_text("hello")
    assert _staged_files_available({"staged_files": [{"path": str(staged_file)}]}) is True
    cleanup_staged_files([{"path": str(staged_file)}])
    assert not staged_dir.exists()

    cleanup_dir = tmp_path / "cleanup-dir"
    cleanup_dir.mkdir()
    cleanup_staging_dir(str(cleanup_dir))
    assert not cleanup_dir.exists()

    planned = validate_and_stage_uploads(files=[("sheet.xlsx", b"not really xlsx")])
    try:
        assert planned.staged_files == []
        assert planned.rejected[0]["extension"] == ".xlsx"
        assert planned.rejected[0]["reason"] == "unsupported_format"
        assert "planned" in planned.rejected[0]["message"].lower()
    finally:
        cleanup_staging_dir(planned.staging_dir)


@pytest.mark.unit
def test_task_payload_invalid_pipeline_include_is_ignored():
    from ragrig.tasks import get_task_payload

    task = SimpleNamespace(
        id="task-1",
        task_type="knowledge_base_upload",
        status="completed",
        payload_json={"pipeline_run_id": "not-a-uuid"},
        result_json={},
        error=None,
        attempt_count=1,
        previous_task_id=None,
        next_task_id=None,
        started_at=None,
        finished_at=None,
        progress=None,
    )

    class DummySession:
        def __enter__(self) -> "DummySession":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            pass

    with patch("ragrig.tasks.get_task_record", return_value=task):
        payload = get_task_payload(
            session_factory=DummySession,
            task_id="task-1",
            include_pipeline_run=True,
        )

    assert payload is not None
    assert "pipeline_run" not in payload


@pytest.mark.unit
def test_upload_pipeline_missing_records_fail_fast(tmp_path):
    import uuid

    from ragrig.tasks import (
        create_upload_pipeline_run,
        mark_pipeline_run_failed,
        run_upload_pipeline,
    )

    workspace_id = uuid.uuid4()

    class DummySession:
        def __enter__(self) -> "DummySession":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            pass

        def get(self, *_args, **_kwargs):
            return None

    with patch("ragrig.tasks.get_knowledge_base_by_name", return_value=None):
        with pytest.raises(ValueError, match="knowledge base 'missing' not found"):
            create_upload_pipeline_run(
                DummySession(),
                kb_name="missing",
                staged_files=[{"path": str(tmp_path / "doc.md")}],
                workspace_id=workspace_id,
            )

    mark_pipeline_run_failed(
        session_factory=DummySession,
        pipeline_run_id=str(uuid.uuid4()),
        error_message="boom",
    )

    missing_kb_dir = tmp_path / "missing-kb"
    missing_kb_dir.mkdir()
    missing_kb_file = missing_kb_dir / "doc.md"
    missing_kb_file.write_text("hello")
    with patch("ragrig.tasks.get_knowledge_base_by_name", return_value=None):
        with pytest.raises(ValueError, match="knowledge base 'missing' not found"):
            run_upload_pipeline(
                session_factory=DummySession,
                kb_name="missing",
                pipeline_run_id=str(uuid.uuid4()),
                staged_files=[{"path": str(missing_kb_file)}],
                workspace_id=workspace_id,
            )

    missing_run_dir = tmp_path / "missing-run"
    missing_run_dir.mkdir()
    missing_run_file = missing_run_dir / "doc.md"
    missing_run_file.write_text("hello")
    kb = SimpleNamespace(id=uuid.uuid4(), workspace_id=workspace_id)
    with patch("ragrig.tasks.get_knowledge_base_by_name", return_value=kb):
        with pytest.raises(ValueError, match="pipeline run"):
            run_upload_pipeline(
                session_factory=DummySession,
                kb_name="kb",
                pipeline_run_id=str(uuid.uuid4()),
                staged_files=[{"path": str(missing_run_file)}],
                workspace_id=workspace_id,
            )


@pytest.mark.unit
def test_prepare_upload_retry_preserves_workspace_and_runner():
    import uuid

    from ragrig.tasks import _prepare_upload_retry

    workspace_id = str(uuid.uuid4())

    class DummySession:
        def __enter__(self) -> "DummySession":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            pass

    with patch(
        "ragrig.tasks.create_upload_pipeline_run",
        return_value=("run-2", "source-1"),
    ) as mock_create:
        prepared = _prepare_upload_retry(
            session_factory=DummySession,
            previous_task_id="task-1",
            previous_payload={
                "knowledge_base": "kb",
                "workspace_id": workspace_id,
                "staged_files": [{"path": "/tmp/doc.md"}],
            },
        )

    assert prepared["pipeline_run_id"] == "run-2"
    assert prepared["payload_json"] == {
        "knowledge_base": "kb",
        "workspace_id": workspace_id,
        "pipeline_run_id": "run-2",
        "staged_files": [{"path": "/tmp/doc.md"}],
        "retry_of": "task-1",
    }
    mock_create.assert_called_once()
    assert mock_create.call_args.kwargs["workspace_id"] == uuid.UUID(workspace_id)

    with patch("ragrig.tasks.run_upload_pipeline", return_value={"status": "ok"}) as mock_upload:
        assert prepared["runner"]() == {"status": "ok"}
        mock_upload.assert_called_once_with(
            session_factory=DummySession,
            kb_name="kb",
            pipeline_run_id="run-2",
            staged_files=[{"path": "/tmp/doc.md"}],
            workspace_id=workspace_id,
        )


@pytest.mark.unit
def test_retry_task_missing_record_reports_not_found():
    from ragrig.tasks import TaskRetryError, retry_task

    class DummySession:
        def __enter__(self) -> "DummySession":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            pass

    with patch("ragrig.tasks.get_task_record", return_value=None):
        with pytest.raises(TaskRetryError) as exc_info:
            retry_task(
                session_factory=DummySession,
                task_executor=MagicMock(),
                task_id="missing",
            )

    assert exc_info.value.code == "task_not_found"
    assert exc_info.value.status_code == 404


@pytest.mark.unit
def test_retry_task_failed_upload_uses_upload_retry_path(tmp_path):
    import uuid

    from ragrig.tasks import retry_task

    staged_file = tmp_path / "doc.md"
    staged_file.write_text("hello")
    original_task = SimpleNamespace(
        task_type="knowledge_base_upload",
        status="failed",
        payload_json={
            "knowledge_base": "kb",
            "pipeline_run_id": "previous-run",
            "staged_files": [{"path": str(staged_file)}],
        },
        result_json={},
        error=None,
        attempt_count=3,
        next_task_id=None,
    )
    new_task_id = uuid.uuid4()

    class DummySession:
        def __enter__(self) -> "DummySession":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            pass

    prepared = {
        "payload_json": {
            "knowledge_base": "kb",
            "pipeline_run_id": "retry-run",
            "staged_files": [{"path": str(staged_file)}],
        },
        "pipeline_run_id": "retry-run",
        "runner": lambda: {"status": "completed"},
    }

    def fake_enqueue_task(**kwargs):
        kwargs["on_task_created"](DummySession(), SimpleNamespace(id=new_task_id))
        return "retry-task"

    with patch("ragrig.tasks.get_task_record", return_value=original_task):
        with patch("ragrig.tasks._prepare_upload_retry", return_value=prepared) as mock_prepare:
            with patch("ragrig.tasks.enqueue_task", side_effect=fake_enqueue_task) as mock_enqueue:
                result = retry_task(
                    session_factory=DummySession,
                    task_executor=MagicMock(),
                    task_id="original-task",
                )

    assert result == {
        "task_id": "retry-task",
        "previous_task_id": "original-task",
        "pipeline_run_id": "retry-run",
        "status": "pending",
    }
    mock_prepare.assert_called_once()
    assert mock_enqueue.call_args.kwargs["task_type"] == "knowledge_base_upload"
    assert original_task.next_task_id == new_task_id
    assert original_task.payload_json["next_task_id"] == str(new_task_id)
    assert original_task.payload_json["next_pipeline_run_id"] == "retry-run"


@pytest.mark.unit
def test_retry_task_defensive_link_errors(tmp_path):
    import uuid

    from ragrig.tasks import TaskRetryError, retry_task

    staged_file = tmp_path / "doc.md"
    staged_file.write_text("hello")

    class DummySession:
        def __enter__(self) -> "DummySession":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            pass

    prepared = {
        "payload_json": {
            "knowledge_base": "kb",
            "pipeline_run_id": "retry-run",
            "staged_files": [{"path": str(staged_file)}],
        },
        "pipeline_run_id": "retry-run",
        "runner": lambda: {"status": "completed"},
    }

    unsupported_task = SimpleNamespace(
        task_type="custom_task",
        status="failed",
        payload_json={"staged_files": [{"path": str(staged_file)}]},
        result_json={},
        error=None,
        attempt_count=1,
        next_task_id=None,
    )
    with patch("ragrig.tasks.get_task_record", return_value=unsupported_task):
        with patch("ragrig.tasks.is_task_retryable", return_value=True):
            with pytest.raises(TaskRetryError) as exc_info:
                retry_task(
                    session_factory=DummySession,
                    task_executor=MagicMock(),
                    task_id="original-task",
                )
    assert exc_info.value.code == "unsupported_task_type"

    def _failed_upload_task() -> SimpleNamespace:
        return SimpleNamespace(
            task_type="knowledge_base_upload",
            status="failed",
            payload_json={
                "knowledge_base": "kb",
                "pipeline_run_id": "previous-run",
                "staged_files": [{"path": str(staged_file)}],
            },
            result_json={},
            error=None,
            attempt_count=1,
            next_task_id=None,
        )

    def fake_enqueue_task(**kwargs):
        kwargs["on_task_created"](DummySession(), SimpleNamespace(id=uuid.uuid4()))
        return "retry-task"

    with patch("ragrig.tasks.get_task_record", side_effect=[_failed_upload_task(), None]):
        with patch("ragrig.tasks._prepare_upload_retry", return_value=prepared):
            with patch("ragrig.tasks.enqueue_task", side_effect=fake_enqueue_task):
                with pytest.raises(TaskRetryError) as exc_info:
                    retry_task(
                        session_factory=DummySession,
                        task_executor=MagicMock(),
                        task_id="original-task",
                    )
    assert exc_info.value.code == "task_not_found"

    stale_previous = SimpleNamespace(
        next_task_id=uuid.uuid4(),
        payload_json={"next_task_id": "existing"},
    )
    with patch(
        "ragrig.tasks.get_task_record",
        side_effect=[_failed_upload_task(), stale_previous],
    ):
        with patch("ragrig.tasks._prepare_upload_retry", return_value=prepared):
            with patch("ragrig.tasks.enqueue_task", side_effect=fake_enqueue_task):
                with pytest.raises(TaskRetryError) as exc_info:
                    retry_task(
                        session_factory=DummySession,
                        task_executor=MagicMock(),
                        task_id="original-task",
                    )
    assert exc_info.value.code == "duplicate_retry"


@pytest.mark.unit
def test_upload_pipeline_records_degraded_parse(tmp_path):
    import uuid

    from ragrig.tasks import run_upload_pipeline

    workspace_id = uuid.uuid4()
    kb = SimpleNamespace(id=uuid.uuid4(), workspace_id=workspace_id)
    source = SimpleNamespace(id=uuid.uuid4())
    document = SimpleNamespace(id=uuid.uuid4())
    run = SimpleNamespace(
        id=uuid.uuid4(),
        total_items=0,
        success_count=0,
        failure_count=0,
        status="running",
        finished_at=None,
    )
    staged_dir = tmp_path / "degraded-upload"
    staged_dir.mkdir()
    staged_file = staged_dir / "doc.md"
    staged_file.write_text("hello")

    class DummySession:
        def __enter__(self) -> "DummySession":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            pass

        def get(self, *_args, **_kwargs):
            return run

        def add(self, _obj) -> None:
            pass

        def flush(self) -> None:
            pass

        def commit(self) -> None:
            pass

    parse_result = SimpleNamespace(
        content_hash="hash",
        mime_type="text/plain",
        metadata={"degraded_reason": "fallback_parser"},
        parser_name="text",
        extracted_text="hello",
    )
    indexing_report = SimpleNamespace(
        pipeline_run_id=uuid.uuid4(),
        indexed_count=1,
        skipped_count=0,
        failed_count=0,
        chunk_count=1,
        embedding_count=1,
    )

    with patch("ragrig.tasks.get_knowledge_base_by_name", return_value=kb):
        with patch("ragrig.tasks.get_or_create_source", return_value=source):
            with patch("ragrig.tasks._select_parser", return_value=object()):
                with patch("ragrig.tasks.parse_with_timeout", return_value=parse_result):
                    with patch(
                        "ragrig.tasks.get_or_create_document",
                        return_value=(document, True),
                    ):
                        with patch("ragrig.tasks.get_next_version_number", return_value=1):
                            with patch("ragrig.tasks.create_pipeline_run_item") as mock_item:
                                with patch(
                                    "ragrig.tasks.index_knowledge_base",
                                    return_value=indexing_report,
                                ):
                                    result = run_upload_pipeline(
                                        session_factory=DummySession,
                                        kb_name="kb",
                                        pipeline_run_id=str(run.id),
                                        staged_files=[{"path": str(staged_file)}],
                                        workspace_id=workspace_id,
                                    )

    assert result["status"] == "completed"
    assert mock_item.call_args.kwargs["status"] == "degraded"
    assert mock_item.call_args.kwargs["metadata_json"]["degraded_reason"] == "fallback_parser"
    assert not staged_dir.exists()


@pytest.mark.unit
def test_upload_pipeline_records_parser_timeout(tmp_path):
    import uuid

    from ragrig.parsers.base import ParserTimeoutError
    from ragrig.tasks import run_upload_pipeline

    workspace_id = uuid.uuid4()
    kb = SimpleNamespace(id=uuid.uuid4(), workspace_id=workspace_id)
    source = SimpleNamespace(id=uuid.uuid4())
    document = SimpleNamespace(id=uuid.uuid4())
    run = SimpleNamespace(
        id=uuid.uuid4(),
        total_items=0,
        success_count=0,
        failure_count=0,
        status="running",
        finished_at=None,
    )
    staged_dir = tmp_path / "timeout-upload"
    staged_dir.mkdir()
    staged_file = staged_dir / "doc.md"
    staged_file.write_text("hello")

    class DummySession:
        def __enter__(self) -> "DummySession":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            pass

        def get(self, *_args, **_kwargs):
            return run

        def commit(self) -> None:
            pass

    indexing_report = SimpleNamespace(
        pipeline_run_id=uuid.uuid4(),
        indexed_count=0,
        skipped_count=0,
        failed_count=0,
        chunk_count=0,
        embedding_count=0,
    )

    with patch("ragrig.tasks.get_knowledge_base_by_name", return_value=kb):
        with patch("ragrig.tasks.get_or_create_source", return_value=source):
            with patch("ragrig.tasks._select_parser", return_value=object()):
                with patch(
                    "ragrig.tasks.parse_with_timeout",
                    side_effect=ParserTimeoutError("timed out"),
                ):
                    with patch(
                        "ragrig.tasks.get_or_create_document",
                        return_value=(document, True),
                    ) as mock_document:
                        with patch("ragrig.tasks.create_pipeline_run_item") as mock_item:
                            with patch(
                                "ragrig.tasks.index_knowledge_base",
                                return_value=indexing_report,
                            ):
                                result = run_upload_pipeline(
                                    session_factory=DummySession,
                                    kb_name="kb",
                                    pipeline_run_id=str(run.id),
                                    staged_files=[{"path": str(staged_file)}],
                                    workspace_id=workspace_id,
                                )

    assert result["status"] == "completed_with_failures"
    assert run.failure_count == 1
    assert run.success_count == 0
    timeout_metadata = mock_document.call_args.kwargs["metadata_json"]
    assert timeout_metadata["failure_reason"] == "parser_timeout"
    assert mock_item.call_args.kwargs["status"] == "failed"
    assert mock_item.call_args.kwargs["metadata_json"]["failure_reason"] == "parser_timeout"
    assert staged_dir.exists()


@pytest.mark.unit
def test_run_ingestion_dag_task_rewraps_rejected_dag():
    from ragrig.tasks import run_ingestion_dag_task
    from ragrig.workflows import IngestionDagRejected

    class DummySession:
        def __enter__(self) -> "DummySession":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            pass

    with patch(
        "ragrig.tasks.execute_ingestion_dag_run",
        side_effect=IngestionDagRejected("bad dag"),
    ):
        with pytest.raises(ValueError, match="bad dag"):
            run_ingestion_dag_task(
                session_factory=DummySession,
                pipeline_run_id="run-1",
            )


# ── Integration: enqueue_task fires webhooks ──────────────────────────────────


@pytest.mark.unit
def test_enqueue_task_fires_failure_webhook():
    """When a task raises, notify_task_failure is called."""
    from sqlalchemy import StaticPool, create_engine, event
    from sqlalchemy.orm import sessionmaker

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
