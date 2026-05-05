from __future__ import annotations

from collections.abc import Callable


class ManualCheckcodeSource:
    """Prompts for a code via synchronous callback (e.g. ``input``)."""

    def __init__(self, *, on_request: Callable[[str], str]) -> None:
        self._on_request = on_request

    def init(self) -> None:
        return

    def close(self) -> None:
        return

    def receive_code(self, email: str, *, timeout_sec: float = 300) -> str:
        hint = f"Email verification code for {email}"
        return self._on_request(hint).strip()
