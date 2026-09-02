"""Symmetric encryption helpers for social OAuth tokens at rest.

Tokens are encrypted with Fernet (AES-128-CBC + HMAC). The key comes from
``SOCIAL_TOKEN_ENCRYPTION_KEY`` when set; otherwise a stable key is derived from
``SECRET_KEY`` so development works out of the box. Set an explicit key in production.
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet
from django.conf import settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = settings.SOCIAL_TOKEN_ENCRYPTION_KEY
    if key:
        return Fernet(key.encode() if isinstance(key, str) else key)
    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


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
