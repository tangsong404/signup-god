"""Pluggable signup identifier producers (email / alias / …)."""

from account_generators.base import AccountIdentifierGenerator
from account_generators.duck import DuckEmailAccountGenerator

__all__ = ["AccountIdentifierGenerator", "DuckEmailAccountGenerator"]
