"""Answer live smoke test: JSON diagnostics for local LLM providers.

Usage:
    make answer-live-smoke
    uv run python -m scripts.answer_live_smoke
    uv run python -m scripts.answer_live_smoke --pretty
    uv run python -m scripts.answer_live_smoke \
        --output docs/operations/artifacts/answer-live-smoke.json

This script safely diagnoses local LLM providers (Ollama / LM Studio /
OpenAI-compatible) without crashing when optional dependencies are missing.

Exit codes:
    0  – healthy, degraded, or skip (expected outcomes)
    1  – error (unexpected failure)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ragrig.answer.diagnostics import AnswerDiagnosticsReport, run_answer_diagnostics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run answer live smoke diagnostics and emit JSON report."
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output path for the JSON diagnostic report.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON to stdout.",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Override provider name (default: env RAGRIG_ANSWER_PROVIDER or 'ollama').",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override model name (default: env RAGRIG_ANSWER_MODEL or 'llama3.2:1b').",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override base URL (default: env RAGRIG_ANSWER_BASE_URL or 'http://localhost:11434/v1').",
    )
    return parser


def _sanitize_result(result: dict) -> dict:
    """Remove any secret-like values from the result dict."""
    SECRET_KEY_PARTS = (
        "api_key",
        "access_key",
        "secret",
        "password",
        "token",
        "credential",
        "private_key",
        "dsn",
        "service_account",
        "session_token",
    )

    def _redact(obj):
        if isinstance(obj, dict):
            return {
                k: "[REDACTED]" if any(p in k.lower() for p in SECRET_KEY_PARTS) else _redact(v)
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [_redact(v) for v in obj]
        return obj

    return _redact(result)


def main() -> int:
    args = build_parser().parse_args()

    report: AnswerDiagnosticsReport = run_answer_diagnostics(
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
    )

    result = report.to_dict()
    result = _sanitize_result(result)

    indent = 2 if args.pretty else None
    json_output = json.dumps(result, indent=indent, ensure_ascii=False, sort_keys=True)
    print(json_output)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json_output, encoding="utf-8")
        print(f"\nAnswer live smoke report written to {output_path}", file=sys.stderr)

    return 0 if report.status in ("healthy", "degraded", "skip") else 1


if __name__ == "__main__":
    raise SystemExit(main())
