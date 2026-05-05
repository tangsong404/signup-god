"""QQMailCheckcodeSource: subprocess wiring, criteria propagation, stdout JSON parsing."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from checkcode.mail_match import MailMatchCriteria
from checkcode.qq_mail import (
    QQListenerFatalError,
    QQListenerMaskedCodeError,
    QQListenerProcessEnded,
    QQListenerSessionLost,
    QQMailCheckcodeSource,
)

_CRITERIA = MailMatchCriteria(
    sender_keyword="deepseek",
    subject_keywords=("DeepSeek", "verification code"),
    code_regex=r"(?<![0-9])([0-9]{6})(?![0-9])",
)


class FakeProc:
    """Minimal subprocess.Popen stand-in for stdout streaming."""

    def __init__(self, stdout_body: str) -> None:
        self.stdout = io.StringIO(stdout_body)
        self.stderr = io.StringIO()
        self._rc: int | None = None

    def poll(self) -> int | None:
        return self._rc

    def terminate(self) -> None:
        if self._rc is None:
            self._rc = 15

    def kill(self) -> None:
        self._rc = 9

    def wait(self, timeout: float | None = None) -> int:
        if self._rc is None:
            self._rc = 0
        return self._rc


def _listener_ready_line(run_id: str = "r1") -> str:
    return json.dumps({"event": "listener_ready", "run_id": run_id}, ensure_ascii=False)


def test_from_env_uses_package_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("checkcode.qq_mail.source.load_dotenv", lambda *a, **k: None)
    src = QQMailCheckcodeSource.from_env(criteria=_CRITERIA)
    got = str(src._project_dir).replace("\\", "/")
    assert got.endswith("signup-god")


def test_init_spawns_listener_and_waits_ready_propagates_criteria_via_env() -> None:
    captured: dict[str, object] = {}

    def fake_popen(cmd: list[str], **kwargs: object) -> FakeProc:
        captured["env"] = kwargs.get("env")
        return FakeProc(_listener_ready_line() + "\n")

    src = QQMailCheckcodeSource(criteria=_CRITERIA, popen=fake_popen)
    try:
        src.init()
        assert src._inited
    finally:
        src.close()
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["QQ_MAIL_SENDER_KEYWORD"] == "deepseek"
    assert json.loads(env["QQ_MAIL_SUBJECT_KEYWORDS"]) == ["DeepSeek", "verification code"]
    assert env["QQ_MAIL_CODE_REGEX"] == r"(?<![0-9])([0-9]{6})(?![0-9])"


def test_receive_code_requires_init() -> None:
    src = QQMailCheckcodeSource(criteria=_CRITERIA)
    with pytest.raises(RuntimeError, match="init"):
        src.receive_code("a@b.com", timeout_sec=5)


def test_receive_code_returns_first_verification_code() -> None:
    captured: dict[str, object] = {}

    def fake_popen(cmd: list[str], **kwargs: object) -> FakeProc:
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        lines = [
            _listener_ready_line(),
            json.dumps(
                {
                    "event": "verification_code",
                    "run_id": "r1",
                    "code": "606060",
                    "message_id": "derived-x",
                },
                ensure_ascii=False,
            ),
        ]
        return FakeProc("\n".join(lines) + "\n")

    src = QQMailCheckcodeSource(criteria=_CRITERIA, popen=fake_popen)
    src.init()
    try:
        code = src.receive_code("user@qq.com", timeout_sec=30)
    finally:
        src.close()
    assert code == "606060"
    assert captured["cwd"] == str(Path(__file__).resolve().parents[1])
    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert cmd[1] == "-u"
    assert cmd[2] == "-m"
    assert cmd[3] == "checkcode.qq_mail.cli"


def test_receive_code_masked_raises() -> None:
    def fake_popen(cmd: list[str], **kwargs: object) -> FakeProc:
        lines = [
            _listener_ready_line(),
            json.dumps({"event": "verification_code", "code": "***060"}, ensure_ascii=False),
        ]
        return FakeProc("\n".join(lines) + "\n")

    src = QQMailCheckcodeSource(criteria=_CRITERIA, popen=fake_popen)
    src.init()
    try:
        with pytest.raises(QQListenerMaskedCodeError):
            src.receive_code("u@q.com", timeout_sec=10)
    finally:
        src.close()


def test_receive_code_fatal_error() -> None:
    def fake_popen(cmd: list[str], **kwargs: object) -> FakeProc:
        lines = [
            _listener_ready_line(),
            json.dumps(
                {"event": "fatal_error", "reason": "boom", "exit_code": 20},
                ensure_ascii=False,
            ),
        ]
        return FakeProc("\n".join(lines) + "\n")

    src = QQMailCheckcodeSource(criteria=_CRITERIA, popen=fake_popen)
    src.init()
    try:
        with pytest.raises(QQListenerFatalError) as ei:
            src.receive_code("u@q.com", timeout_sec=10)
        assert ei.value.exit_code == 20
    finally:
        src.close()


def test_receive_code_session_lost() -> None:
    def fake_popen(cmd: list[str], **kwargs: object) -> FakeProc:
        lines = [
            _listener_ready_line(),
            json.dumps(
                {"event": "session_lost_exit", "reason": "cookie", "exit_code": 10},
                ensure_ascii=False,
            ),
        ]
        return FakeProc("\n".join(lines) + "\n")

    src = QQMailCheckcodeSource(criteria=_CRITERIA, popen=fake_popen)
    src.init()
    try:
        with pytest.raises(QQListenerSessionLost):
            src.receive_code("u@q.com", timeout_sec=10)
    finally:
        src.close()


def test_receive_code_stdout_end_without_code() -> None:
    def fake_popen(cmd: list[str], **kwargs: object) -> FakeProc:
        return FakeProc(_listener_ready_line() + "\n")

    src = QQMailCheckcodeSource(criteria=_CRITERIA, popen=fake_popen)
    src.init()
    try:
        with pytest.raises(QQListenerProcessEnded):
            src.receive_code("u@q.com", timeout_sec=5)
    finally:
        src.close()


def test_close_terminates_active_proc() -> None:
    def fake_popen(cmd: list[str], **kwargs: object) -> FakeProc:
        return FakeProc(_listener_ready_line() + "\n")

    src = QQMailCheckcodeSource(criteria=_CRITERIA, popen=fake_popen)
    src.init()
    inner = FakeProc("")
    src._active_proc = inner  # type: ignore[assignment]
    src.close()
    assert inner._rc is not None
