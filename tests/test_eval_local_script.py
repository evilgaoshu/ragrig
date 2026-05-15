from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from scripts import eval_local


def test_eval_local_ephemeral_sqlite_supports_baseline_diff(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    golden_path = repo_root / "tests" / "fixtures" / "evaluation_golden.yaml"
    ingest_root = repo_root / "tests" / "fixtures" / "local_ingestion"
    baseline_path = tmp_path / "baseline.json"
    store_dir = tmp_path / "runs"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval_local.py",
            "--ephemeral-sqlite",
            "--golden",
            str(golden_path),
            "--ingest-root",
            str(ingest_root),
            "--store-dir",
            str(store_dir),
            "--output",
            str(baseline_path),
        ],
    )
    first_rc = eval_local.main()
    first_report = json.loads(capsys.readouterr().out)

    assert first_rc == 0
    assert first_report["status"] == "completed"
    assert first_report["metrics"]["total_questions"] >= 6
    assert baseline_path.exists()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval_local.py",
            "--ephemeral-sqlite",
            "--golden",
            str(golden_path),
            "--ingest-root",
            str(ingest_root),
            "--store-dir",
            str(store_dir),
            "--baseline",
            str(baseline_path),
        ],
    )
    second_rc = eval_local.main()
    second_report = json.loads(capsys.readouterr().out)

    assert second_rc == 0
    delta = second_report["metrics"]["regression_delta_vs_baseline"]
    assert isinstance(delta["hit_at_1"], int | float)
    assert isinstance(delta["mrr"], int | float)
    assert isinstance(delta["hit_at_5"], int | float)


def test_makefile_eval_local_target_uses_ephemeral_sqlite() -> None:
    makefile_path = Path(__file__).resolve().parents[1] / "Makefile"
    makefile = makefile_path.read_text(encoding="utf-8")

    match = re.search(
        r"^eval-local:\n(?P<recipe>\t.*scripts\.eval_local.*)$",
        makefile,
        re.MULTILINE,
    )

    assert match is not None
    recipe = match.group("recipe")
    assert recipe.startswith("\t@")
    assert "--ephemeral-sqlite" in recipe
