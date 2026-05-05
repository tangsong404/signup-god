from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def _strip_env_value(raw: str) -> str:
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


@dataclass(frozen=True)
class DeepSeekConfig:
    """HTTP client settings for chat.deepseek.com registration APIs."""

    device_id: str
    turnstile_token: str = ""
    locale: str = "en_US"
    base_url: str = "https://chat.deepseek.com"
    app_version: str = "0.0.0"
    client_version: str = "1.0.0"
    client_platform: str = "web"
    timezone_offset_minutes: int = 300
    region: str = "US"

    @classmethod
    def from_env(cls) -> DeepSeekConfig:
        load_dotenv(_ENV_PATH)
        device_id = _strip_env_value(os.environ.get("DEEPSEEK_DEVICE_ID", ""))
        if not device_id:
            msg = "DEEPSEEK_DEVICE_ID is required in .env (non-empty)."
            raise ValueError(msg)
        return cls(
            device_id=device_id,
            turnstile_token="",
            locale="en_US",
            base_url="https://chat.deepseek.com",
            app_version="0.0.0",
            client_version="1.0.0",
            client_platform="web",
            timezone_offset_minutes=300,
            region="US",
        )
