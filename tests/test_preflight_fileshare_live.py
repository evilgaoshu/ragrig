from __future__ import annotations

from scripts import preflight_fileshare_live


def test_run_checks_does_not_require_env_file_for_fileshare_only_services(monkeypatch) -> None:
    monkeypatch.setattr(preflight_fileshare_live, "_docker_available", lambda: None)
    monkeypatch.setattr(preflight_fileshare_live, "_docker_compose_available", lambda: None)
    monkeypatch.setattr(preflight_fileshare_live, "_docker_daemon_running", lambda: None)
    monkeypatch.setattr(
        preflight_fileshare_live,
        "_ports_free",
        lambda ports, auto_pick: ([], ports),
    )
    monkeypatch.setattr(preflight_fileshare_live, "_optional_sdks", lambda: [])

    result = preflight_fileshare_live.run_checks()

    assert result["ok"] is True
    assert result["hard_blockers"] == []
    assert "env_file" not in result["checks"]
