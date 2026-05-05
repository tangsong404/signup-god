from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CheckcodeSource(Protocol):
    """Pluggable mailbox / manual input for DeepSeek email verification codes."""

    def init(self) -> None:
        """Sync blocking setup (e.g. QQ mailbox login)."""

    def close(self) -> None:
        """Release resources acquired in init."""

    def receive_code(self, email: str, *, timeout_sec: float = 300) -> str:
        """Block until a verification code is available for this email."""
