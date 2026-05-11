"""A permissive email type.

``pydantic.EmailStr`` (via ``email-validator``) rejects RFC-reserved TLDs
such as ``.local`` — but those are exactly what the seeded demo accounts use
(``host@livequiz.local`` etc.). Those addresses must be accepted on login and
must round-trip through response models such as ``UserPublic``, so we keep a
light syntactic check (``local@domain``, no whitespace) instead of full RFC
deliverability validation. Login/lookup matches against stored values anyway,
so strict format validation buys nothing there.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import AfterValidator


def _validate_email_shape(value: str) -> str:
    value = value.strip()
    local, sep, domain = value.partition("@")
    if not sep or not local or not domain or "@" in domain:
        raise ValueError("value is not a valid email address")
    if any(ch.isspace() for ch in value):
        raise ValueError("value is not a valid email address")
    # Domain part is case-insensitive — normalise it the way EmailStr did so
    # lookups stay stable. The local part is left untouched.
    return f"{local}@{domain.lower()}"


LooseEmailStr = Annotated[str, AfterValidator(_validate_email_shape)]
