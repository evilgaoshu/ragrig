from __future__ import annotations

import json
from pathlib import Path

FIXTURE_ROOT = Path("tests/fixtures/acl_phase2")


def main() -> None:
    FIXTURE_ROOT.mkdir(parents=True, exist_ok=True)
    (FIXTURE_ROOT / "kb-engineering").mkdir(exist_ok=True)
    (FIXTURE_ROOT / "kb-finance").mkdir(exist_ok=True)
    (FIXTURE_ROOT / "kb-engineering" / "public.txt").write_text(
        "shared roadmap permissions fixture\n", encoding="utf-8"
    )
    (FIXTURE_ROOT / "kb-engineering" / "engineering.txt").write_text(
        "engineering runway private fixture\n", encoding="utf-8"
    )
    (FIXTURE_ROOT / "kb-finance" / "finance.txt").write_text(
        "finance runway private fixture\n", encoding="utf-8"
    )
    manifest = {
        "principals": [
            {"user_id": "alice", "groups": ["engineering"]},
            {"user_id": "bob", "groups": ["finance"]},
        ],
        "knowledge_bases": ["acl-engineering", "acl-finance"],
    }
    (FIXTURE_ROOT / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"seeded {FIXTURE_ROOT}")


if __name__ == "__main__":
    main()
