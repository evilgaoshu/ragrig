from __future__ import annotations

import json

from fastapi.testclient import TestClient

from ragrig.main import create_app


def main() -> None:
    client = TestClient(create_app(check_database=lambda: None))
    status = client.get("/local-pilot/status")
    status.raise_for_status()
    smoke = client.post(
        "/local-pilot/answer-smoke",
        json={"provider": "deterministic-local"},
    )
    smoke.raise_for_status()
    print(
        json.dumps(
            {
                "status": status.json(),
                "answer_smoke": smoke.json(),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
