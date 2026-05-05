"""with exits call close; __enter__ does not auto-init (11A)."""

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


def test_with_exits_calls_close_after_enter_without_auto_init(deepseek_config) -> None:
    from registrars.deepseek.registrar import DeepSeekRegistrar

    src = OrderStubCheckcodeSource()
    reg = DeepSeekRegistrar(checkcode_source=src, config=deepseek_config)
    reg.init()
    with reg:
        assert "source_close" not in src.events
    assert src.events[-1] == "source_close"
