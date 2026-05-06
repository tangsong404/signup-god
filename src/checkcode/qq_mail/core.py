from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

CN_TZ = timezone(timedelta(hours=8))
HUMAN_LOG = logging.getLogger("qq_mail_listener")


class ListenerError(Exception):
    pass


class SessionLostError(ListenerError):
    pass


def extract_first_capture_or_whole(match: Optional[re.Match[str]]) -> Optional[str]:
    if not match:
        return None
    for g in match.groups():
        if g is not None:
            return g
    return match.group(0)


@dataclass
class MailItem:
    sender: str
    subject: str
    body: str
    mail_ts: datetime
    message_id: str
    mail_ts_raw: Optional[str] = None
    id_type: str = "source"


def now_iso() -> str:
    return datetime.now(CN_TZ).isoformat()


def build_derived_message_id(sender: str, subject: str, mail_ts_raw: str, code: str) -> str:
    data = f"{sender}|{subject}|{mail_ts_raw}|{code}".encode("utf-8")
    return "derived-" + hashlib.sha1(data).hexdigest()


class EventEmitter:
    def emit_json(self, payload: dict) -> None:
        raise NotImplementedError


class StdoutJsonEmitter(EventEmitter):
    def __init__(self, run_id: str):
        self.run_id = run_id

    def emit_json(self, payload: dict) -> None:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        sys.stdout.flush()


class MessageMatcher:
    def __init__(
        self,
        sender_keyword: str,
        subject_keywords: list[str],
        code_regex: str,
        freshness_minutes: int = 5,
        code_dedupe_minutes: int = 5,
    ):
        self.sender_keyword = sender_keyword.lower()
        self.subject_keywords = subject_keywords
        self._code_re = re.compile(code_regex)
        self.freshness = timedelta(minutes=freshness_minutes)
        self.code_dedupe = timedelta(minutes=code_dedupe_minutes)
        self._seen_message_ids: set[str] = set()
        self._seen_codes: dict[str, datetime] = {}

    def matches_envelope(self, sender: str, subject: str) -> bool:
        if self.sender_keyword and self.sender_keyword not in sender.lower():
            return False
        if self.subject_keywords and not any(k.lower() in subject.lower() for k in self.subject_keywords):
            return False
        return True

    def extract_code(self, sender: str, subject: str, body: str) -> Optional[str]:
        if not self.matches_envelope(sender, subject):
            return None
        m = self._code_re.search(body)
        return extract_first_capture_or_whole(m)

    def should_emit(self, message_id: str, code: str, now: datetime) -> bool:
        if message_id in self._seen_message_ids:
            return False
        last_code_at = self._seen_codes.get(code)
        if last_code_at and now - last_code_at < self.code_dedupe:
            return False
        self._seen_message_ids.add(message_id)
        self._seen_codes[code] = now
        return True


class SerialCoordinator:
    def __init__(
        self,
        emitter: EventEmitter,
        matcher: MessageMatcher,
        consume_func: Callable[[dict], None],
        consume_timeout_sec: int = 120,
        mask_code: bool = False,
    ):
        self.emitter = emitter
        self.matcher = matcher
        self.consume_func = consume_func
        self.consume_timeout_sec = consume_timeout_sec
        self.mask_code = mask_code

    def _consume_with_timeout(self, event: dict) -> None:
        error_holder: list[Exception] = []

        def target() -> None:
            try:
                self.consume_func(event)
            except Exception as ex:
                error_holder.append(ex)

        t = threading.Thread(target=target, daemon=True)
        t.start()
        t.join(self.consume_timeout_sec)
        if t.is_alive():
            raise TimeoutError("consumer timeout")
        if error_holder:
            raise error_holder[0]

    def process_new_mail(self, item: MailItem, *, extracted_code: Optional[str] = None) -> bool:
        code = extracted_code or self.matcher.extract_code(item.sender, item.subject, item.body)
        if not code:
            return False
        current = datetime.now(CN_TZ)
        message_id = item.message_id or build_derived_message_id(
            item.sender, item.subject, item.mail_ts_raw or "", code
        )
        id_type = "source" if item.message_id else "derived"
        if not self.matcher.should_emit(message_id, code, current):
            return False

        code_out = f"***{code[-3:]}" if self.mask_code else code
        event = {
            "event": "verification_code",
            "ts": now_iso(),
            "run_id": getattr(self.emitter, "run_id", "unknown"),
            "code": code_out,
            "message_id": message_id,
            "id_type": id_type,
            "mail_ts": item.mail_ts.astimezone(CN_TZ).isoformat(),
            "mail_ts_raw": item.mail_ts_raw,
        }
        self.emitter.emit_json(event)
        self._consume_with_timeout(event)
        return True
