"""Guest PoW parallel behavior with fixed workers."""

from __future__ import annotations

from registrars.deepseek.pow import build_prefix, hash_prefix_plus_nonce, solve_pow


def test_parallel_matches_sequential_vector() -> None:
    salt = "testsalt"
    exp = 1_700_000_000
    answer = 42
    pfx = build_prefix(salt, exp)
    ch = hash_prefix_plus_nonce(pfx, answer).hex()
    diff = 50_000
    assert solve_pow(ch, salt, exp, diff) == answer


def test_cancel_check_disables_parallel() -> None:
    salt = "testsalt"
    exp = 1_700_000_000
    answer = 42
    pfx = build_prefix(salt, exp)
    ch = hash_prefix_plus_nonce(pfx, answer).hex()
    diff = 50_000
    calls: list[int] = []

    def tick() -> None:
        calls.append(1)

    assert solve_pow(ch, salt, exp, diff, cancel_check=tick) == answer
    assert calls  # sequential path exercised cancel_check
