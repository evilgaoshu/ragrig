"""Browser-level smoke for the external Graph Console demo loop."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn

from ragrig.config import Settings
from ragrig.main import create_app
from scripts.demo_graph_console_runbook import (
    DEFAULT_MARKDOWN_OUTPUT,
    DEFAULT_OUTPUT,
    _sqlite_url,
    run_demo_graph_console_runbook,
)
from scripts.demo_rc_gate import DEFAULT_KNOWLEDGE_BASE
from scripts.demo_rc_gate import DEFAULT_MARKDOWN_OUTPUT as DEFAULT_DEMO_RC_MARKDOWN
from scripts.demo_rc_gate import DEFAULT_OUTPUT as DEFAULT_DEMO_RC_OUTPUT


class DemoGraphConsoleSmokeError(RuntimeError):
    pass


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_server(base_url: str, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{base_url}/health", timeout=1.0)
            if response.status_code == 200:
                return
        except Exception as exc:  # pragma: no cover - depends on process timing
            last_error = exc
        time.sleep(0.2)
    raise DemoGraphConsoleSmokeError(f"server did not become ready: {last_error}")


def _run_playwright(
    *,
    base_url: str,
    knowledge_base: str,
    headed: bool,
    timeout_ms: int,
) -> dict[str, Any]:
    if shutil.which("npx") is None:
        raise DemoGraphConsoleSmokeError("npx is required to run the browser smoke")
    if shutil.which("npm") is None:
        raise DemoGraphConsoleSmokeError("npm is required to install the Playwright package")

    spec = Path(__file__).with_suffix(".mjs")
    package = os.environ.get("RAGRIG_PLAYWRIGHT_NPM_PACKAGE", "playwright@1.56.1")
    env = os.environ.copy()
    env.update(
        {
            "RAGRIG_GRAPH_CONSOLE_SMOKE_BASE_URL": base_url,
            "RAGRIG_GRAPH_CONSOLE_SMOKE_KNOWLEDGE_BASE": knowledge_base,
            "RAGRIG_GRAPH_CONSOLE_SMOKE_HEADLESS": "0" if headed else "1",
            "RAGRIG_GRAPH_CONSOLE_SMOKE_TIMEOUT_MS": str(timeout_ms),
            "RAGRIG_GRAPH_CONSOLE_SMOKE_BROWSER_CHANNEL": os.environ.get(
                "RAGRIG_GRAPH_CONSOLE_SMOKE_BROWSER_CHANNEL", "chrome"
            ),
        }
    )

    with tempfile.TemporaryDirectory(prefix="ragrig-graph-console-smoke-node-") as node_dir:
        node_root = Path(node_dir)
        node_spec = node_root / spec.name
        shutil.copy2(spec, node_spec)

        install_package = subprocess.run(
            ["npm", "install", "--no-save", "--no-package-lock", package],
            cwd=node_root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        if install_package.returncode != 0:
            raise DemoGraphConsoleSmokeError(
                "failed to install Playwright package:\n"
                f"{install_package.stdout}\n{install_package.stderr}"
            )

        command = ["node", str(node_spec)]
        result = subprocess.run(
            command,
            cwd=node_root,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        combined_output = f"{result.stdout}\n{result.stderr}"
        browser_missing = (
            "Executable doesn't exist" in combined_output
            or "Chromium distribution 'chrome' is not found" in combined_output
        )
        if result.returncode != 0 and browser_missing:
            install_browser = subprocess.run(
                ["npx", "playwright", "install", "chromium"],
                cwd=node_root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            if install_browser.returncode != 0:
                raise DemoGraphConsoleSmokeError(
                    "failed to install Playwright Chromium:\n"
                    f"{install_browser.stdout}\n{install_browser.stderr}"
                )
            retry_env = dict(env)
            retry_env["RAGRIG_GRAPH_CONSOLE_SMOKE_BROWSER_CHANNEL"] = ""
            result = subprocess.run(
                command,
                cwd=node_root,
                env=retry_env,
                text=True,
                capture_output=True,
                check=False,
            )

    if result.returncode != 0:
        raise DemoGraphConsoleSmokeError(
            f"browser smoke failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return json.loads(result.stdout)


def run_smoke(
    *,
    database_path: Path,
    output: Path | None = None,
    headed: bool = False,
    timeout_ms: int = 30000,
    knowledge_base: str = DEFAULT_KNOWLEDGE_BASE,
) -> dict[str, Any]:
    port = _find_free_port()
    base_url = f"http://127.0.0.1:{port}"
    artifact_root = database_path.parent
    runbook = run_demo_graph_console_runbook(
        database_path=database_path,
        knowledge_base=knowledge_base,
        host="127.0.0.1",
        port=port,
        demo_rc_output=artifact_root / DEFAULT_DEMO_RC_OUTPUT.name,
        demo_rc_markdown_output=artifact_root / DEFAULT_DEMO_RC_MARKDOWN.name,
    )
    if runbook["status"] != "pass":
        raise DemoGraphConsoleSmokeError(
            f"demo runbook did not pass: {json.dumps(runbook['checks'], sort_keys=True)}"
        )
    runbook_output = artifact_root / DEFAULT_OUTPUT.name
    runbook_markdown_output = artifact_root / DEFAULT_MARKDOWN_OUTPUT.name
    runbook_output.write_text(json.dumps(runbook, indent=2, sort_keys=True), encoding="utf-8")
    runbook_markdown_output.write_text(runbook["markdown_summary"], encoding="utf-8")

    settings = Settings(
        database_url=_sqlite_url(database_path),
        app_host="127.0.0.1",
        app_port=port,
        ragrig_auth_enabled=False,
        ragrig_metrics_enabled=False,
    )
    app = create_app(check_database=lambda: None, settings=settings)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        _wait_for_server(base_url, timeout_ms / 1000)
        browser_result = _run_playwright(
            base_url=base_url,
            knowledge_base=knowledge_base,
            headed=headed,
            timeout_ms=timeout_ms,
        )
    finally:
        server.should_exit = True
        thread.join(timeout=10)

    result = {
        **browser_result,
        "runbook": {
            "status": runbook["status"],
            "check_count": len(runbook["checks"]),
            "failed_checks": [
                check["id"] for check in runbook["checks"] if check.get("status") != "pass"
            ],
        },
        "artifacts": {
            "database": str(database_path),
            "runbook_json": str(runbook_output),
            "runbook_markdown": str(runbook_markdown_output),
        },
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a browser-level Graph Console demo smoke.")
    parser.add_argument(
        "--database-path",
        type=Path,
        default=None,
        help="Optional SQLite database path. Defaults to a temporary file.",
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    parser.add_argument("--headed", action="store_true", help="Run Chromium headed.")
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=30000,
        help="Browser action timeout in milliseconds.",
    )
    parser.add_argument("--knowledge-base", default=DEFAULT_KNOWLEDGE_BASE)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.database_path is not None:
        result = run_smoke(
            database_path=args.database_path,
            output=args.output,
            headed=args.headed,
            timeout_ms=args.timeout_ms,
            knowledge_base=args.knowledge_base,
        )
    else:
        with tempfile.TemporaryDirectory(prefix="ragrig-graph-console-smoke-") as temp_dir:
            result = run_smoke(
                database_path=Path(temp_dir) / "demo-graph-console-smoke.db",
                output=args.output,
                headed=args.headed,
                timeout_ms=args.timeout_ms,
                knowledge_base=args.knowledge_base,
            )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
