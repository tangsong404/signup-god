"""DeepSeek signup email: language-neutral 6-digit verification code extraction.

Why an anchor-based regex (not a bare ``\\d{6}`` rule):

The QQ-mail listener feeds us **every string field** in the ``/read/readmail`` JSON tree
joined with newlines (mail ids, dir ids, attachment metadata, server timestamps, account
uids, …). Plenty of those happen to be 6-digit numeric runs surrounded by non-digits — so
a plain ``(?<![0-9])([0-9]{6})(?![0-9])`` regex routinely returns the *wrong* number,
which then makes ``POST /api/v0/users/register`` fail with::

    biz_code=8 biz_msg='EMAIL_VERIFY_FAILED'

Anchoring on the verification template ("verification code" / "verify your email" /
"验证码" / …) and only then scanning for the nearest 6-digit run massively reduces those
false positives. The DeepSeek mail template includes one of these phrases in both
English and Chinese variants observed in the wild.
"""

# (?s) -> dot matches newline, (?i) -> case-insensitive. Anchor must appear within 450
# characters before the digits, and the digits themselves must not be embedded inside a
# longer numeric run.
VERIFICATION_CODE_BODY_REGEX = (
    r"(?si)"
    r"(?:"
    r"verification\s+code|email\s+verification|verify\s+(?:your\s+)?email|"
    r"your\s+(?:deepseek\s+)?(?:verification|email)\s+code|"
    r"sign[- ]?up\s+code|use\s+this\s+code|code\s*below|thecode\s+below|"
    r"code\s+will\s+expire|expires?\s+in|"
    r"验证码|邮箱\s*验证|注册\s*验证|您的\s*(?:[^0-9\s]{0,12})?验证"
    r")"
    r"[\s\S]{0,450}?"
    r"(?<![0-9])([0-9]{6})(?![0-9])"
)
