"""Encryption for OAuth tokens stored at rest.

Calendar refresh tokens are long-lived credentials to a user's calendar, so they
are encrypted in the database rather than stored in the clear. The key lives in
CALENDAR_TOKEN_KEY, outside the database, so a dump or backup leak is not enough
to read them.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import LargeBinary
from sqlalchemy.types import TypeDecorator

from app.config import settings


class TokenKeyMissing(RuntimeError):
    """CALENDAR_TOKEN_KEY is unset or malformed."""


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = settings.calendar_token_key
    if not key:
        raise TokenKeyMissing(
            "CALENDAR_TOKEN_KEY is not set. Generate one with:\n"
            '  python3 -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    try:
        return Fernet(key)
    except (ValueError, TypeError) as exc:
        raise TokenKeyMissing(
            "CALENDAR_TOKEN_KEY is not a valid Fernet key (44-char urlsafe base64)."
        ) from exc


def encrypt(value: str) -> bytes:
    return _fernet().encrypt(value.encode())


def decrypt(value: bytes) -> str:
    return _fernet().decrypt(bytes(value)).decode()


class EncryptedString(TypeDecorator):
    """Transparently encrypts a string column.

    Values are ciphertext in the database and plain `str` on the model, so
    callers never handle encryption directly. Note this makes the column
    unsearchable: Fernet output is non-deterministic, so equality filters on it
    will never match. Query by user/provider instead.
    """

    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> bytes | None:
        return None if value is None else encrypt(value)

    def process_result_value(self, value: bytes | None, dialect) -> str | None:
        return None if value is None else decrypt(value)


__all__ = ["EncryptedString", "InvalidToken",
           "TokenKeyMissing", "decrypt", "encrypt"]
