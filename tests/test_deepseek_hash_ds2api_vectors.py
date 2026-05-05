"""Vectors from ds2api pow/deepseek_pow_test.go (TestDeepSeekHashV1)."""

from __future__ import annotations

import pytest

from registrars.deepseek.hash import deepseek_hash_v1


@pytest.mark.parametrize(
    ("data", "want_hex"),
    [
        (
            "",
            "e594808bc5b7151ac160c6d39a02e0a8e261ed588578403099e3561dc40c26b3",
        ),
        (
            "testsalt_1700000000_42",
            "d4a2ea58c89e40887c933484868380c6f803eaa8dc53a3b9df8e431b921a4f09",
        ),
        (
            "testsalt_1700000000_100000",
            "abea2f35796b65486e9be1b36f7878c66cab021e96faa473fdf4decd31f9ba30",
        ),
        (
            "abc123salt_1700000000_12345",
            "74b3b7452745b70e85eb32ee7f0a9ec0381d42dd5137b695da915e104fc390e1",
        ),
    ],
)
def test_deepseek_hash_v1_matches_ds2api(data: str, want_hex: str) -> None:
    got = deepseek_hash_v1(data.encode("utf-8")).hex()
    assert got == want_hex
