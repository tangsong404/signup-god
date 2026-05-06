"""Mail-side matching criteria a registrar passes to a generic mail checkcode source."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MailMatchCriteria:
    """
    Pure data: which inbox mails belong to a particular signup, and how to extract the code.

    - ``sender_keyword``: case-insensitive substring matched against the sender field.
    - ``subject_keywords``: ANY one (case-insensitive) appearing in the mail subject is enough.
    - ``code_regex``: regex applied to the (HTML-decoded, whitespace-cleaned) mail body / payload text.
      If the pattern has capture groups, the first non-``None`` group is used; otherwise ``group(0)``.
    """

    sender_keyword: str
    subject_keywords: tuple[str, ...]
    code_regex: str
