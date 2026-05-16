from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class VercelPreviewSmokeError(RuntimeError):
    pass


def _read_response(request: Request, *, timeout_seconds: float) -> tuple[int, str, str]:
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            return (
                response.status,
                response.headers.get("Content-Type", ""),
                response.read().decode("utf-8"),
            )
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise VercelPreviewSmokeError(f"{request.full_url} returned {exc.code}: {body}") from exc
    except URLError as exc:
        raise VercelPreviewSmokeError(f"{request.full_url} failed: {exc.reason}") from exc


def _get_json(url: str, *, timeout_seconds: float) -> dict[str, Any]:
    status, _content_type, body = _read_response(
        Request(url, headers={"Accept": "application/json"}),
        timeout_seconds=timeout_seconds,
    )
    if status != 200:
        raise VercelPreviewSmokeError(f"{url} returned {status}")
    return json.loads(body)


def _get_text(url: str, *, timeout_seconds: float) -> str:
    status, _content_type, body = _read_response(
        Request(url, headers={"Accept": "text/html"}),
        timeout_seconds=timeout_seconds,
    )
    if status != 200:
        raise VercelPreviewSmokeError(f"{url} returned {status}")
    return body


def run_smoke(base_url: str, *, timeout_seconds: float = 15.0) -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    health = _get_json(f"{base_url}/health", timeout_seconds=timeout_seconds)
    if health.get("status") != "healthy":
        raise VercelPreviewSmokeError(f"preview health is not healthy: {health}")

    console_html = _get_text(f"{base_url}/console", timeout_seconds=timeout_seconds)
    if "RAGRig Web Console" not in console_html or "Local Pilot" not in console_html:
        raise VercelPreviewSmokeError("preview console does not contain the Local Pilot console")

    local_pilot_status = _get_json(
        f"{base_url}/local-pilot/status",
        timeout_seconds=timeout_seconds,
    )
    return {
        "base_url": base_url,
        "health": health,
        "console": {"contains_local_pilot": True},
        "local_pilot_status": local_pilot_status,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke test a RAGRig Vercel Preview URL.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("VERCEL_PREVIEW_URL"),
        help="Preview deployment URL. Defaults to VERCEL_PREVIEW_URL.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.base_url:
        raise SystemExit("VERCEL_PREVIEW_URL or --base-url is required")
    result = run_smoke(args.base_url, timeout_seconds=args.timeout_seconds)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
