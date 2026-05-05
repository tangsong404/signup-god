from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AccountIdentifierGenerator(Protocol):
    """Call ``next_identifier()`` once per new account to obtain a signup id (e.g. email)."""

    def next_identifier(self) -> str: ...
