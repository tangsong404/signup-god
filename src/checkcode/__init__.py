"""Pluggable verification-code sources: protocol, mail-match criteria, manual / QQ-mail impls."""

from checkcode.base import CheckcodeSource
from checkcode.mail_match import MailMatchCriteria
from checkcode.manual import ManualCheckcodeSource
from checkcode.qq_mail import (
    QQListenerError,
    QQListenerFatalError,
    QQListenerMaskedCodeError,
    QQListenerProcessEnded,
    QQListenerSessionLost,
    QQMailCheckcodeSource,
)

__all__ = [
    "CheckcodeSource",
    "MailMatchCriteria",
    "ManualCheckcodeSource",
    "QQListenerError",
    "QQListenerFatalError",
    "QQListenerMaskedCodeError",
    "QQListenerProcessEnded",
    "QQListenerSessionLost",
    "QQMailCheckcodeSource",
]
