"""Registrar close forwards to CheckcodeSource.close first."""

from __future__ import annotations


class OrderStubCheckcodeSource:
    def __init__(self) -> None:
        self.events: list[str] = []

    def init(self) -> None:
        self.events.append("init")

    def close(self) -> None:
        self.events.append("source_close")

    def receive_code(self, email: str, *, timeout_sec: float = 300) -> str:
        return "000000"


def test_registrar_close_calls_source_close(deepseek_config) -> None:
    from registrars.deepseek.registrar import DeepSeekRegistrar

    src = OrderStubCheckcodeSource()
    reg = DeepSeekRegistrar(checkcode_source=src, config=deepseek_config)
    reg.init()
    reg.close()
    assert "source_close" in src.events
