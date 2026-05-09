from __future__ import annotations

import pytest

from scripts.plugins_check import build_payload

pytestmark = pytest.mark.unit


def test_plugins_check_payload_exposes_registry_items() -> None:
    payload = build_payload()

    assert "items" in payload
    assert any(item["plugin_id"] == "source.local" for item in payload["items"])
    assert any(item["plugin_id"] == "source.s3" for item in payload["items"])
    assert any(item["plugin_id"] == "source.fileshare" for item in payload["items"])
    assert any(item["plugin_id"] == "sink.object_storage" for item in payload["items"])
    assert any(item["plugin_id"] == "model.ollama" for item in payload["items"])
    assert any(item["plugin_id"] == "model.openai" for item in payload["items"])
