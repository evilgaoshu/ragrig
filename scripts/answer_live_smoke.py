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

from ragrig.answer.diagnostics import generate_diagnostics_artifact


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run answer live smoke diagnostics and emit JSON artifact."
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Output path for the JSON artifact. "
            "Defaults to docs/operations/artifacts/answer-live-smoke.json"
        ),
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


def main() -> int:
    args = build_parser().parse_args()

    output_path = Path(args.output) if args.output else None

    artifact = generate_diagnostics_artifact(
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        output_path=output_path,
    )

    indent = 2 if args.pretty else None
    json_output = json.dumps(artifact, indent=indent, ensure_ascii=False, sort_keys=True)
    print(json_output)

    print(f"\nArtifact written to {artifact['report_path']}", file=sys.stderr)

    # Exit codes: 0 for healthy/degraded/skip, 1 for error
    status = artifact.get("status", "error")
    return 0 if status in ("healthy", "degraded", "skip") else 1


if __name__ == "__main__":
    raise SystemExit(main())
