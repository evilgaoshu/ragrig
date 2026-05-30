from __future__ import annotations

from typing import Any

from ragrig.acl import acl_summary_from_metadata


async def answer_sse_stream(payload: dict[str, Any]):
    import asyncio
    import json

    answer = payload.get("answer") or ""
    size = 12
    pieces = [answer[i : i + size] for i in range(0, len(answer), size)] or [""]
    for piece in pieces:
        yield "event: delta\n"
        yield f"data: {json.dumps({'text': piece})}\n\n"
        await asyncio.sleep(0)

    final_meta = {
        "citations": payload.get("citations", []),
        "evidence_chunks": payload.get("evidence_chunks", []),
        "model": payload.get("model"),
        "provider": payload.get("provider"),
        "grounding_status": payload.get("grounding_status"),
        "refusal_reason": payload.get("refusal_reason"),
        "retrieval_trace": payload.get("retrieval_trace", {}),
    }
    yield "event: done\n"
    yield f"data: {json.dumps(final_meta)}\n\n"
    yield "data: [DONE]\n\n"


def safe_chunk_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    safe = dict(metadata or {})
    if "acl" in safe:
        safe["acl"] = acl_summary_from_metadata(metadata)
    return safe
