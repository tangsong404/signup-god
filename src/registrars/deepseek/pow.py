# SPDX-License-Identifier: CC0-1.0
# PoW logic ported from https://github.com/CJackHwang/ds2api (pow/deepseek_pow.go).

from __future__ import annotations

import base64
import json
import struct
import sys
from concurrent.futures import ProcessPoolExecutor
from typing import Callable

from registrars.deepseek.hash import deepseek_hash_v1, keccak_f23

RATE = 136

_POW_PARALLEL_MIN_DIFF = 40_000
_POW_FIXED_WORKERS = 8


def build_prefix(salt: str, expire_at: int) -> str:
    """salt + '_' + str(expire_at) + '_' (same as ds2api BuildPrefix)."""
    return f"{salt}_{expire_at}_"


def _pow_absorb_prefix(salt: str, expire_at: int) -> tuple[list[int], bytearray, int]:
    prefix = build_prefix(salt, expire_at).encode("utf-8")
    base_state = [0] * 25
    off = 0
    while off + RATE <= len(prefix):
        for i in range(RATE // 8):
            w = struct.unpack_from("<Q", prefix, off + i * 8)[0]
            base_state[i] ^= w
        keccak_f23(base_state)
        off += RATE
    tail_len = len(prefix) - off
    tail = bytearray(RATE)
    tail[:tail_len] = prefix[off:]
    return base_state, tail, tail_len


def _scan_nonce_range(
    base_state: list[int],
    tail: bytearray,
    tail_len: int,
    t0: int,
    t1: int,
    t2: int,
    t3: int,
    n0: int,
    n1: int,
    *,
    progress_total: int,
    cancel_check: Callable[[], None] | None,
) -> int | None:
    num_buf = bytearray(20)
    for n in range(n0, n1):
        if cancel_check is not None and (n & 0x3FF) == 0:
            cancel_check()
        v = n
        pos = 20
        if v == 0:
            pos -= 1
            num_buf[pos] = ord("0")
        else:
            while v > 0:
                pos -= 1
                num_buf[pos] = ord("0") + (v % 10)
                v //= 10
        num_len = 20 - pos
        s = base_state.copy()
        total_tail = tail_len + num_len
        if total_tail < RATE:
            buf = bytearray(RATE)
            buf[:tail_len] = tail[:tail_len]
            buf[tail_len:total_tail] = num_buf[pos : pos + num_len]
            buf[total_tail] = 0x06
            buf[RATE - 1] |= 0x80
            for i in range(RATE // 8):
                w = struct.unpack_from("<Q", buf, i * 8)[0]
                s[i] ^= w
            keccak_f23(s)
        else:
            buf = bytearray(RATE)
            buf[:tail_len] = tail[:tail_len]
            seg_len = RATE - tail_len
            buf[tail_len:RATE] = num_buf[pos : pos + seg_len]
            for i in range(RATE // 8):
                w = struct.unpack_from("<Q", buf, i * 8)[0]
                s[i] ^= w
            keccak_f23(s)
            buf2 = bytearray(RATE)
            rem = total_tail - RATE
            buf2[:rem] = num_buf[pos + seg_len : pos + seg_len + rem]
            buf2[rem] = 0x06
            buf2[RATE - 1] |= 0x80
            for i in range(RATE // 8):
                w = struct.unpack_from("<Q", buf2, i * 8)[0]
                s[i] ^= w
            keccak_f23(s)
        if s[0] == t0 and s[1] == t1 and s[2] == t2 and s[3] == t3:
            return n
    return None


def _pow_worker_entry(task: tuple[str, str, int, int, int, int]) -> int | None:
    """Picklable worker for ProcessPoolExecutor (must stay at module top level)."""
    challenge_hex, salt, expire_at, n0, n1, progress_total = task
    if n0 >= n1:
        return None
    if len(challenge_hex) != 64:
        return None
    target = bytes.fromhex(challenge_hex)
    t0, t1, t2, t3 = struct.unpack("<QQQQ", target[:32])
    base_state, tail, tail_len = _pow_absorb_prefix(salt, expire_at)
    return _scan_nonce_range(
        base_state,
        tail,
        tail_len,
        t0,
        t1,
        t2,
        t3,
        n0,
        n1,
        progress_total=progress_total,
        cancel_check=None,
    )


def solve_pow(
    challenge_hex: str,
    salt: str,
    expire_at: int,
    difficulty: int,
    *,
    cancel_check: Callable[[], None] | None = None,
) -> int:
    """Find n in [0, difficulty) such that state after DeepSeekHashV1 sponge matches challenge (ds2api SolvePow)."""
    if len(challenge_hex) != 64:
        msg = "pow: challenge must be 64 hex chars"
        raise ValueError(msg)
    sys.stderr.write(f"[main] guest PoW start difficulty={difficulty}\n")
    sys.stderr.flush()
    target = bytes.fromhex(challenge_hex)
    t0, t1, t2, t3 = struct.unpack("<QQQQ", target[:32])

    workers = _POW_FIXED_WORKERS
    use_parallel = workers > 1 and difficulty >= _POW_PARALLEL_MIN_DIFF and cancel_check is None

    if not use_parallel and difficulty >= _POW_PARALLEL_MIN_DIFF:
        if cancel_check is not None:
            sys.stderr.write(
                "[main] guest PoW: single-process mode (parallel disabled when cancel_check is set)\n",
            )
            sys.stderr.flush()

    if use_parallel:
        n_per = (difficulty + workers - 1) // workers
        tasks: list[tuple[str, str, int, int, int, int]] = []
        for i in range(workers):
            n0 = i * n_per
            n1 = min(difficulty, (i + 1) * n_per)
            if n0 < n1:
                tasks.append((challenge_hex, salt, expire_at, n0, n1, difficulty))
        with ProcessPoolExecutor(max_workers=workers) as ex:
            parts = list(ex.map(_pow_worker_entry, tasks))
        hits = [p for p in parts if p is not None]
        if not hits:
            msg = "pow: no solution within difficulty"
            raise ValueError(msg)
        ans = min(hits)
        sys.stderr.write(f"[main] guest PoW done answer={ans}\n")
        sys.stderr.flush()
        return ans

    base_state, tail, tail_len = _pow_absorb_prefix(salt, expire_at)
    hit = _scan_nonce_range(
        base_state,
        tail,
        tail_len,
        t0,
        t1,
        t2,
        t3,
        0,
        difficulty,
        progress_total=difficulty,
        cancel_check=cancel_check,
    )
    if hit is None:
        msg = "pow: no solution within difficulty"
        raise ValueError(msg)
    sys.stderr.write(f"[main] guest PoW done answer={hit}\n")
    sys.stderr.flush()
    return hit


def build_guest_pow_header_b64(*, salt: str, answer: int) -> str:
    """Value for HTTP header X-DS-Guest-PoW-Response (btoa(JSON.stringify({salt, answer})))."""
    raw = json.dumps({"salt": salt, "answer": answer}, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def solve_guest_challenge(
    *,
    challenge_hex: str,
    salt: str,
    expire_at: int,
    difficulty: int,
    cancel_check: Callable[[], None] | None = None,
) -> tuple[int, str]:
    """Return (answer, X-DS-Guest-PoW-Response header value)."""
    ans = solve_pow(
        challenge_hex,
        salt,
        expire_at,
        difficulty,
        cancel_check=cancel_check,
    )
    return ans, build_guest_pow_header_b64(salt=salt, answer=ans)


def hash_prefix_plus_nonce(prefix: str, nonce: int) -> bytes:
    """Convenience: DeepSeekHashV1(prefix + str(nonce)) for tests."""
    return deepseek_hash_v1((prefix + str(nonce)).encode("utf-8"))
