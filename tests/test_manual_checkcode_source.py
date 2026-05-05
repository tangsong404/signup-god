"""Manual checkcode source uses callback (grill 3A)."""

from __future__ import annotations


def test_manual_source_receive_code_invokes_callback() -> None:
    from checkcode.manual import ManualCheckcodeSource

    seen: list[tuple[str, str]] = []

    def on_request(hint: str) -> str:
        seen.append(("hint", hint))
        return " 197097 "

    src = ManualCheckcodeSource(on_request=on_request)
    src.init()
    code = src.receive_code("a@b.com", timeout_sec=1.0)
    assert code == "197097"
    assert seen and "a@b.com" in seen[0][1]
