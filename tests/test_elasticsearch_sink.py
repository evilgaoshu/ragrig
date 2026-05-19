"""Unit tests for the Elasticsearch sink connector."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ragrig.db.models import Base, Chunk, DocumentVersion
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
from ragrig.repositories import (
    get_or_create_document,
    get_or_create_knowledge_base,
    get_or_create_source,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def mem_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=True, autocommit=False, expire_on_commit=False)
    with factory() as session:
        yield session


def _seed(session, kb_name: str = "test-kb", chunk_count: int = 2):
    kb = get_or_create_knowledge_base(session, kb_name)
    source = get_or_create_source(
        session,
        knowledge_base_id=kb.id,
        kind="local_directory",
        uri="/tmp/test-kb",
        config_json={"root_path": "/tmp/test-kb"},
    )
    doc, _ = get_or_create_document(
        session,
        knowledge_base_id=kb.id,
        source_id=source.id,
        uri="test-kb/doc.txt",
        content_hash="deadbeef",
        mime_type="text/plain",
        metadata_json={},
    )
    dv = DocumentVersion(
        document_id=doc.id,
        version_number=1,
        content_hash="deadbeef",
        parser_name="text",
        parser_config_json={},
        extracted_text="chunk one\nchunk two",
        metadata_json={},
    )
    session.add(dv)
    session.flush()

    chunks = []
    for i in range(chunk_count):
        chunk = Chunk(
            id=uuid.uuid4(),
            document_version_id=dv.id,
            chunk_index=i,
            text=f"chunk text {i}",
            metadata_json={"index": i},
        )
        session.add(chunk)
        chunks.append(chunk)
    session.flush()

    return kb, dv, chunks


def _make_config(**overrides):
    defaults = {
        "url": "http://localhost:9200",
        "index": "test-index",
    }
    defaults.update(overrides)
    return ElasticsearchSinkConfig(**defaults)


class TestDryRun:
    def test_dry_run_returns_planned_count_without_indexing(self, mem_session) -> None:
        _seed(mem_session, chunk_count=3)
        config = _make_config(dry_run=True)
        report = export_to_elasticsearch(
            mem_session,
            knowledge_base_name="test-kb",
            config=config,
        )
        assert report.dry_run is True
        assert report.planned_count == 3
        assert report.indexed_count == 0
        assert report.failed_count == 0

    def test_dry_run_returns_zero_for_empty_kb(self, mem_session) -> None:
        get_or_create_knowledge_base(mem_session, "empty-kb")
        config = _make_config(dry_run=True)
        report = export_to_elasticsearch(
            mem_session,
            knowledge_base_name="empty-kb",
            config=config,
        )
        assert report.dry_run is True
        assert report.planned_count == 0
        assert report.indexed_count == 0


class TestSecretResolution:
    def test_raises_on_missing_knowledge_base(self, mem_session) -> None:
        config = _make_config()
        with pytest.raises(ValueError, match="was not found"):
            export_to_elasticsearch(
                mem_session,
                knowledge_base_name="nonexistent",
                config=config,
            )

    def test_raises_config_error_for_non_env_api_key(self, mem_session) -> None:
        _seed(mem_session)
        # api_key not using env: prefix
        config = _make_config(dry_run=False, api_key="plaintext-key")
        with pytest.raises(ElasticsearchConfigError, match="env:VAR"):
            export_to_elasticsearch(
                mem_session,
                knowledge_base_name="test-kb",
                config=config,
            )

    def test_raises_config_error_for_non_env_password(self, mem_session) -> None:
        _seed(mem_session)
        config = _make_config(dry_run=False, username="user", password="plaintext-password")
        with pytest.raises(ElasticsearchConfigError, match="env:VAR"):
            export_to_elasticsearch(
                mem_session,
                knowledge_base_name="test-kb",
                config=config,
            )

    def test_raises_config_error_when_env_var_not_set(self, mem_session) -> None:
        _seed(mem_session)
        config = _make_config(dry_run=False, api_key="env:MISSING_ES_KEY")
        with pytest.raises(ElasticsearchConfigError, match="MISSING_ES_KEY"):
            export_to_elasticsearch(
                mem_session,
                knowledge_base_name="test-kb",
                config=config,
                env={},
            )

    def test_raises_config_error_when_both_api_key_and_username_set(self, mem_session) -> None:
        _seed(mem_session)
        config = _make_config(
            api_key="env:ES_API_KEY",
            username="user",
            password="env:ES_PASSWORD",
        )
        with pytest.raises(ElasticsearchConfigError, match="both"):
            export_to_elasticsearch(
                mem_session,
                knowledge_base_name="test-kb",
                config=config,
                env={"ES_API_KEY": "secret", "ES_PASSWORD": "pass"},
            )


class TestHttpxBulkExport:
    """Tests using the httpx fallback (elasticsearch SDK not installed)."""

    def _mock_httpx_success(self, chunk_count: int):
        """Return a mock httpx Response simulating a successful bulk response."""
        items = [
            {"index": {"_id": str(uuid.uuid4()), "result": "created"}} for _ in range(chunk_count)
        ]
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"errors": False, "items": items}
        return mock_resp

    def test_bulk_export_via_httpx_success(self, mem_session) -> None:
        _seed(mem_session, chunk_count=2)
        config = _make_config(batch_size=10)

        mock_resp = self._mock_httpx_success(2)

        with patch("ragrig.plugins.sinks.elasticsearch.connector._es_ready", False):
            with patch("httpx.post", return_value=mock_resp) as mock_post:
                report = export_to_elasticsearch(
                    mem_session,
                    knowledge_base_name="test-kb",
                    config=config,
                )

        assert report.planned_count == 2
        assert report.indexed_count == 2
        assert report.failed_count == 0
        assert mock_post.called

    def test_bulk_export_respects_batch_size(self, mem_session) -> None:
        _seed(mem_session, chunk_count=5)
        config = _make_config(batch_size=2)

        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"errors": False, "items": [{"index": {}}] * 2}

        with patch("ragrig.plugins.sinks.elasticsearch.connector._es_ready", False):
            with patch("httpx.post", return_value=mock_resp) as mock_post:
                export_to_elasticsearch(
                    mem_session,
                    knowledge_base_name="test-kb",
                    config=config,
                )

        # With 5 chunks and batch_size=2 we get ceil(5/2)=3 requests
        assert mock_post.call_count == 3

    def test_bulk_export_raises_auth_error_on_401(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        config = _make_config()

        mock_resp = MagicMock()
        mock_resp.is_success = False
        mock_resp.status_code = 401
        mock_resp.text = "Unauthorized"

        with patch("ragrig.plugins.sinks.elasticsearch.connector._es_ready", False):
            with patch("httpx.post", return_value=mock_resp):
                with pytest.raises(ElasticsearchAuthError):
                    export_to_elasticsearch(
                        mem_session,
                        knowledge_base_name="test-kb",
                        config=config,
                    )

    def test_bulk_export_raises_sink_error_on_500(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        config = _make_config()

        mock_resp = MagicMock()
        mock_resp.is_success = False
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"

        with patch("ragrig.plugins.sinks.elasticsearch.connector._es_ready", False):
            with patch("httpx.post", return_value=mock_resp):
                with pytest.raises(ElasticsearchSinkError):
                    export_to_elasticsearch(
                        mem_session,
                        knowledge_base_name="test-kb",
                        config=config,
                    )

    def test_api_key_auth_passed_as_bearer_header(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        config = _make_config(api_key="env:ES_API_KEY")

        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"errors": False, "items": [{"index": {}}]}

        with patch("ragrig.plugins.sinks.elasticsearch.connector._es_ready", False):
            with patch("httpx.post", return_value=mock_resp) as mock_post:
                export_to_elasticsearch(
                    mem_session,
                    knowledge_base_name="test-kb",
                    config=config,
                    env={"ES_API_KEY": "my-secret-key"},
                )

        call_kwargs = mock_post.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers") or {}
        assert "ApiKey my-secret-key" in headers.get("Authorization", "")


class TestReport:
    def test_report_is_dataclass_with_expected_fields(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        config = _make_config(dry_run=True)
        report = export_to_elasticsearch(
            mem_session,
            knowledge_base_name="test-kb",
            config=config,
        )
        assert isinstance(report, ElasticsearchExportReport)
        assert report.pipeline_run_id.startswith("es-export-")
        assert isinstance(report.planned_count, int)
        assert isinstance(report.indexed_count, int)
        assert isinstance(report.failed_count, int)
        assert report.dry_run is True

    def test_empty_kb_dry_run_returns_zero_counts(self, mem_session) -> None:
        get_or_create_knowledge_base(mem_session, "zero-kb")
        config = _make_config(dry_run=True)
        report = export_to_elasticsearch(
            mem_session,
            knowledge_base_name="zero-kb",
            config=config,
        )
        assert report.planned_count == 0
        assert report.indexed_count == 0
        assert report.failed_count == 0


class TestSdkPath:
    """Test that the SDK path is used when elasticsearch-py is available."""

    def test_sdk_bulk_called_when_es_ready(self, mem_session) -> None:
        _seed(mem_session, chunk_count=2)
        config = _make_config()

        mock_es_instance = MagicMock()
        mock_helpers = MagicMock()
        mock_helpers.bulk.return_value = (2, [])

        with patch("ragrig.plugins.sinks.elasticsearch.connector._es_ready", True):
            with patch(
                "ragrig.plugins.sinks.elasticsearch.connector.Elasticsearch",
                return_value=mock_es_instance,
                create=True,
            ):
                with patch(
                    "ragrig.plugins.sinks.elasticsearch.connector.helpers",
                    mock_helpers,
                    create=True,
                ):
                    report = export_to_elasticsearch(
                        mem_session,
                        knowledge_base_name="test-kb",
                        config=config,
                    )

        assert mock_helpers.bulk.called
        assert report.indexed_count == 2
        assert report.failed_count == 0
