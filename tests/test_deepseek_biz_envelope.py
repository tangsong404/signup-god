"""Business-layer biz_code handling (HTTP 200 but not success)."""

from __future__ import annotations

import pytest

from registrars.deepseek.registrar import DeepSeekApiError, _raise_if_deepseek_biz_failed


def test_biz_code_nonzero_raises_with_full_body() -> None:
    body = {
        "code": 0,
        "msg": "",
        "data": {"biz_code": 6, "biz_msg": "REGISTER_FROM_MAINLAND", "biz_data": None},
    }
    with pytest.raises(DeepSeekApiError, match="business rejected") as ei:
        _raise_if_deepseek_biz_failed(body)
    assert ei.value.response_json == body


def test_envelope_code_nonzero_raises() -> None:
    body = {"code": 1, "msg": "bad", "data": {}}
    with pytest.raises(DeepSeekApiError, match="envelope rejected"):
        _raise_if_deepseek_biz_failed(body)


def test_missing_biz_code_passes() -> None:
    body = {"code": 0, "data": {"sent": True}}
    _raise_if_deepseek_biz_failed(body)
