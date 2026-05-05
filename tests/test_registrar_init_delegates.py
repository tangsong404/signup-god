"""Tracer bullet: registrar init delegates to CheckcodeSource.init (sync)."""

from __future__ import annotations

import pytest


class StubCheckcodeSource:
    def __init__(self) -> None:
        self.init_called = False
        self.close_called = False

    def init(self) -> None:
        self.init_called = True

    def close(self) -> None:
        self.close_called = True

    def receive_code(self, email: str, *, timeout_sec: float = 300) -> str:
        raise AssertionError("not used in this test")


def test_registrar_init_calls_checkcode_source_init_sync(deepseek_config) -> None:
    from registrars.deepseek.registrar import DeepSeekRegistrar

    src = StubCheckcodeSource()
    reg = DeepSeekRegistrar(checkcode_source=src, config=deepseek_config)
    assert not src.init_called
    reg.init()
    assert src.init_called
