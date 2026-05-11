from __future__ import annotations

import subprocess

from scripts import test_live_fileshare


def test_docker_compose_helpers_target_only_fileshare_services(monkeypatch) -> None:
    commands: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        del kwargs
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(test_live_fileshare, "_run", _fake_run)

    up_result = test_live_fileshare._docker_compose_up()
    down_result = test_live_fileshare._docker_compose_down()

    expected_up = [
        "docker",
        "compose",
        "--profile",
        "fileshare-live",
        "up",
        "-d",
        "--wait",
        "samba",
        "webdav",
        "sftp",
    ]
    expected_down = [
        "docker",
        "compose",
        "--profile",
        "fileshare-live",
        "down",
        "--remove-orphans",
        "samba",
        "webdav",
        "sftp",
    ]

    assert commands == [expected_up, expected_down]
    assert up_result["cmd"] == " ".join(expected_up)
    assert down_result["cmd"] == " ".join(expected_down)
