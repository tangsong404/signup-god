"""DeepSeekConfig reads DEEPSEEK_DEVICE_ID from .env."""

from __future__ import annotations

import pytest


def _no_dotenv_files(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("registrars.deepseek.config.load_dotenv", lambda *a, **k: None)


def test_from_env_requires_device_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from registrars.deepseek.config import DeepSeekConfig

    _no_dotenv_files(monkeypatch)
    monkeypatch.delenv("DEEPSEEK_DEVICE_ID", raising=False)
    with pytest.raises(ValueError, match="DEEPSEEK_DEVICE_ID"):
        DeepSeekConfig.from_env()


def test_from_env_reads_device_id(monkeypatch: pytest.MonkeyPatch) -> None:
    from registrars.deepseek.config import DeepSeekConfig

    _no_dotenv_files(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_DEVICE_ID", "dev-device")
    cfg = DeepSeekConfig.from_env()
    assert cfg.device_id == "dev-device"
    assert cfg.locale == "en_US"
    assert cfg.region == "US"
    assert cfg.timezone_offset_minutes == 300
    assert cfg.turnstile_token == ""
    assert cfg.base_url == "https://chat.deepseek.com"


def test_from_env_strips_quotes(monkeypatch: pytest.MonkeyPatch) -> None:
    from registrars.deepseek.config import DeepSeekConfig

    _no_dotenv_files(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_DEVICE_ID", '"quoted-id"')
    cfg = DeepSeekConfig.from_env()
    assert cfg.device_id == "quoted-id"
