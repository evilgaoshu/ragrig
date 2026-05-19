"""Unit tests for the webhook sink connector."""

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
from ragrig.plugins.sinks.webhook.connector import (
    export_to_webhook,
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
    def test_dry_run_counts_chunks_without_sending(self, mem_session) -> None:
        _seed(mem_session, chunk_count=4)
        report = export_to_webhook(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://hook.example.com/recv",
            dry_run=True,
        )
        assert report.dry_run is True
        assert report.chunk_count == 4
        assert report.delivered_batches == 0

    def test_dry_run_no_http_calls(self, mem_session) -> None:
        _seed(mem_session, chunk_count=2)
        client = MockHTTPClient()
        export_to_webhook(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://hook.example.com/recv",
            dry_run=True,
            _client=client,
        )
        assert client.requests == []


class TestNDJSON:
    def test_ndjson_content_type(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        client = MockHTTPClient()
        export_to_webhook(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://hook.example.com/recv",
            format="ndjson",
            _client=client,
        )
        assert client.requests[0]["headers"]["Content-Type"] == "application/x-ndjson"

    def test_ndjson_each_line_is_valid_json(self, mem_session) -> None:
        _seed(mem_session, chunk_count=3)
        client = MockHTTPClient()
        export_to_webhook(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://hook.example.com/recv",
            format="ndjson",
            _client=client,
        )
        lines = [
            line for line in client.requests[0]["content"].decode().splitlines() if line.strip()
        ]
        assert len(lines) == 3
        for line in lines:
            obj = json.loads(line)
            assert "chunk_id" in obj
            assert "text" in obj


class TestJSONFormat:
    def test_json_content_type(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        client = MockHTTPClient()
        export_to_webhook(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://hook.example.com/recv",
            format="json",
            _client=client,
        )
        assert client.requests[0]["headers"]["Content-Type"] == "application/json"

    def test_json_payload_is_array(self, mem_session) -> None:
        _seed(mem_session, chunk_count=2)
        client = MockHTTPClient()
        export_to_webhook(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://hook.example.com/recv",
            format="json",
            _client=client,
        )
        payload = json.loads(client.requests[0]["content"])
        assert isinstance(payload, list)
        assert len(payload) == 2


class TestBatching:
    def test_batch_size_splits_requests(self, mem_session) -> None:
        _seed(mem_session, chunk_count=5)
        client = MockHTTPClient()
        report = export_to_webhook(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://hook.example.com/recv",
            batch_size=2,
            _client=client,
        )
        assert report.batch_count == 3
        assert report.delivered_batches == 3
        assert len(client.requests) == 3

    def test_failed_requests_counted(self, mem_session) -> None:
        _seed(mem_session, chunk_count=2)
        client = MockHTTPClient(status_code=503)
        report = export_to_webhook(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://hook.example.com/recv",
            _client=client,
        )
        assert report.failed_batches == 1
        assert report.delivered_batches == 0


class TestHMAC:
    def test_hmac_header_present_when_secret_given(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        client = MockHTTPClient()
        export_to_webhook(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://hook.example.com/recv",
            hmac_secret="webhook-secret",
            _client=client,
        )
        assert "X-Signature-256" in client.requests[0]["headers"]

    def test_hmac_signature_verifies(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        client = MockHTTPClient()
        export_to_webhook(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://hook.example.com/recv",
            hmac_secret="webhook-secret",
            _client=client,
        )
        payload_bytes = client.requests[0]["content"]
        expected = (
            "sha256=" + hmac.new(b"webhook-secret", payload_bytes, hashlib.sha256).hexdigest()
        )
        assert client.requests[0]["headers"]["X-Signature-256"] == expected

    def test_hmac_from_env(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        client = MockHTTPClient()
        export_to_webhook(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://hook.example.com/recv",
            hmac_secret="env:WEBHOOK_SECRET",
            env={"WEBHOOK_SECRET": "resolved-secret"},
            _client=client,
        )
        assert "X-Signature-256" in client.requests[0]["headers"]

    def test_no_hmac_when_no_secret(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        client = MockHTTPClient()
        export_to_webhook(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://hook.example.com/recv",
            _client=client,
        )
        assert "X-Signature-256" not in client.requests[0]["headers"]


class TestExtraHeaders:
    def test_extra_headers_included(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        client = MockHTTPClient()
        export_to_webhook(
            mem_session,
            knowledge_base_name="test-kb",
            endpoint_url="https://hook.example.com/recv",
            extra_headers={"X-Custom-Header": "value42"},
            _client=client,
        )
        assert client.requests[0]["headers"]["X-Custom-Header"] == "value42"


class TestErrorHandling:
    def test_missing_knowledge_base_raises(self, mem_session) -> None:
        with pytest.raises(ValueError, match="not found"):
            export_to_webhook(
                mem_session,
                knowledge_base_name="no-such-kb",
                endpoint_url="https://hook.example.com/recv",
            )

    def test_invalid_format_raises(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        with pytest.raises(ValueError, match="format"):
            export_to_webhook(
                mem_session,
                knowledge_base_name="test-kb",
                endpoint_url="https://hook.example.com/recv",
                format="xml",
            )
