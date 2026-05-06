from __future__ import annotations

import random
import sys
from typing import TYPE_CHECKING, Any, Callable

import httpx

from checkcode.mail_match import MailMatchCriteria
from registrars.deepseek.config import DeepSeekConfig
from registrars.deepseek.pow import solve_guest_challenge

if TYPE_CHECKING:
    from checkcode.base import CheckcodeSource

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _http_headers(cfg: DeepSeekConfig) -> dict[str, str]:
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "user-agent": _DEFAULT_USER_AGENT,
        "x-app-version": cfg.app_version,
        "x-client-locale": cfg.locale,
        "x-client-platform": cfg.client_platform,
        "x-client-timezone-offset": str(cfg.timezone_offset_minutes),
        "x-client-version": cfg.client_version,
    }


class DeepSeekApiError(RuntimeError):
    """HTTP failure, malformed envelope, or DeepSeek ``code`` / ``data.biz_code`` business rejection."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_json: object | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_json = response_json


def _coerce_int_code(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("-"):
            rest = s[1:]
            if rest.isdigit():
                return int(s)
        if s.isdigit():
            return int(s)
    return None


def _raise_if_deepseek_biz_failed(body: dict[str, Any]) -> None:
    """
    DeepSeek chat APIs often return HTTP 200 with ``code: 0`` but set ``data.biz_code`` non-zero
    for business failures (e.g. REGISTER_FROM_MAINLAND). Treat that as an error so callers do
    not mistake printed JSON for success.
    """
    env_code = _coerce_int_code(body.get("code"))
    if env_code is not None and env_code != 0:
        msg = f"DeepSeek envelope rejected: code={env_code!r} msg={body.get('msg')!r}"
        raise DeepSeekApiError(msg, response_json=body)
    inner = body.get("data")
    if not isinstance(inner, dict):
        return
    biz = _coerce_int_code(inner.get("biz_code"))
    if biz is not None and biz != 0:
        bm = inner.get("biz_msg")
        msg = f"DeepSeek business rejected: biz_code={biz} biz_msg={bm!r}"
        if isinstance(bm, str):
            u = bm.upper()
            if "RECAPTCHA" in u:
                msg += (
                    " - Turnstile/reCAPTCHA failed: complete the check in a real browser session "
                    "and retry with a fresh signup attempt if your client supports passing a token."
                )
            elif "MAINLAND" in u:
                msg += (
                    " - Region / compliance: use an officially allowed signup path for your network."
                )
            elif "RISK_DEVICE" in u:
                msg += " - Device risk: update DEEPSEEK_DEVICE_ID in .env to a valid value from a real browser session."
        raise DeepSeekApiError(msg, status_code=200, response_json=body)


class DeepSeekRegistrar:
    """Send-code -> verify -> register; optional ``set_birthday`` with session token (see examples)."""

    @staticmethod
    def mail_match_criteria() -> MailMatchCriteria:
        """Sender / subject / code regex used by a mail checkcode source to find DeepSeek's signup mail."""
        return MailMatchCriteria(
            sender_keyword="deepseek",
            subject_keywords=("DeepSeek", "verification code", "验证码"),
            code_regex=r"(?<![0-9])([0-9]{6})(?![0-9])",
        )

    def __init__(
        self,
        *,
        checkcode_source: CheckcodeSource,
        config: DeepSeekConfig,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._checkcode_source = checkcode_source
        self._config = config
        self._client = http_client
        self._own_client = http_client is None
        self._initialized = False

    def __enter__(self) -> DeepSeekRegistrar:
        return self

    def __exit__(self, exc_type: object, exc: BaseException | None, tb: object) -> None:
        self.close()

    def _require_client(self) -> httpx.Client:
        self._require_initialized()
        if self._client is None:
            msg = "Call init() before HTTP operations on DeepSeekRegistrar."
            raise RuntimeError(msg)
        return self._client

    def _require_initialized(self) -> None:
        if not self._initialized:
            msg = "Call init() and wait for completion before registration steps."
            raise RuntimeError(msg)

    @staticmethod
    def _stderr_log(msg: str) -> None:
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()

    def init(self) -> None:
        self._stderr_log("[deepseek_registrar] init() ...")
        self._initialized = False
        try:
            self._checkcode_source.init()
            if self._own_client:
                if self._client is not None:
                    self._client.close()
                self._client = httpx.Client(
                    base_url=self._config.base_url,
                    headers=_http_headers(self._config),
                    timeout=120.0,
                )
            self._initialized = True
            self._stderr_log("[deepseek_registrar] init done.")
        except Exception:
            try:
                self._checkcode_source.close()
            except Exception:
                pass
            if self._own_client and self._client is not None:
                self._client.close()
                self._client = None
            raise

    def close(self) -> None:
        self._initialized = False
        self._checkcode_source.close()
        if self._own_client and self._client is not None:
            self._client.close()
            self._client = None

    @staticmethod
    def _extract_guest_challenge(body: dict[str, Any]) -> dict[str, Any]:
        try:
            gc = body["data"]["biz_data"]["guest_challenge"]
        except (KeyError, TypeError) as e:
            raise DeepSeekApiError(
                "Response missing data.biz_data.guest_challenge",
                response_json=body,
            ) from e
        if not isinstance(gc, dict):
            msg = "guest_challenge must be an object"
            raise DeepSeekApiError(msg, response_json=body)
        return gc

    @staticmethod
    def _expire_at_for_pow(gc: dict[str, Any]) -> int:
        if "expire_at" in gc:
            return int(gc["expire_at"])
        if "expireAt" in gc:
            return int(gc["expireAt"])
        msg = "guest_challenge missing expire_at / expireAt (required for PoW prefix)"
        raise DeepSeekApiError(msg, response_json=gc)

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        try:
            payload = resp.json()
        except ValueError:
            payload = None
        raise DeepSeekApiError(
            f"HTTP {resp.status_code} from {resp.request.url!s}",
            status_code=resp.status_code,
            response_json=payload,
        )

    def _guest_pow_header_for_target(self, target_path: str) -> str:
        client = self._require_client()
        r = client.post(
            "/api/v0/users/create_guest_challenge",
            json={"target_path": target_path},
        )
        self._raise_for_status(r)
        body = r.json()
        if not isinstance(body, dict):
            msg = "create_guest_challenge response must be a JSON object"
            raise DeepSeekApiError(msg, status_code=r.status_code)
        gc = self._extract_guest_challenge(body)
        if gc.get("algorithm") != "DeepSeekHashV1":
            msg = f"Unsupported guest PoW algorithm: {gc.get('algorithm')!r}"
            raise DeepSeekApiError(msg, response_json=gc)
        difficulty = int(gc.get("difficulty") or 144_000)
        expire_at = self._expire_at_for_pow(gc)
        _, header = solve_guest_challenge(
            challenge_hex=str(gc["challenge"]),
            salt=str(gc["salt"]),
            expire_at=expire_at,
            difficulty=difficulty,
        )
        return header

    def send_email_code(self, email: str) -> dict[str, Any]:
        target = "/api/v0/users/create_email_verification_code"
        header = self._guest_pow_header_for_target(target)
        client = self._require_client()
        r = client.post(
            target,
            json={
                "email": email,
                "locale": self._config.locale,
                "scenario": "register",
                "device_id": self._config.device_id,
                "turnstile_token": self._config.turnstile_token,
            },
            headers={"X-DS-Guest-PoW-Response": header},
        )
        self._raise_for_status(r)
        data = r.json()
        if not isinstance(data, dict):
            msg = "create_email_verification_code response must be a JSON object"
            raise DeepSeekApiError(msg, status_code=r.status_code)
        _raise_if_deepseek_biz_failed(data)
        return data

    def wait_checkcode(self, email: str, *, timeout_sec: float = 300) -> str:
        self._require_initialized()
        return self._checkcode_source.receive_code(email, timeout_sec=timeout_sec)

    @staticmethod
    def random_birthday() -> tuple[int, int]:
        """Random birthday range required by current flow: year 1970..2005, month 1..12."""
        return random.randint(1970, 2005), random.randint(1, 12)

    def sign(self, email: str, password: str, email_verification_code: str) -> dict[str, Any]:
        target = "/api/v0/users/register"
        header = self._guest_pow_header_for_target(target)
        client = self._require_client()
        r = client.post(
            target,
            json={
                "locale": self._config.locale,
                "region": self._config.region,
                "os": "web",
                "device_id": self._config.device_id,
                "payload": {
                    "email": email,
                    "email_verification_code": email_verification_code,
                    "password": password,
                },
            },
            headers={"X-DS-Guest-PoW-Response": header},
        )
        self._raise_for_status(r)
        data = r.json()
        if not isinstance(data, dict):
            msg = "register response must be a JSON object"
            raise DeepSeekApiError(msg, status_code=r.status_code)
        _raise_if_deepseek_biz_failed(data)
        return data

    @staticmethod
    def extract_session_token(register_body: dict[str, Any]) -> str:
        """Bearer token from ``POST .../register`` JSON at ``data.biz_data.user.token``."""
        try:
            inner = register_body["data"]["biz_data"]
            if not isinstance(inner, dict):
                raise KeyError
            user = inner["user"]
            if not isinstance(user, dict):
                raise KeyError
            tok = user.get("token")
            if not tok:
                raise KeyError
        except (KeyError, TypeError) as e:
            raise DeepSeekApiError(
                "Register response missing data.biz_data.user.token",
                response_json=register_body,
            ) from e
        return str(tok)

    def set_birthday(self, bearer_token: str, year: int, month: int) -> dict[str, Any]:
        """POST ``/api/v0/users/set_birthday`` (authenticated). ``month`` is 1..12."""
        if month < 1 or month > 12:
            msg = "set_birthday: month must be in 1..12"
            raise ValueError(msg)
        if year < 1900 or year > 2100:
            msg = "set_birthday: year out of allowed range"
            raise ValueError(msg)
        client = self._require_client()
        r = client.post(
            "/api/v0/users/set_birthday",
            json={"year": year, "month": month},
            headers={"Authorization": f"Bearer {bearer_token}"},
        )
        self._raise_for_status(r)
        data = r.json()
        if not isinstance(data, dict):
            msg = "set_birthday response must be a JSON object"
            raise DeepSeekApiError(msg, status_code=r.status_code)
        _raise_if_deepseek_biz_failed(data)
        return data

    def register_with_random_birthday(
        self,
        *,
        email: str,
        password: str,
        checkcode_timeout_sec: float = 300,
        log: Callable[[str], None] | None = None,
    ) -> tuple[dict[str, Any], tuple[int, int]]:
        """
        End-to-end registration flow shared by examples:
        send code -> receive code -> register -> set random birthday.
        """
        emit = log or self._stderr_log
        emit("[deepseek_registrar] send_email_code() ...")
        self.send_email_code(email)
        emit("[deepseek_registrar] send_email_code done.")
        emit("[deepseek_registrar] waiting for verification code ...")
        code = self.wait_checkcode(email, timeout_sec=checkcode_timeout_sec)
        emit("[deepseek_registrar] sign() ...")
        result = self.sign(email, password, code)
        emit("Registration succeeded.")
        token = self.extract_session_token(result)
        year, month = self.random_birthday()
        emit(f"[deepseek_registrar] set_birthday() with random year={year}, month={month}")
        self.set_birthday(token, year, month)
        emit("Birthday set successfully.")
        return result, (year, month)
