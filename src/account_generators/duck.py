"""DuckDuckGo private @duck.com address producer (quack API)."""

from __future__ import annotations

import json
import sys

import httpx

QUACK_URL = "https://quack.duckduckgo.com/api/email/addresses"


def fetch_one_duck_address(*, token: str, client: httpx.Client | None = None) -> str:
    """Allocate one new private address. Returns ``local@duck.com``."""
    own = client is None
    c = client or httpx.Client()
    try:
        r = c.post(
            QUACK_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={},
            timeout=30.0,
        )
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(str(data.get("error", "unknown_error")))
        local = data.get("address")
        if not local or not isinstance(local, str):
            raise RuntimeError(f"unexpected_response:{json.dumps(data)[:200]}")
        return f"{local}@duck.com"
    finally:
        if own:
            c.close()


class DuckEmailAccountGenerator:
    """One ``next_identifier()`` call allocates one new ``local@duck.com`` address."""

    __slots__ = ("_client", "_token")

    def __init__(self, *, token: str, client: httpx.Client) -> None:
        self._token = token
        self._client = client

    def next_identifier(self) -> str:
        email = fetch_one_duck_address(token=self._token, client=self._client)
        sys.stderr.write(f"[duckemail_generator] {email}\n")
        sys.stderr.flush()
        return email
