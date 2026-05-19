"""Unit tests for the agent_access sink connector."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ragrig.db.models import Base, Chunk, DocumentVersion
from ragrig.plugins.sinks.agent_access.connector import (
    export_to_agent_endpoint,
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


def _seed(session, kb_name: str = "test-kb", chunk_count: int = 3):
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
        extracted_text="body",
        metadata_json={},
    )
    session.add(dv)
    session.flush()

    for i in range(chunk_count):
        chunk = Chunk(
            id=uuid.uuid4(),
            document_version_id=dv.id,
            chunk_index=i,
            text=f"chunk {i}",
            metadata_json={"i": i},
        )
        session.add(chunk)
    session.flush()
    return kb


class MockHTTPResponse:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError(
                f"{self.status_code}",
                request=None,  # type: ignore[arg-type]
                response=None,  # type: ignore[arg-type]
            )


class MockHTTPClient:
    def __init__(self, status_code: int = 200):
        self.requests: list[dict] = []
        self._status_code = status_code

    def post(self, url: str, *, content: bytes, headers: dict) -> MockHTTPResponse:
        self.requests.append({"url": url, "content": content, "headers": dict(headers)})
        return MockHTTPResponse(self._status_code)

    def close(self) -> None:
        pass


class TestDryRun:
    def test_dry_run_returns_counts_without_sending(self, mem_session) -> None:
        _seed(mem_session, chunk_count=3)
        report = export_to_agent_endpoint(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://example.com/ingest",
            api_key="tok",
            dry_run=True,
        )
        assert report.dry_run is True
        assert report.chunk_count == 3
        assert report.delivered_batches == 0
        assert report.failed_batches == 0

    def test_dry_run_no_http_calls(self, mem_session) -> None:
        _seed(mem_session, chunk_count=2)
        client = MockHTTPClient()
        export_to_agent_endpoint(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://example.com/ingest",
            api_key="tok",
            dry_run=True,
            _client=client,
        )
        assert client.requests == []


class TestDelivery:
    def test_single_batch_delivered(self, mem_session) -> None:
        _seed(mem_session, chunk_count=3)
        client = MockHTTPClient()
        report = export_to_agent_endpoint(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://example.com/ingest",
            api_key="tok",
            _client=client,
        )
        assert report.delivered_batches == 1
        assert report.failed_batches == 0
        assert len(client.requests) == 1

    def test_bearer_token_in_authorization_header(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        client = MockHTTPClient()
        export_to_agent_endpoint(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://example.com/ingest",
            api_key="my-secret-token",
            _client=client,
        )
        assert client.requests[0]["headers"]["Authorization"] == "Bearer my-secret-token"

    def test_api_key_from_env(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        client = MockHTTPClient()
        export_to_agent_endpoint(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://example.com/ingest",
            api_key="env:MY_API_KEY",
            env={"MY_API_KEY": "resolved-key"},
            _client=client,
        )
        assert client.requests[0]["headers"]["Authorization"] == "Bearer resolved-key"

    def test_payload_structure(self, mem_session) -> None:
        _seed(mem_session, chunk_count=2)
        client = MockHTTPClient()
        export_to_agent_endpoint(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://example.com/ingest",
            api_key="tok",
            _client=client,
        )
        payload = json.loads(client.requests[0]["content"])
        assert payload["knowledge_base"] == "test-kb"
        assert payload["batch_index"] == 0
        assert payload["total_batches"] == 1
        assert len(payload["chunks"]) == 2
        assert "chunk_id" in payload["chunks"][0]
        assert "text" in payload["chunks"][0]

    def test_batching_creates_multiple_requests(self, mem_session) -> None:
        _seed(mem_session, chunk_count=5)
        client = MockHTTPClient()
        report = export_to_agent_endpoint(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://example.com/ingest",
            api_key="tok",
            batch_size=2,
            _client=client,
        )
        assert report.batch_count == 3
        assert report.delivered_batches == 3
        assert len(client.requests) == 3

    def test_failed_batch_counted(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        client = MockHTTPClient(status_code=500)
        report = export_to_agent_endpoint(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://example.com/ingest",
            api_key="tok",
            _client=client,
        )
        assert report.failed_batches == 1
        assert report.delivered_batches == 0


class TestHMAC:
    def test_hmac_header_present_when_secret_configured(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        client = MockHTTPClient()
        export_to_agent_endpoint(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://example.com/ingest",
            api_key="tok",
            hmac_secret="my-secret",
            _client=client,
        )
        assert "X-Signature-256" in client.requests[0]["headers"]

    def test_hmac_signature_is_correct(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        client = MockHTTPClient()
        export_to_agent_endpoint(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://example.com/ingest",
            api_key="tok",
            hmac_secret="my-secret",
            _client=client,
        )
        payload_bytes = client.requests[0]["content"]
        expected = "sha256=" + hmac.new(b"my-secret", payload_bytes, hashlib.sha256).hexdigest()
        assert client.requests[0]["headers"]["X-Signature-256"] == expected

    def test_no_hmac_header_when_no_secret(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        client = MockHTTPClient()
        export_to_agent_endpoint(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://example.com/ingest",
            api_key="tok",
            _client=client,
        )
        assert "X-Signature-256" not in client.requests[0]["headers"]


class TestErrorHandling:
    def test_missing_knowledge_base_raises(self, mem_session) -> None:
        with pytest.raises(ValueError, match="not found"):
            export_to_agent_endpoint(
                mem_session,
                knowledge_base_name="does-not-exist",
                endpoint_url="https://example.com/ingest",
                api_key="tok",
            )

    def test_missing_env_var_raises(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        with pytest.raises(ValueError, match="MISSING_KEY"):
            export_to_agent_endpoint(
                mem_session,
                knowledge_base_name="test-kb",
                endpoint_url="https://example.com/ingest",
                api_key="env:MISSING_KEY",
                env={},
            )
