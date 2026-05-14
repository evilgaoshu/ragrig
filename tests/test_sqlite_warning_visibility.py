from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from scripts.sqlite_warning_check import find_sqlite_resourcewarning_filters

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_makefile_exposes_sqlite_warning_visibility_check_target() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "sqlite-warning-check:" in makefile
    assert "python -m scripts.sqlite_warning_check" in makefile


def test_sqlite_warning_check_reports_no_sqlite_suppression_filters() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "scripts.sqlite_warning_check"],
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
        text=True,
    )

    assert result.returncode == 0, result.stderr

    payload = json.loads(result.stdout)

    assert payload == {
        "filterwarnings": [],
        "has_sqlite_resourcewarning_suppression": False,
        "status": "ok",
    }


def test_sqlite_warning_check_only_flags_ignore_filters() -> None:
    filterwarnings = [
        "error::ResourceWarning",
        "always::ResourceWarning",
        "ignore:unclosed database in <sqlite3.Connection object:ResourceWarning",
    ]

    assert find_sqlite_resourcewarning_filters(filterwarnings) == [
        "ignore:unclosed database in <sqlite3.Connection object:ResourceWarning"
    ]


def test_pyproject_has_no_sqlite_resourcewarning_ignore_filters() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    filterwarnings = pyproject.get("tool", {}).get("pytest", {}).get("ini_options", {}).get(
        "filterwarnings",
        [],
    )

    assert find_sqlite_resourcewarning_filters(filterwarnings) == []
