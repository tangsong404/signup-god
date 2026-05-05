from __future__ import annotations

import argparse
import json
import sys

from checkcode.manual import ManualCheckcodeSource
from registrars.deepseek.config import DeepSeekConfig
from registrars.deepseek.registrar import DeepSeekApiError, DeepSeekRegistrar


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m registrars.deepseek")
    sub = p.add_subparsers(dest="command", required=True)
    reg = sub.add_parser("register", help="init -> send code -> manual code -> sign-up (HTTP)")
    reg.add_argument("--email", required=True, help="Mailbox receiving DeepSeek code")
    reg.add_argument("--password", required=True, help="Desired DeepSeek password")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "register":
        return 0
    try:
        cfg = DeepSeekConfig.from_env()
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    source = ManualCheckcodeSource(on_request=lambda hint: input(f"{hint}: "))
    reg = DeepSeekRegistrar(checkcode_source=source, config=cfg)
    reg.init()
    try:
        reg.send_email_code(args.email)
        code = reg.wait_checkcode(args.email)
        result = reg.sign(args.email, args.password, code)
    except (DeepSeekApiError, OSError, RuntimeError, TimeoutError) as e:
        print(str(e), file=sys.stderr)
        if isinstance(e, DeepSeekApiError) and e.response_json is not None:
            print(json.dumps(e.response_json, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    finally:
        reg.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
