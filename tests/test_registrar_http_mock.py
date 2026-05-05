"""HTTP flow against httpx.MockTransport (no real network)."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import httpx
import pytest

from registrars.deepseek.pow import build_prefix, hash_prefix_plus_nonce
from registrars.deepseek.registrar import DeepSeekApiError, DeepSeekRegistrar


def test_extract_session_token_ok() -> None:
    body = {"data": {"biz_data": {"user": {"token": "sess-tok"}}}}
    assert DeepSeekRegistrar.extract_session_token(body) == "sess-tok"


def test_extract_session_token_raises() -> None:
    with pytest.raises(DeepSeekApiError, match="missing.*token"):
        DeepSeekRegistrar.extract_session_token({"code": 0, "data": {"biz_data": {}}})


def _guest_challenge_envelope() -> dict[str, Any]:
    salt = "testsalt"
    exp = 1_700_000_000
    answer = 42
    ch = hash_prefix_plus_nonce(build_prefix(salt, exp), answer).hex()
    return {
        "data": {
            "biz_data": {
                "guest_challenge": {
                    "algorithm": "DeepSeekHashV1",
                    "challenge": ch,
                    "salt": salt,
                    "difficulty": 1000,
                    "signature": "sig",
                    "expire_at": exp,
                }
            }
        }
    }


def test_send_email_code_guest_challenge_and_pow_headers(deepseek_config) -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/v0/users/create_guest_challenge":
            body = json.loads(request.content.decode())
            assert body["target_path"] == "/api/v0/users/create_email_verification_code"
            return httpx.Response(200, json=_guest_challenge_envelope())
        if request.url.path == "/api/v0/users/create_email_verification_code":
            assert request.headers.get("x-ds-guest-pow-response")
            b = json.loads(request.content.decode())
            assert b["email"] == "u@example.com"
            assert b["device_id"] == "test-device-id"
            assert b["scenario"] == "register"
            return httpx.Response(200, json={"data": {"sent": True}})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://chat.test")
    cfg = replace(deepseek_config, base_url="https://chat.test")
    src = type(
        "S",
        (),
        {
            "init": lambda self: None,
            "close": lambda self: None,
            "receive_code": lambda self, email, timeout_sec=300: "000000",
        },
    )()
    reg = DeepSeekRegistrar(checkcode_source=src, config=cfg, http_client=client)
    reg.init()
    try:
        out = reg.send_email_code("u@example.com")
    finally:
        reg.close()
        client.close()
    assert paths == [
        "/api/v0/users/create_guest_challenge",
        "/api/v0/users/create_email_verification_code",
    ]
    assert out == {"data": {"sent": True}}


def test_sign_register_request_shape(deepseek_config) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v0/users/create_guest_challenge":
            b = json.loads(request.content.decode())
            assert b["target_path"] == "/api/v0/users/register"
            return httpx.Response(200, json=_guest_challenge_envelope())
        if request.url.path == "/api/v0/users/register":
            assert request.headers.get("x-ds-guest-pow-response")
            b = json.loads(request.content.decode())
            assert b["locale"] == "en_US"
            assert b["region"] == "US"
            assert b["os"] == "web"
            assert b["device_id"] == "test-device-id"
            assert b["payload"]["email"] == "u@example.com"
            assert b["payload"]["password"] == "pw"
            assert b["payload"]["email_verification_code"] == "111111"
            return httpx.Response(200, json={"code": 0, "data": {"biz_code": 0, "registered": True}})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://chat.test")
    cfg = replace(deepseek_config, base_url="https://chat.test")
    src = type(
        "S",
        (),
        {
            "init": lambda self: None,
            "close": lambda self: None,
            "receive_code": lambda self, email, timeout_sec=300: "000000",
        },
    )()
    reg = DeepSeekRegistrar(checkcode_source=src, config=cfg, http_client=client)
    reg.init()
    try:
        out = reg.sign("u@example.com", "pw", "111111")
    finally:
        reg.close()
        client.close()
    assert out["code"] == 0
    assert out["data"]["biz_code"] == 0


def test_sign_raises_on_register_from_mainland_biz_code(deepseek_config) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v0/users/create_guest_challenge":
            b = json.loads(request.content.decode())
            assert b["target_path"] == "/api/v0/users/register"
            return httpx.Response(200, json=_guest_challenge_envelope())
        if request.url.path == "/api/v0/users/register":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "msg": "",
                    "data": {"biz_code": 6, "biz_msg": "REGISTER_FROM_MAINLAND", "biz_data": None},
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://chat.test")
    cfg = replace(deepseek_config, base_url="https://chat.test")
    src = type(
        "S",
        (),
        {
            "init": lambda self: None,
            "close": lambda self: None,
            "receive_code": lambda self, email, timeout_sec=300: "000000",
        },
    )()
    reg = DeepSeekRegistrar(checkcode_source=src, config=cfg, http_client=client)
    reg.init()
    try:
        with pytest.raises(DeepSeekApiError, match="business rejected"):
            reg.sign("u@example.com", "pw", "111111")
    finally:
        reg.close()
        client.close()


def test_set_birthday_post_shape(deepseek_config) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v0/users/set_birthday":
            seen["auth"] = request.headers.get("authorization")
            b = json.loads(request.content.decode())
            seen["body"] = b
            return httpx.Response(
                200,
                json={"code": 0, "msg": "", "data": {"biz_code": 0, "biz_msg": "", "biz_data": None}},
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://chat.test")
    cfg = replace(deepseek_config, base_url="https://chat.test")
    src = type("S", (), {"init": lambda s: None, "close": lambda s: None})()
    reg = DeepSeekRegistrar(checkcode_source=src, config=cfg, http_client=client)
    reg.init()
    try:
        out = reg.set_birthday("mytoken", 2000, 1)
    finally:
        reg.close()
        client.close()
    assert seen["auth"] == "Bearer mytoken"
    assert seen["body"] == {"year": 2000, "month": 1}
    assert out["data"]["biz_code"] == 0


def test_set_birthday_invalid_month_raises(deepseek_config) -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(404))
    client = httpx.Client(transport=transport, base_url="https://chat.test")
    cfg = replace(deepseek_config, base_url="https://chat.test")
    src = type("S", (), {"init": lambda s: None, "close": lambda s: None})()
    reg = DeepSeekRegistrar(checkcode_source=src, config=cfg, http_client=client)
    reg.init()
    try:
        with pytest.raises(ValueError, match="month"):
            reg.set_birthday("t", 2000, 13)
    finally:
        reg.close()
        client.close()


def test_extract_guest_challenge_raises(deepseek_config) -> None:
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"data": {}})
        if r.url.path == "/api/v0/users/create_guest_challenge"
        else httpx.Response(404),
    )
    client = httpx.Client(transport=transport, base_url="https://chat.test")
    cfg = replace(deepseek_config, base_url="https://chat.test")
    src = type("S", (), {"init": lambda s: None, "close": lambda s: None})()
    reg = DeepSeekRegistrar(checkcode_source=src, config=cfg, http_client=client)
    reg.init()
    try:
        with pytest.raises(DeepSeekApiError, match="guest_challenge"):
            reg.send_email_code("x@y.z")
    finally:
        reg.close()
        client.close()


def test_register_with_random_birthday_uses_shared_flow(monkeypatch: pytest.MonkeyPatch, deepseek_config) -> None:
    paths: list[str] = []
    seen_birthday: dict[str, int] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path == "/api/v0/users/create_guest_challenge":
            b = json.loads(request.content.decode())
            target = b["target_path"]
            if target in ("/api/v0/users/create_email_verification_code", "/api/v0/users/register"):
                return httpx.Response(200, json=_guest_challenge_envelope())
            return httpx.Response(400, json={"msg": "unexpected target"})
        if request.url.path == "/api/v0/users/create_email_verification_code":
            return httpx.Response(200, json={"code": 0, "data": {"biz_code": 0, "biz_msg": "", "biz_data": None}})
        if request.url.path == "/api/v0/users/register":
            return httpx.Response(
                200,
                json={"code": 0, "data": {"biz_code": 0, "biz_msg": "", "biz_data": {"user": {"token": "tok"}}}},
            )
        if request.url.path == "/api/v0/users/set_birthday":
            b = json.loads(request.content.decode())
            seen_birthday["year"] = int(b["year"])
            seen_birthday["month"] = int(b["month"])
            return httpx.Response(200, json={"code": 0, "data": {"biz_code": 0, "biz_msg": "", "biz_data": None}})
        return httpx.Response(404)

    vals = iter([1973, 11])
    monkeypatch.setattr("registrars.deepseek.registrar.random.randint", lambda a, b: next(vals))

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://chat.test")
    cfg = replace(deepseek_config, base_url="https://chat.test")
    src = type(
        "S",
        (),
        {
            "init": lambda self: None,
            "close": lambda self: None,
            "receive_code": lambda self, email, timeout_sec=300: "123456",
        },
    )()
    reg = DeepSeekRegistrar(checkcode_source=src, config=cfg, http_client=client)
    reg.init()
    try:
        out, (y, m) = reg.register_with_random_birthday(email="u@example.com", password="pw")
    finally:
        reg.close()
        client.close()
    assert out["data"]["biz_code"] == 0
    assert (y, m) == (1973, 11)
    assert seen_birthday == {"year": 1973, "month": 11}
    assert paths == [
        "/api/v0/users/create_guest_challenge",
        "/api/v0/users/create_email_verification_code",
        "/api/v0/users/create_guest_challenge",
        "/api/v0/users/register",
        "/api/v0/users/set_birthday",
    ]


def test_send_email_code_risk_device_raises(deepseek_config) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v0/users/create_guest_challenge":
            return httpx.Response(200, json=_guest_challenge_envelope())
        if request.url.path == "/api/v0/users/create_email_verification_code":
            return httpx.Response(
                200,
                json={"code": 0, "data": {"biz_code": 1102, "biz_msg": "RISK_DEVICE_DETECTED", "biz_data": None}},
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport, base_url="https://chat.test")
    cfg = replace(deepseek_config, base_url="https://chat.test")
    src = type("S", (), {"init": lambda s: None, "close": lambda s: None})()
    reg = DeepSeekRegistrar(checkcode_source=src, config=cfg, http_client=client)
    reg.init()
    try:
        with pytest.raises(DeepSeekApiError, match="RISK_DEVICE"):
            reg.send_email_code("u@example.com")
    finally:
        reg.close()
        client.close()
