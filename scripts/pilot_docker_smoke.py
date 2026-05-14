from __future__ import annotations

import argparse
import json
import os
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class PilotDockerSmokeError(RuntimeError):
    pass


def _read_response(request: Request, *, timeout_seconds: float) -> tuple[int, str, str]:
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            body = response.read().decode("utf-8")
            content_type = response.headers.get("Content-Type", "")
            return response.status, content_type, body
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise PilotDockerSmokeError(f"{request.full_url} returned {exc.code}: {body}") from exc
    except URLError as exc:
        raise PilotDockerSmokeError(f"{request.full_url} failed: {exc.reason}") from exc


def _get_json(url: str, *, timeout_seconds: float) -> dict[str, Any]:
    status, _content_type, body = _read_response(
        Request(url, headers={"Accept": "application/json"}),
        timeout_seconds=timeout_seconds,
    )
    if status != 200:
        raise PilotDockerSmokeError(f"{url} returned {status}")
    return json.loads(body)


def _post_json(url: str, payload: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    status, _content_type, response_body = _read_response(
        Request(
            url,
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        ),
        timeout_seconds=timeout_seconds,
    )
    if status != 200:
        raise PilotDockerSmokeError(f"{url} returned {status}")
    return json.loads(response_body)


def _get_text(url: str, *, timeout_seconds: float) -> str:
    status, _content_type, body = _read_response(
        Request(url, headers={"Accept": "text/html"}),
        timeout_seconds=timeout_seconds,
    )
    if status != 200:
        raise PilotDockerSmokeError(f"{url} returned {status}")
    return body


def _wait_for_health(
    base_url: str,
    *,
    timeout_seconds: float,
    interval_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            health = _get_json(f"{base_url}/health", timeout_seconds=min(interval_seconds, 5.0))
            if health.get("status") == "healthy":
                return health
            last_error = PilotDockerSmokeError(f"health status is {health.get('status')!r}")
        except Exception as exc:  # pragma: no cover - loop behavior covered by success path
            last_error = exc
        time.sleep(interval_seconds)
    raise PilotDockerSmokeError(f"timed out waiting for healthy app: {last_error}")


def run_smoke(
    base_url: str,
    *,
    timeout_seconds: float = 60.0,
    interval_seconds: float = 2.0,
) -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    health = _wait_for_health(
        base_url,
        timeout_seconds=timeout_seconds,
        interval_seconds=interval_seconds,
    )
    console_html = _get_text(f"{base_url}/console", timeout_seconds=10.0)
    if "RAGRig Web Console" not in console_html or "Local Pilot" not in console_html:
        raise PilotDockerSmokeError("console response does not contain the Local Pilot console")

    status = _get_json(f"{base_url}/local-pilot/status", timeout_seconds=10.0)
    extensions = status.get("upload", {}).get("extensions", [])
    for required_extension in (".md", ".txt", ".pdf", ".docx"):
        if required_extension not in extensions:
            raise PilotDockerSmokeError(
                f"local pilot status is missing {required_extension} upload support"
            )

    answer_smoke = _post_json(
        f"{base_url}/local-pilot/answer-smoke",
        {"provider": "deterministic-local"},
        timeout_seconds=10.0,
    )
    if answer_smoke.get("status") != "healthy":
        raise PilotDockerSmokeError(
            f"answer smoke returned {answer_smoke.get('status')!r}: {answer_smoke}"
        )

    return {
        "base_url": base_url,
        "health": health,
        "console": {"contains_local_pilot": True},
        "local_pilot_status": status,
        "answer_smoke": answer_smoke,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test a Dockerized RAGRig Local Pilot.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("PILOT_BASE_URL")
        or f"http://127.0.0.1:{os.environ.get('APP_HOST_PORT', '8000')}",
    )
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--interval-seconds", type=float, default=2.0)
    args = parser.parse_args()

    result = run_smoke(
        args.base_url,
        timeout_seconds=args.timeout_seconds,
        interval_seconds=args.interval_seconds,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
