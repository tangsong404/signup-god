# SPDX-License-Identifier: CC0-1.0
# Algorithm ported from https://github.com/CJackHwang/ds2api (pow/deepseek_hash.go).
# DeepSeekHashV1 = SHA3-256 padding/rate, but Keccak-f[1600] runs rounds 1..23 only (skip round 0).

from __future__ import annotations

import struct
from typing import MutableSequence

_MASK = (1 << 64) - 1

_RC = (
    0x0000000000000001,
    0x0000000000008082,
    0x800000000000808A,
    0x8000000080008000,
    0x000000000000808B,
    0x0000000080000001,
    0x8000000080008081,
    0x8000000000008009,
    0x000000000000008A,
    0x0000000000000088,
    0x0000000080008009,
    0x000000008000000A,
    0x000000008000808B,
    0x800000000000008B,
    0x8000000000008089,
    0x8000000000008003,
    0x8000000000008002,
    0x8000000000000080,
    0x000000000000800A,
    0x800000008000000A,
    0x8000000080008081,
    0x8000000000008080,
    0x0000000080000001,
    0x8000000080008008,
)


def _u64(x: int) -> int:
    return x & _MASK


def _rotl64(v: int, k: int) -> int:
    k = k % 64
    return _u64((v << k) | (v >> (64 - k)))


def keccak_f23(s: MutableSequence[int]) -> None:
    a0, a1, a2, a3, a4 = s[0], s[1], s[2], s[3], s[4]
    a5, a6, a7, a8, a9 = s[5], s[6], s[7], s[8], s[9]
    a10, a11, a12, a13, a14 = s[10], s[11], s[12], s[13], s[14]
    a15, a16, a17, a18, a19 = s[15], s[16], s[17], s[18], s[19]
    a20, a21, a22, a23, a24 = s[20], s[21], s[22], s[23], s[24]

    for r in range(1, 24):
        c0 = a0 ^ a5 ^ a10 ^ a15 ^ a20
        c1 = a1 ^ a6 ^ a11 ^ a16 ^ a21
        c2 = a2 ^ a7 ^ a12 ^ a17 ^ a22
        c3 = a3 ^ a8 ^ a13 ^ a18 ^ a23
        c4 = a4 ^ a9 ^ a14 ^ a19 ^ a24
        d0 = c4 ^ _rotl64(c1, 1)
        d1 = c0 ^ _rotl64(c2, 1)
        d2 = c1 ^ _rotl64(c3, 1)
        d3 = c2 ^ _rotl64(c4, 1)
        d4 = c3 ^ _rotl64(c0, 1)
        a0 ^= d0
        a5 ^= d0
        a10 ^= d0
        a15 ^= d0
        a20 ^= d0
        a1 ^= d1
        a6 ^= d1
        a11 ^= d1
        a16 ^= d1
        a21 ^= d1
        a2 ^= d2
        a7 ^= d2
        a12 ^= d2
        a17 ^= d2
        a22 ^= d2
        a3 ^= d3
        a8 ^= d3
        a13 ^= d3
        a18 ^= d3
        a23 ^= d3
        a4 ^= d4
        a9 ^= d4
        a14 ^= d4
        a19 ^= d4
        a24 ^= d4

        b0 = a0
        b10 = _rotl64(a1, 1)
        b20 = _rotl64(a2, 62)
        b5 = _rotl64(a3, 28)
        b15 = _rotl64(a4, 27)
        b16 = _rotl64(a5, 36)
        b1 = _rotl64(a6, 44)
        b11 = _rotl64(a7, 6)
        b21 = _rotl64(a8, 55)
        b6 = _rotl64(a9, 20)
        b7 = _rotl64(a10, 3)
        b17 = _rotl64(a11, 10)
        b2 = _rotl64(a12, 43)
        b12 = _rotl64(a13, 25)
        b22 = _rotl64(a14, 39)
        b23 = _rotl64(a15, 41)
        b8 = _rotl64(a16, 45)
        b18 = _rotl64(a17, 15)
        b3 = _rotl64(a18, 21)
        b13 = _rotl64(a19, 8)
        b14 = _rotl64(a20, 18)
        b24 = _rotl64(a21, 2)
        b9 = _rotl64(a22, 61)
        b19 = _rotl64(a23, 56)
        b4 = _rotl64(a24, 14)

        a0 = b0 ^ (_u64(~b1) & b2)
        a1 = b1 ^ (_u64(~b2) & b3)
        a2 = b2 ^ (_u64(~b3) & b4)
        a3 = b3 ^ (_u64(~b4) & b0)
        a4 = b4 ^ (_u64(~b0) & b1)
        a5 = b5 ^ (_u64(~b6) & b7)
        a6 = b6 ^ (_u64(~b7) & b8)
        a7 = b7 ^ (_u64(~b8) & b9)
        a8 = b8 ^ (_u64(~b9) & b5)
        a9 = b9 ^ (_u64(~b5) & b6)
        a10 = b10 ^ (_u64(~b11) & b12)
        a11 = b11 ^ (_u64(~b12) & b13)
        a12 = b12 ^ (_u64(~b13) & b14)
        a13 = b13 ^ (_u64(~b14) & b10)
        a14 = b14 ^ (_u64(~b10) & b11)
        a15 = b15 ^ (_u64(~b16) & b17)
        a16 = b16 ^ (_u64(~b17) & b18)
        a17 = b17 ^ (_u64(~b18) & b19)
        a18 = b18 ^ (_u64(~b19) & b15)
        a19 = b19 ^ (_u64(~b15) & b16)
        a20 = b20 ^ (_u64(~b21) & b22)
        a21 = b21 ^ (_u64(~b22) & b23)
        a22 = b22 ^ (_u64(~b23) & b24)
        a23 = b23 ^ (_u64(~b24) & b20)
        a24 = b24 ^ (_u64(~b20) & b21)

        a0 ^= _RC[r]

    s[0], s[1], s[2], s[3], s[4] = a0, a1, a2, a3, a4
    s[5], s[6], s[7], s[8], s[9] = a5, a6, a7, a8, a9
    s[10], s[11], s[12], s[13], s[14] = a10, a11, a12, a13, a14
    s[15], s[16], s[17], s[18], s[19] = a15, a16, a17, a18, a19
    s[20], s[21], s[22], s[23], s[24] = a20, a21, a22, a23, a24


def deepseek_hash_v1(data: bytes) -> bytes:
    rate = 136
    s = [0] * 25

    off = 0
    while off + rate <= len(data):
        for i in range(rate // 8):
            w = struct.unpack_from("<Q", data, off + i * 8)[0]
            s[i] ^= w
        keccak_f23(s)
        off += rate

    final = bytearray(rate)
    final[: len(data) - off] = data[off:]
    final[len(data) - off] = 0x06
    final[rate - 1] |= 0x80
    for i in range(rate // 8):
        w = struct.unpack_from("<Q", final, i * 8)[0]
        s[i] ^= w
    keccak_f23(s)

    return struct.pack("<QQQQ", s[0], s[1], s[2], s[3])
