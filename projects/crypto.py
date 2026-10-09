"""Symmetric encryption helpers for social OAuth tokens at rest.

Tokens are encrypted with Fernet (AES-128-CBC + HMAC). The key comes from
``SOCIAL_TOKEN_ENCRYPTION_KEY`` (comma-separated for rotation; required in
production). In local DEBUG without it, a key derived from ``SECRET_KEY`` is used.
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings


@lru_cache(maxsize=1)
def _fernet() -> MultiFernet:
    # Comma-separated keys: the first encrypts, all decrypt (key rotation).
    keys = [k.strip() for k in (settings.SOCIAL_TOKEN_ENCRYPTION_KEY or "").split(",") if k.strip()]
    if not keys:  # local DEBUG only; settings refuse to start without a key in production
        keys = [base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest()).decode()]
    return MultiFernet([Fernet(k.encode()) for k in keys])


def encrypt(plaintext: str) -> str:
    """Encrypt a string; empty input returns an empty string."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a string; empty input returns an empty string."""
    if not ciphertext:
        return ""
    return _fernet().decrypt(ciphertext.encode()).decode()
