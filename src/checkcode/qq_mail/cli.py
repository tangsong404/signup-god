from __future__ import annotations

import html
import json
import logging
import os
import re
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import dotenv_values

from checkcode.qq_mail.core import (
    HUMAN_LOG,
    MailItem,
    MessageMatcher,
    SerialCoordinator,
    StdoutJsonEmitter,
    extract_first_capture_or_whole,
)

CN_TZ = timezone(timedelta(hours=8))
_DEFAULT_QQ_UA = (
    "Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 "
    "Mobile Safari/537.36 Edg/147.0.0.0"
)


def setup_human_logging(*, debug_stream: bool) -> None:
    HUMAN_LOG.handlers.clear()
    HUMAN_LOG.propagate = False
    if debug_stream:
        HUMAN_LOG.setLevel(logging.INFO)
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        HUMAN_LOG.addHandler(sh)
    else:
        HUMAN_LOG.setLevel(logging.CRITICAL + 10)
        HUMAN_LOG.addHandler(logging.NullHandler())


def load_dotenv_only() -> dict:
    env_override = (os.environ.get("QQ_LISTENER_ENV_PATH") or "").strip()
    env_path = Path(env_override).expanduser().resolve() if env_override else Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        raise FileNotFoundError(f"missing .env: {env_path}")
    values = dotenv_values(env_path)
    return {k: v for k, v in values.items() if v is not None}


def emit_fatal(run_id: str, reason: str, exit_code: int = 20) -> int:
    payload = {
        "event": "fatal_error",
        "ts": datetime.now(CN_TZ).isoformat(),
        "run_id": run_id,
        "reason": reason,
        "exit_code": exit_code,
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return exit_code


def parse_cookie_header(raw: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for part in (raw or "").split(";"):
        item = part.strip()
        if not item or "=" not in item:
            continue
        k, v = item.split("=", 1)
        if k.strip() and v.strip():
            pairs.append((k.strip(), v.strip()))
    return pairs


def extract_sid(cookie_pairs: list[tuple[str, str]]) -> str:
    kv = {k: v for k, v in cookie_pairs}
    sid = kv.get("xm_sid", "").strip()
    if sid:
        return sid
    sid = kv.get("sid", "").strip()
    if "&" in sid:
        sid = sid.split("&", 1)[0]
    return sid


def _http_json(
    *,
    method: str,
    path: str,
    params: dict[str, object],
    cookie_header: str,
    user_agent: str,
) -> dict:
    if method == "GET":
        url = f"https://wx.mail.qq.com{path}?{urlencode(params, doseq=True)}"
        body = None
    else:
        url = f"https://wx.mail.qq.com{path}"
        body = urlencode(params, doseq=True).encode("utf-8")
    req = Request(url, data=body, method=method)
    req.add_header("Accept", "application/json, text/plain, */*")
    req.add_header("Cookie", cookie_header)
    req.add_header("User-Agent", user_agent)
    req.add_header("Referer", "https://wx.mail.qq.com/")
    if method == "POST":
        req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
    with urlopen(req, timeout=25) as resp:  # nosec B310
        raw = resp.read().decode("utf-8", errors="replace")
    payload = json.loads(raw)
    if isinstance(payload, dict):
        head = payload.get("head")
        if isinstance(head, dict) and isinstance(head.get("ret"), int) and head["ret"] != 0:
            raise RuntimeError(f"qq api {path} ret={head['ret']}")
    return payload if isinstance(payload, dict) else {}


def _collect_dicts(obj: object) -> list[dict]:
    out: list[dict] = []
    if isinstance(obj, dict):
        out.append(obj)
        for v in obj.values():
            out.extend(_collect_dicts(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_collect_dicts(v))
    return out


def _collect_strings(obj: object) -> list[str]:
    out: list[str] = []
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(_collect_strings(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_collect_strings(v))
    return out


def _mail_candidates(payload: dict) -> list[dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for d in _collect_dicts(payload):
        mid = ""
        for k in ("emailid", "mailid", "mail_id", "id"):
            v = d.get(k)
            if isinstance(v, str) and v.strip():
                mid = v.strip()
                break
        if not mid:
            continue
        subj = ""
        for k in ("subject", "title", "subj"):
            v = d.get(k)
            if isinstance(v, str) and v.strip():
                subj = v.strip()
                break
        sender = ""
        for k in ("from", "from_addr", "sender", "fromName"):
            v = d.get(k)
            if isinstance(v, str) and v.strip():
                sender = v.strip()
                break
        # QQ list payload commonly nests sender at body.list[].senders.item[0].
        if not sender:
            senders = d.get("senders")
            if isinstance(senders, dict):
                items = senders.get("item")
                if isinstance(items, list):
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        for k in ("email", "nick"):
                            v = it.get(k)
                            if isinstance(v, str) and v.strip():
                                sender = v.strip()
                                break
                        if sender:
                            break
        folderid = "1"
        dirid = d.get("dirid")
        if isinstance(dirid, int):
            folderid = str(dirid)
        elif isinstance(dirid, str) and dirid.strip():
            folderid = dirid.strip()
        rows[mid] = {"mailid": mid, "subject": subj, "sender": sender, "folderid": folderid}
    return list(rows.values())


def _payload_shape_brief(payload: dict, max_items: int = 8) -> str:
    parts: list[str] = []
    if isinstance(payload, dict):
        ks = list(payload.keys())
        parts.append(f"top_keys={ks[:max_items]}")
        head = payload.get("head")
        if isinstance(head, dict):
            parts.append(f"head_keys={list(head.keys())[:max_items]}")
            if "ret" in head:
                parts.append(f"ret={head.get('ret')!r}")
        body = payload.get("body")
        if isinstance(body, dict):
            parts.append(f"body_keys={list(body.keys())[:max_items]}")
    return ", ".join(parts) if parts else "payload not dict"


_ZW_RE = re.compile(r"[\u200b\u200c\u200d\ufeff\u00a0]")


def normalize_text(text: str | None) -> str:
    if not text or not str(text).strip():
        return ""
    return _ZW_RE.sub("", html.unescape(str(text)))


def default_consumer(_: dict) -> None:
    return


def _stderr_log(msg: str) -> None:
    sys.stderr.write(f"[qqmail_verifier] {msg}\n")
    sys.stderr.flush()


def _delete_mail_after_code(
    *,
    sid: str,
    mailid: str,
    folderid: str,
    cookie_header: str,
    user_agent: str,
) -> None:
    _http_json(
        method="POST",
        path="/mgr/mailmgr",
        params={
            "func": 1,
            "mailid": mailid,
            "folderid": folderid,
            "choose_type": 1,
            "r": str(int(time.time() * 1000)),
            "sid": sid,
        },
        cookie_header=cookie_header,
        user_agent=user_agent,
    )


def _load_match_criteria_from_env() -> tuple[str, list[str], str]:
    sender_keyword = (os.environ.get("QQ_MAIL_SENDER_KEYWORD") or "").strip()
    subj_raw = (os.environ.get("QQ_MAIL_SUBJECT_KEYWORDS") or "").strip()
    subject_keywords: list[str] = []
    if subj_raw:
        try:
            parsed = json.loads(subj_raw)
        except json.JSONDecodeError:
            parsed = [s.strip() for s in subj_raw.split(",") if s.strip()]
        if isinstance(parsed, list):
            subject_keywords = [str(x) for x in parsed if str(x).strip()]
        elif isinstance(parsed, str):
            subject_keywords = [parsed]
    # Injected by ``QQMailCheckcodeSource`` from ``MailMatchCriteria.code_regex`` (site-specific;
    # DeepSeek defines theirs in ``registrars.deepseek.verification_mail`` — not configured in .env).
    code_regex = (os.environ.get("QQ_MAIL_CODE_REGEX") or "").strip()
    if not code_regex:
        raise ValueError(
            "QQ_MAIL_CODE_REGEX is unset. Run via main.py (or any flow that starts the listener "
            "with registrar mail_match_criteria); do not run the QQ listener standalone without "
            "injecting MailMatchCriteria."
        )
    return sender_keyword, subject_keywords, code_regex


def main() -> int:
    run_id = "unknown"
    try:
        cfg = load_dotenv_only()
        run_id = cfg.get("RUN_ID") or str(uuid.uuid4())
        poll_interval_sec = int(cfg.get("POLL_INTERVAL_SEC", "5"))
        mask_code = str(cfg.get("MASK_CODE", "0")).strip() == "1"
        setup_human_logging(debug_stream=False)
        emitter = StdoutJsonEmitter(run_id=run_id)
        sender_kw, subject_kws, code_regex = _load_match_criteria_from_env()
        try:
            compiled_code_re = re.compile(code_regex)
        except re.error as ex:
            return emit_fatal(run_id, f"invalid QQ_MAIL_CODE_REGEX: {ex}", exit_code=33)
        matcher = MessageMatcher(
            sender_keyword=sender_kw,
            subject_keywords=subject_kws,
            code_regex=code_regex,
            freshness_minutes=5,
            code_dedupe_minutes=5,
        )
        coordinator = SerialCoordinator(
            emitter=emitter,
            matcher=matcher,
            consume_func=default_consumer,
            consume_timeout_sec=120,
            mask_code=mask_code,
        )
        qq_cookie_raw = str(cfg.get("QQ_MAIL_COOKIE") or "").strip()
        qq_cookie_pairs = parse_cookie_header(qq_cookie_raw)
        _stderr_log(f"startup run_id={run_id}")
        _stderr_log(f"cookie pairs loaded={len(qq_cookie_pairs)}")
        if not qq_cookie_pairs:
            return emit_fatal(run_id, "QQ_MAIL_COOKIE is required.", exit_code=31)

        sid = extract_sid(qq_cookie_pairs)
        _stderr_log(f"sid detected={bool(sid)}")
        if not sid:
            return emit_fatal(run_id, "QQ_MAIL_COOKIE missing sid/xm_sid", exit_code=32)
        cookie_header = "; ".join(f"{k}={v}" for k, v in qq_cookie_pairs)
        qq_ua = str(cfg.get("QQ_MAIL_USER_AGENT") or _DEFAULT_QQ_UA)
        _stderr_log("fetching initial mail list baseline")
        first_list = _http_json(
            method="GET",
            path="/list/maillist",
            params={
                "r": str(int(time.time() * 1000)),
                "sid": sid,
                "dir": 1,
                "page_now": 0,
                "page_size": 25,
                "sort_type": 1,
                "sort_direction": 1,
                "func": 1,
                "tag": "",
            },
            cookie_header=cookie_header,
            user_agent=qq_ua,
        )
        baseline_rows = _mail_candidates(first_list)
        baseline_ids = {x["mailid"] for x in baseline_rows}
        _stderr_log(f"initial baseline loaded: {len(baseline_ids)} mail ids")
        if not baseline_rows:
            _stderr_log(f"initial list rows=0; shape: {_payload_shape_brief(first_list)}")
            _stderr_log(f"initial list compact: {json.dumps(first_list, ensure_ascii=False)[:1200]}")
        emitter.emit_json(
            {
                "event": "listener_ready",
                "ts": datetime.now(CN_TZ).isoformat(),
                "run_id": run_id,
                "baseline_count": len(baseline_ids),
            }
        )
        zero_rows_logged = False
        while True:
            try:
                listed = _http_json(
                    method="GET",
                    path="/list/maillist",
                    params={
                        "r": str(int(time.time() * 1000)),
                        "sid": sid,
                        "dir": 1,
                        "page_now": 0,
                        "page_size": 25,
                        "sort_type": 1,
                        "sort_direction": 1,
                        "func": 1,
                        "tag": "",
                    },
                    cookie_header=cookie_header,
                    user_agent=qq_ua,
                )
            except TimeoutError as ex:
                _stderr_log(f"list poll timeout: {ex}")
                time.sleep(poll_interval_sec)
                continue
            except Exception as ex:
                _stderr_log(f"list poll failed: {ex}")
                time.sleep(poll_interval_sec)
                continue
            rows = _mail_candidates(listed)
            fresh = [r for r in rows if r["mailid"] not in baseline_ids]
            _stderr_log(f"poll list fetched={len(rows)} fresh={len(fresh)}")
            if not rows and not zero_rows_logged:
                zero_rows_logged = True
                _stderr_log(f"poll rows=0; shape: {_payload_shape_brief(listed)}")
                _stderr_log(f"poll compact: {json.dumps(listed, ensure_ascii=False)[:1200]}")
            for r in rows:
                baseline_ids.add(r["mailid"])
            if not fresh:
                time.sleep(poll_interval_sec)
                continue
            for row in fresh:
                row_subject = row.get("subject", "") or ""
                row_sender = row.get("sender", "") or ""
                if not matcher.matches_envelope(row_sender, row_subject):
                    _stderr_log(
                        "skip non-matching mail "
                        f"mailid={row['mailid']} subject={row_subject!r} sender={row_sender!r}"
                    )
                    continue
                _stderr_log(
                    "parsing fresh mail "
                    f"mailid={row['mailid']} subject={row_subject!r} sender={row_sender!r}"
                )
                try:
                    payload = _http_json(
                        method="POST",
                        path="/read/readmail",
                        params={
                            "mailid": row["mailid"],
                            "func": 1,
                            "r": str(int(time.time() * 1000)),
                            "sid": sid,
                        },
                        cookie_header=cookie_header,
                        user_agent=qq_ua,
                    )
                except TimeoutError as ex:
                    _stderr_log(f"readmail timeout mailid={row['mailid']}: {ex}")
                    continue
                except Exception as ex:
                    _stderr_log(f"readmail failed mailid={row['mailid']}: {ex}")
                    continue
                text_blob = normalize_text("\n".join(_collect_strings(payload)))
                m = compiled_code_re.search(text_blob)
                code = extract_first_capture_or_whole(m)
                if not code:
                    _stderr_log(f"code not found in mailid={row['mailid']}")
                    emitter.emit_json(
                        {
                            "event": "mail_parse_failed",
                            "ts": datetime.now(CN_TZ).isoformat(),
                            "run_id": run_id,
                            "reason": f"mailid={row['mailid']} code not found",
                        }
                    )
                    continue
                _stderr_log(f"extracted code from mailid={row['mailid']}")
                try:
                    _delete_mail_after_code(
                        sid=sid,
                        mailid=row["mailid"],
                        folderid=str(row.get("folderid") or "1"),
                        cookie_header=cookie_header,
                        user_agent=qq_ua,
                    )
                    _stderr_log(f"mail deleted mailid={row['mailid']}")
                except Exception as ex:
                    _stderr_log(f"mail delete failed mailid={row['mailid']}: {ex}")
                now_dt = datetime.now(CN_TZ)
                item = MailItem(
                    sender=row_sender or "unknown@sender",
                    subject=row_subject,
                    body=text_blob[:16000],
                    mail_ts=now_dt,
                    message_id=row["mailid"],
                    mail_ts_raw=now_dt.strftime("%Y-%m-%d %H:%M"),
                    id_type="source",
                )
                coordinator.process_new_mail(item, extracted_code=code)
            time.sleep(poll_interval_sec)
    except Exception as ex:
        return emit_fatal(run_id, str(ex), exit_code=20)


if __name__ == "__main__":
    raise SystemExit(main())
