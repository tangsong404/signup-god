"""Minimal CLI (12A): register subcommand parses required flags."""

from __future__ import annotations

import pytest


def test_register_subcommand_requires_email_and_password_flags() -> None:
    from registrars.deepseek.cli import build_parser

    p = build_parser()
    with pytest.raises(SystemExit):
        p.parse_args(["register"])

    with pytest.raises(SystemExit):
        p.parse_args(["register", "--email", "a@b.com"])

    args = p.parse_args(["register", "--email", "a@b.com", "--password", "x"])
    assert args.email == "a@b.com"
    assert args.password == "x"


def test_main_register_runs_send_wait_sign(monkeypatch: pytest.MonkeyPatch) -> None:
    from registrars.deepseek import cli

    monkeypatch.setenv("DEEPSEEK_DEVICE_ID", "cli-device")

    events: list[str] = []

    class StubRegistrar:
        def __init__(self, *, checkcode_source, config) -> None:
            events.append("ctor")
            assert config.device_id == "cli-device"

        def init(self) -> None:
            events.append("init")

        def send_email_code(self, email: str) -> None:
            events.append(f"send:{email}")

        def wait_checkcode(self, email: str, *, timeout_sec: float = 300) -> str:
            events.append(f"wait:{email}")
            return "654321"

        def sign(self, email: str, password: str, email_verification_code: str) -> dict:
            events.append(f"sign:{email}:{password}:{email_verification_code}")
            return {"ok": True}

        def close(self) -> None:
            events.append("close")

    class StubManual:
        def __init__(self, *, on_request) -> None:
            pass

        def init(self) -> None:
            pass

        def close(self) -> None:
            pass

        def receive_code(self, email: str, *, timeout_sec: float = 300) -> str:
            return "654321"

    monkeypatch.setattr(cli, "DeepSeekRegistrar", StubRegistrar)
    monkeypatch.setattr(cli, "ManualCheckcodeSource", StubManual)

    assert cli.main(["register", "--email", "a@b.com", "--password", "secret"]) == 0
    assert events == [
        "ctor",
        "init",
        "send:a@b.com",
        "wait:a@b.com",
        "sign:a@b.com:secret:654321",
        "close",
    ]
