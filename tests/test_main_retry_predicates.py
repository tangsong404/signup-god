"""Predicates used by ``main.py`` for DeepSeek biz-layer retries."""

from __future__ import annotations

from registrars.deepseek.registrar import DeepSeekApiError

import main as main_module


def _err(payload: dict) -> DeepSeekApiError:
    return DeepSeekApiError("test", status_code=200, response_json=payload)


def test_is_account_already_exists_true() -> None:
    payload = {"code": 0, "msg": "", "data": {"biz_code": 1, "biz_msg": "ACCOUNT_ALREADY_EXISTS", "biz_data": None}}
    assert main_module._is_account_already_exists(_err(payload))


def test_is_account_already_exists_case_insensitive() -> None:
    payload = {"code": 0, "data": {"biz_msg": "account_already_exists"}}
    assert main_module._is_account_already_exists(_err(payload))


def test_is_account_already_exists_false_on_other_msg() -> None:
    payload = {"code": 0, "data": {"biz_msg": "REGISTER_FROM_MAINLAND"}}
    assert not main_module._is_account_already_exists(_err(payload))


def test_is_request_too_frequent_chinese() -> None:
    payload = {"code": 0, "data": {"biz_msg": "REQUEST太过频繁"}}
    assert main_module._is_request_too_frequent(_err(payload))


def test_is_request_too_frequent_english_substring() -> None:
    for msg in ("REQUEST_TOO_FREQUENT", "API_RATE_LIMIT_EXCEEDED"):
        payload = {"code": 0, "data": {"biz_msg": msg}}
        assert main_module._is_request_too_frequent(_err(payload)), msg


def test_is_request_too_frequent_top_level_msg() -> None:
    payload = {"code": 100, "msg": "请求太过频繁", "data": None}
    assert main_module._is_request_too_frequent(_err(payload))


def test_is_request_too_frequent_false() -> None:
    payload = {"code": 0, "data": {"biz_msg": "SOME_OTHER_FAILURE"}}
    assert not main_module._is_request_too_frequent(_err(payload))


def test_deepseek_biz_msg_none_when_missing() -> None:
    assert main_module._deepseek_biz_msg(DeepSeekApiError("no json")) is None
