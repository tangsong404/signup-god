"""DeepSeek verification-code extraction is anchored on the mail template.

Goal: avoid the EMAIL_VERIFY_FAILED bug we hit when a bare ``\\d{6}`` regex picked up
6-digit runs from QQ Mail's readmail JSON metadata (mail/dir/attachment ids, etc.)
instead of the real verification code.
"""

from __future__ import annotations

import re

from checkcode.qq_mail.core import MessageMatcher, extract_first_capture_or_whole
from registrars.deepseek.verification_mail import VERIFICATION_CODE_BODY_REGEX


def _matcher() -> MessageMatcher:
    return MessageMatcher(
        sender_keyword="",
        subject_keywords=[],
        code_regex=VERIFICATION_CODE_BODY_REGEX,
    )


def test_extracts_code_from_english_deepseek_template() -> None:
    body = (
        "Hello,\n\nYour DeepSeek verification code is:\n\n  887766\n\n"
        "This code expires in 10 minutes."
    )
    assert _matcher().extract_code("noreply@deepseek.com", "DeepSeek verification code", body) == "887766"


def test_extracts_code_from_chinese_deepseek_template() -> None:
    body = (
        "您好,\n\n您的 DeepSeek 邮箱验证码是:\n\n  778899\n\n"
        "该验证码将在 10 分钟后失效。"
    )
    assert _matcher().extract_code("noreply@deepseek.com", "DeepSeek 验证码", body) == "778899"


def test_extracts_code_from_html_template() -> None:
    body = (
        "<p>Use this code to verify your email address:</p>"
        "<div class=\"code\">123456</div>"
        "<p>It will expire in 10 minutes.</p>"
    )
    assert _matcher().extract_code("noreply@deepseek.com", "Verify your email", body) == "123456"


def test_extracts_code_from_duck_preview_with_thecode_below_variant() -> None:
    body = (
        "DuckDuckGo did not detect any trackers. More Deactivate Hello, x@duck.com "
        "To continue setting up your DeepSeek account, please verify your account with "
        "thecode below: 407074 This code will expire in 5 days."
    )
    assert _matcher().extract_code("deepseek_at_al.mail.deepseek.com_x@duck.com", "Your verification code for DeepSeek", body) == "407074"


def test_ignores_unrelated_six_digit_runs_without_anchor() -> None:
    """QQ-mail JSON metadata frequently contains 6-digit ids; those must NOT match."""
    body = "mailid:567890\ndirid 234567\nattachment_id=345678\n(no verification keyword)"
    assert _matcher().extract_code("x", "y", body) is None


def test_picks_code_after_anchor_not_unrelated_earlier_run() -> None:
    body = (
        "noise 234567 padding 567890 more padding "
        "Your DeepSeek verification code is:\n\n887766\n\nbye"
    )
    assert _matcher().extract_code("x", "y", body) == "887766"


def test_skips_seven_digit_run_after_anchor() -> None:
    body = "Your DeepSeek verification code is 12345678 not real"
    # 7+ digits flanking the run violate the (?<![0-9])...(?![0-9]) boundary; no extraction.
    assert _matcher().extract_code("x", "y", body) is None


def test_extract_first_capture_helper_handles_single_group() -> None:
    rr = re.compile(VERIFICATION_CODE_BODY_REGEX)
    m = rr.search("verification code is 991199!")
    assert m is not None
    assert extract_first_capture_or_whole(m) == "991199"
