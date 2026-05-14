from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
SQLITE_RESOURCEWARNING_PATTERN = re.compile(r"sqlite|sqlite3|ResourceWarning", re.IGNORECASE)
SUPPRESSION_ACTION_PATTERN = re.compile(r"^\s*ignore\s*:", re.IGNORECASE)


def load_pytest_filterwarnings() -> list[str]:
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    return (
        pyproject.get("tool", {})
        .get("pytest", {})
        .get("ini_options", {})
        .get(
            "filterwarnings",
            [],
        )
    )


def find_sqlite_resourcewarning_filters(filterwarnings: list[str]) -> list[str]:
    return [
        entry
        for entry in filterwarnings
        if SUPPRESSION_ACTION_PATTERN.search(entry) and SQLITE_RESOURCEWARNING_PATTERN.search(entry)
    ]


def main() -> int:
    sqlite_filters = find_sqlite_resourcewarning_filters(load_pytest_filterwarnings())
    payload = {
        "filterwarnings": sqlite_filters,
        "has_sqlite_resourcewarning_suppression": bool(sqlite_filters),
        "status": "ok" if not sqlite_filters else "failure",
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not sqlite_filters else 1


if __name__ == "__main__":
    raise SystemExit(main())
