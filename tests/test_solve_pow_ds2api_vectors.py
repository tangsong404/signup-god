"""Vectors from ds2api pow/deepseek_pow_test.go (TestSolvePow)."""

from __future__ import annotations

import pytest

from registrars.deepseek.pow import build_prefix, hash_prefix_plus_nonce, solve_pow


@pytest.mark.parametrize(
    ("salt", "expire", "answer", "diff"),
    [
        ("testsalt", 1_700_000_000, 42, 1000),
        ("testsalt", 1_700_000_000, 500, 2000),
        ("abc123salt", 1_700_000_000, 12_345, 20_000),
    ],
)
def test_solve_pow_matches_ds2api(salt: str, expire: int, answer: int, diff: int) -> None:
    pfx = build_prefix(salt, expire)
    ch = hash_prefix_plus_nonce(pfx, answer).hex()
    got = solve_pow(ch, salt, expire, diff)
    assert got == answer
