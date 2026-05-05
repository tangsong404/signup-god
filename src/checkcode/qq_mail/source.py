from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv

from checkcode.mail_match import MailMatchCriteria

_PACKAGE_ENV = Path(__file__).resolve().parents[3] / ".env"
# Single instance so queue producer/consumer identity checks match.
_STDOUT_FEED_END = object()


class QQListenerError(RuntimeError):
    """QQ mail listener subprocess failed or produced an unusable result."""


class QQListenerFatalError(QQListenerError):
    def __init__(self, message: str, *, payload: dict[str, Any]) -> None:
        super().__init__(message)
        self.payload = payload
        self.exit_code = int(payload.get("exit_code") or 20)


class QQListenerSessionLost(QQListenerError):
    def __init__(self, message: str, *, payload: dict[str, Any]) -> None:
        super().__init__(message)
        self.payload = payload


class QQListenerMaskedCodeError(QQListenerError):
    """MASK_CODE=1 in listener .env yields a partial code; registration needs the full code."""


class QQListenerProcessEnded(QQListenerError):
    """Listener exited or closed stdout before a usable verification code arrived."""


class QQMailCheckcodeSource:
    """
    Generic QQ-mail-backed verification-code source.

    Site-specific behaviour (which sender / subject keywords to filter on, and the
    regex used to extract the code) is provided by the caller as ``MailMatchCriteria``;
    the registrar exposes its own criteria via ``mail_match_criteria()``.

    Internally this spawns ``checkcode.qq_mail.cli`` and parses JSON ``verification_code``
    events from its stdout.
    """

    def __init__(
        self,
        *,
        criteria: MailMatchCriteria,
        listener_root: str | os.PathLike[str] | None = None,
        python_executable: str | None = None,
        popen: Callable[..., Any] | None = None,
    ) -> None:
        self._criteria = criteria
        self._listener_root = (
            Path(listener_root).expanduser().resolve()
            if listener_root is not None
            else Path(__file__).resolve().parents[3]
        )
        self._python = python_executable or sys.executable
        self._popen = popen or subprocess.Popen
        self._project_dir = Path(__file__).resolve().parents[3]
        self._active_proc: subprocess.Popen[str] | None = None
        self._out_q: queue.Queue[Any] | None = None
        self._inited = False

    @classmethod
    def from_env(
        cls,
        *,
        criteria: MailMatchCriteria,
        python_executable: str | None = None,
    ) -> QQMailCheckcodeSource:
        load_dotenv(_PACKAGE_ENV)
        return cls(criteria=criteria, listener_root=None, python_executable=python_executable)

    def _listener_paths_ok(self) -> None:
        cli_path = Path(__file__).resolve().parent / "cli.py"
        if not cli_path.is_file():
            msg = f"In-package QQ listener cli missing at {cli_path}"
            raise FileNotFoundError(msg)

    def init(self) -> None:
        self._listener_paths_ok()
        self._terminate_active()
        proc = self._spawn_listener()
        self._active_proc = proc
        out_q: queue.Queue[Any] = queue.Queue()
        self._out_q = out_q
        feeder = threading.Thread(
            target=self._stdout_feeder,
            args=(proc, out_q),
            name="qq-listener-stdout",
            daemon=True,
        )
        feeder.start()
        err_feeder = threading.Thread(
            target=self._stderr_feeder,
            args=(proc,),
            name="qq-listener-stderr",
            daemon=True,
        )
        err_feeder.start()
        self._wait_for_ready(proc, out_q=out_q, timeout_sec=45.0)
        self._inited = True

    def close(self) -> None:
        self._terminate_active()
        self._out_q = None
        self._inited = False

    def _terminate_active(self) -> None:
        proc = self._active_proc
        if proc is None:
            return
        self._terminate_process(proc)
        self._active_proc = None
        self._out_q = None

    @staticmethod
    def _terminate_process(proc: subprocess.Popen[str]) -> None:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)

    @staticmethod
    def _normalize_code(raw: str) -> str:
        code = (raw or "").strip()
        if not code or "***" in code:
            msg = (
                "Listener returned a masked or empty code (set MASK_CODE=0 in the listener .env "
                "to receive the full verification code)."
            )
            raise QQListenerMaskedCodeError(msg)
        return code

    def _spawn_listener(self) -> subprocess.Popen[str]:
        cmd = [self._python, "-u", "-m", "checkcode.qq_mail.cli"]
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        env = os.environ.copy()
        env["QQ_LISTENER_ENV_PATH"] = str(_PACKAGE_ENV)
        env["QQ_MAIL_SENDER_KEYWORD"] = self._criteria.sender_keyword
        env["QQ_MAIL_SUBJECT_KEYWORDS"] = json.dumps(
            list(self._criteria.subject_keywords), ensure_ascii=False
        )
        env["QQ_MAIL_CODE_REGEX"] = self._criteria.code_regex
        # Keep child's stdio in UTF-8 so the parent (which decodes the pipe as UTF-8) sees
        # consistent text on Windows cp936 consoles.
        env["PYTHONIOENCODING"] = "utf-8"
        # The child runs ``python -m checkcode.qq_mail.cli``; it needs ``src`` on its module
        # search path to find the top-level ``checkcode`` package (parent's runtime sys.path
        # patch in main.py does NOT propagate into subprocesses).
        src_dir = str(Path(__file__).resolve().parents[2])
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = src_dir + (os.pathsep + existing_pp if existing_pp else "")
        return self._popen(
            cmd,
            cwd=str(self._project_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )

    @staticmethod
    def _stdout_feeder(proc: subprocess.Popen[str], out_q: queue.Queue[Any]) -> None:
        try:
            if proc.stdout is None:
                return
            for line in proc.stdout:
                out_q.put(line.rstrip("\r\n"))
        finally:
            out_q.put(_STDOUT_FEED_END)

    @staticmethod
    def _stderr_feeder(proc: subprocess.Popen[str]) -> None:
        if proc.stderr is None:
            return
        for line in proc.stderr:
            s = line.rstrip("\r\n")
            if not s:
                continue
            sys.stderr.write(f"{s}\n")
            sys.stderr.flush()

    def _wait_for_code(
        self,
        proc: subprocess.Popen[str],
        *,
        email: str,
        deadline: float,
        out_q: queue.Queue[Any],
    ) -> str:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                msg = f"Timed out after waiting for verification email code (mailbox hint: {email})."
                raise TimeoutError(msg)
            try:
                item = out_q.get(timeout=min(2.0, max(0.05, remaining)))
            except queue.Empty:
                rc = proc.poll()
                if rc is not None:
                    err_tail = ""
                    if proc.stderr:
                        try:
                            err_tail = proc.stderr.read()[-4000:]
                        except Exception:
                            err_tail = ""
                    msg = f"QQ listener process exited early (exit {rc})."
                    if err_tail.strip():
                        msg = f"{msg}\n--- stderr tail ---\n{err_tail}"
                    raise QQListenerProcessEnded(msg)
                continue

            if item is _STDOUT_FEED_END:
                rc = proc.poll()
                extra = f" (listener exit={rc})" if rc is not None else ""
                raise QQListenerProcessEnded(
                    f"Listener closed stdout before a verification_code event was received.{extra}",
                )

            line = str(item).strip()
            if not line:
                continue
            try:
                evt: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = evt.get("event")
            if kind == "verification_code":
                return self._normalize_code(str(evt.get("code", "")))
            if kind == "mail_parse_failed":
                reason = str(evt.get("reason", "") or "").strip()
                if reason:
                    sys.stderr.write(f"QQ Mail: parse failed - {reason}\n")
                    sys.stderr.flush()
                continue
            if kind == "session_lost_exit":
                raise QQListenerSessionLost(
                    str(evt.get("reason", "session lost")),
                    payload=evt,
                )
            if kind == "fatal_error":
                raise QQListenerFatalError(str(evt.get("reason", "fatal_error")), payload=evt)

    def _wait_for_ready(self, proc: subprocess.Popen[str], *, out_q: queue.Queue[Any], timeout_sec: float) -> None:
        deadline = time.monotonic() + float(timeout_sec)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("QQ listener init timed out before listener_ready.")
            try:
                item = out_q.get(timeout=min(1.5, max(0.05, remaining)))
            except queue.Empty:
                rc = proc.poll()
                if rc is not None:
                    raise QQListenerProcessEnded(f"QQ listener exited during init (exit {rc}).")
                continue
            if item is _STDOUT_FEED_END:
                rc = proc.poll()
                extra = f" (listener exit={rc})" if rc is not None else ""
                raise QQListenerProcessEnded(f"QQ listener closed stdout during init{extra}")
            line = str(item).strip()
            if not line:
                continue
            try:
                evt: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = evt.get("event")
            if kind == "listener_ready":
                return
            if kind == "fatal_error":
                raise QQListenerFatalError(str(evt.get("reason", "fatal_error")), payload=evt)
            if kind == "session_lost_exit":
                raise QQListenerSessionLost(
                    str(evt.get("reason", "session lost")),
                    payload=evt,
                )

    def receive_code(self, email: str, *, timeout_sec: float = 300) -> str:
        if not self._inited:
            msg = "Call QQMailCheckcodeSource.init() before receive_code()."
            raise RuntimeError(msg)
        self._listener_paths_ok()
        proc = self._active_proc
        out_q = self._out_q
        if proc is None or out_q is None:
            raise QQListenerProcessEnded("QQ listener not running after init().")
        deadline = time.monotonic() + float(timeout_sec)
        return self._wait_for_code(proc, email=email, deadline=deadline, out_q=out_q)
