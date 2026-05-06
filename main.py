"""
Batch signup driver. The three pluggable layers are picked by .env:

  - SIGNUP_REGISTRAR              which site's registrar to drive       (default: ``deepseek``)
  - SIGNUP_CHECKCODE              where verification codes come from    (default: ``qq_mail``)
  - SIGNUP_ACCOUNT_GENERATOR      where new account identifiers come    (default: ``duck_email``)

Each successful registration appends one row to ``结果.csv`` (UTF-8 BOM, columns
``identifier`` / ``password`` / ``token``). Failures are not recorded. When DeepSeek returns
``ACCOUNT_ALREADY_EXISTS``, the driver allocates a new ``@duck.com`` address and retries without
advancing ``--num``. When responses indicate excessive request rate (e.g. ``REQUEST_TOO_FREQUENT`` /
Chinese ``频繁`` text), it sleeps 30s and retries using the same address.

Run from ``signup-god`` root::

    python main.py
    python main.py --num 5
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

# Force UTF-8 for our own stdout/stderr so non-ASCII output (Chinese / em-dash /
# ellipsis) does not crash on Windows cp936 consoles.
for _stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(_stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

_REPO_ROOT = Path(__file__).resolve().parent
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")

import httpx  # noqa: E402

from account_generators import DuckEmailAccountGenerator  # noqa: E402
from checkcode.manual import ManualCheckcodeSource  # noqa: E402
from checkcode.qq_mail import QQMailCheckcodeSource  # noqa: E402
from registrars.deepseek.config import DeepSeekConfig  # noqa: E402
from registrars.deepseek.registrar import DeepSeekApiError, DeepSeekRegistrar  # noqa: E402

_RESULT_CSV = _REPO_ROOT / "结果.csv"
_RESULT_FIELDS = ("identifier", "password", "token")
_STEP_PACE_SEC = 60.0
_RATE_LIMIT_RETRY_SLEEP_SEC = 30.0


def _deepseek_biz_msg(err: DeepSeekApiError) -> str | None:
    payload = err.response_json
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    bm = data.get("biz_msg")
    if bm is None:
        return None
    return str(bm).strip()


def _is_account_already_exists(err: DeepSeekApiError) -> bool:
    bm = _deepseek_biz_msg(err)
    return bm is not None and bm.upper() == "ACCOUNT_ALREADY_EXISTS"


def _is_request_too_frequent(err: DeepSeekApiError) -> bool:
    payload = err.response_json
    if isinstance(payload, dict):
        top_msg = payload.get("msg")
        if isinstance(top_msg, str):
            if "频繁" in top_msg:
                return True
            u = top_msg.upper().replace(" ", "_")
            if "FREQUENT" in u or "RATE_LIMIT" in u or "TOO_MANY_REQUEST" in u:
                return True
    bm = _deepseek_biz_msg(err)
    if bm:
        if "频繁" in bm:
            return True
        u = bm.upper().replace(" ", "_")
        if "FREQUENT" in u or "RATE_LIMIT" in u or "TOO_MANY_REQUEST" in u:
            return True
    return "频繁" in str(err)


# ---------------------------------------------------------------------------
# Pluggable component registries: pick by name via .env. Each entry is a small
# spec describing how to build the component (and, for registrars, how to drive
# it for one account). Add new entries as new sites / mailbox providers / ID
# producers come online -- main() does not need to change.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegistrarSpec:
    """How to build and use a registrar for one signup attempt."""

    cls: type
    build: Callable[..., Any]                  # (*, checkcode_source) -> registrar
    register_one: Callable[..., None]          # (registrar, *, identifier, password) -> None


def _build_deepseek_registrar(*, checkcode_source: Any) -> DeepSeekRegistrar:
    return DeepSeekRegistrar(
        checkcode_source=checkcode_source,
        config=DeepSeekConfig.from_env(),
    )


def _register_one_deepseek(reg: DeepSeekRegistrar, *, identifier: str, password: str) -> None:
    reg.register_with_random_birthday(email=identifier, password=password)


REGISTRARS: dict[str, RegistrarSpec] = {
    "deepseek": RegistrarSpec(
        cls=DeepSeekRegistrar,
        build=_build_deepseek_registrar,
        register_one=_register_one_deepseek,
    ),
}


def _build_qq_mail_source(*, registrar_cls: type) -> Any:
    return QQMailCheckcodeSource.from_env(criteria=registrar_cls.mail_match_criteria())


def _build_manual_source(*, registrar_cls: type) -> Any:  # noqa: ARG001 - unified signature
    return ManualCheckcodeSource(on_request=lambda hint: input(f"{hint}: "))


# Each builder takes (*, registrar_cls) -> CheckcodeSource. registrar_cls is
# passed so mail-based sources can read site-specific match criteria from it.
CHECKCODE_SOURCES: dict[str, Callable[..., Any]] = {
    "qq_mail": _build_qq_mail_source,
    "manual": _build_manual_source,
}


def _build_duck_email_generator(*, http_client: httpx.Client) -> DuckEmailAccountGenerator:
    token = (os.environ.get("DUCK_EMAIL_API_TOKEN") or "").strip()
    if not token:
        msg = "DUCK_EMAIL_API_TOKEN is required when SIGNUP_ACCOUNT_GENERATOR=duck_email"
        raise ValueError(msg)
    return DuckEmailAccountGenerator(token=token, client=http_client)


# Each builder takes (*, http_client) -> AccountIdentifierGenerator.
ACCOUNT_GENERATORS: dict[str, Callable[..., Any]] = {
    "duck_email": _build_duck_email_generator,
}


def _pick(env_var: str, default: str, choices: dict[str, Any]) -> str:
    name = (os.environ.get(env_var) or default).strip()
    if name not in choices:
        avail = ", ".join(sorted(choices)) or "(none registered)"
        msg = f"Unknown {env_var}={name!r}. Available: {avail}"
        raise ValueError(msg)
    return name


def _append_success_csv(path: Path, *, identifier: str, password: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=_RESULT_FIELDS)
        if new_file:
            w.writeheader()
        w.writerow(
            {
                "identifier": identifier,
                "password": password,
                "token": "",
            },
        )


def main() -> int:
    p = argparse.ArgumentParser(description="Generate identifiers and register accounts.")
    p.add_argument("--num", type=int, default=1, help="Number of accounts to register (default: 1)")
    args = p.parse_args()
    if args.num < 1:
        sys.stderr.write("[main] --num must be >= 1\n")
        sys.stderr.flush()
        return 2

    password = (os.environ.get("DEEPSEEK_REGISTER_PASSWORD") or "").strip()
    if not password:
        sys.stderr.write("[main] Missing DEEPSEEK_REGISTER_PASSWORD in .env\n")
        sys.stderr.flush()
        return 1

    try:
        registrar_name = _pick("SIGNUP_REGISTRAR", "deepseek", REGISTRARS)
        checkcode_name = _pick("SIGNUP_CHECKCODE", "qq_mail", CHECKCODE_SOURCES)
        generator_name = _pick("SIGNUP_ACCOUNT_GENERATOR", "duck_email", ACCOUNT_GENERATORS)
    except ValueError as e:
        sys.stderr.write(f"[main] {e}\n")
        sys.stderr.flush()
        return 1

    spec = REGISTRARS[registrar_name]
    sys.stderr.write(
        f"[main] selection: registrar={registrar_name} checkcode={checkcode_name} "
        f"account_generator={generator_name}\n",
    )
    sys.stderr.flush()

    try:
        checkcode_source = CHECKCODE_SOURCES[checkcode_name](registrar_cls=spec.cls)
        reg = spec.build(checkcode_source=checkcode_source)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    except OSError as e:
        print(str(e), file=sys.stderr)
        return 1

    batch_started_at = time.monotonic()
    try:
        reg.init()
        with httpx.Client() as http:
            try:
                id_gen = ACCOUNT_GENERATORS[generator_name](http_client=http)
            except ValueError as e:
                print(str(e), file=sys.stderr)
                return 1
            success_i = 0
            while success_i < args.num:
                step_started_at = time.monotonic()
                identifier = id_gen.next_identifier()
                while True:
                    try:
                        spec.register_one(reg, identifier=identifier, password=password)
                        break
                    except DeepSeekApiError as e:
                        if _is_account_already_exists(e):
                            sys.stderr.write(
                                "[main] DeepSeek biz_msg=ACCOUNT_ALREADY_EXISTS: "
                                "allocating a new duck address and retrying "
                                "(does not count toward --num).\n"
                            )
                            sys.stderr.flush()
                            identifier = id_gen.next_identifier()
                            continue
                        if _is_request_too_frequent(e):
                            sys.stderr.write(
                                f"[main] rate-limited (biz_msg or message mentions "
                                f"throttling); sleeping {_RATE_LIMIT_RETRY_SLEEP_SEC:.0f}s "
                                f"then retrying the same address.\n"
                            )
                            sys.stderr.flush()
                            time.sleep(_RATE_LIMIT_RETRY_SLEEP_SEC)
                            continue
                        raise
                success_i += 1
                _append_success_csv(_RESULT_CSV, identifier=identifier, password=password)
                sys.stderr.write(f"[main] wrote success row to {_RESULT_CSV.name}\n")
                step_elapsed = time.monotonic() - step_started_at
                total_elapsed = time.monotonic() - batch_started_at
                sys.stderr.write(
                    f"\n-----{success_i}/{args.num}, this run elapsed {step_elapsed:.2f}s, "
                    f"total elapsed {total_elapsed:.2f}s-----\n\n"
                )
                sys.stderr.flush()
                # Pace one registration per 60s window; skip the wait after the last account.
                if success_i < args.num:
                    sleep_for = max(0.0, _STEP_PACE_SEC - step_elapsed)
                    if sleep_for > 0:
                        sys.stderr.write(
                            f"[main] waiting {sleep_for:.2f}s before next account "
                            f"(pace {_STEP_PACE_SEC:.0f}s/account)\n"
                        )
                        sys.stderr.flush()
                        time.sleep(sleep_for)
        return 0
    except (DeepSeekApiError, OSError, RuntimeError, TimeoutError, ValueError) as e:
        print(str(e), file=sys.stderr)
        if isinstance(e, DeepSeekApiError) and e.response_json is not None:
            print(json.dumps(e.response_json, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    finally:
        reg.close()


if __name__ == "__main__":
    raise SystemExit(main())
