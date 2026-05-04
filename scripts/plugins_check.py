from __future__ import annotations

import argparse
import json
from typing import Any

from ragrig.plugins import get_plugin_registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Show plugin registry status.")
    parser.add_argument(
        "--format",
        choices=("json",),
        default="json",
        help="Output format. JSON is the only supported offline format in this phase.",
    )
    return parser


def build_payload() -> dict[str, list[dict[str, Any]]]:
    return {"items": get_plugin_registry().list_discovery()}


def main() -> int:
    build_parser().parse_args()
    print(json.dumps(build_payload(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
