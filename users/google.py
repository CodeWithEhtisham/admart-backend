"""Google Sign-In: exchange auth code, verify id_token, resolve User."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import jwt
import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from jwt import PyJWKClient

logger = logging.getLogger(__name__)
User = get_user_model()

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}

_jwks_client: PyJWKClient | None = None


NO_ACCOUNT = {
    "code": "no_account",
    "message": "There is no Admart account for this email. Please sign up first, then sign in.",
}


class GoogleAuthError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _jwks() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(GOOGLE_JWKS_URL, cache_keys=True)
    return _jwks_client


def _truthy(value) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1")
    return False


def allowed_redirect_uris() -> set[str]:
    origins: set[str] = set()
    frontend = (getattr(settings, "FRONTEND_URL", "") or "").rstrip("/")
    if frontend:
        origins.add(frontend)
    for origin in getattr(settings, "CORS_ALLOWED_ORIGINS", []) or []:
        if origin:
            origins.add(origin.rstrip("/"))
    return {f"{origin}/auth-callback" for origin in origins}


def _validate_redirect_uri(redirect_uri: str) -> None:
    allowed = allowed_redirect_uris()
    if redirect_uri not in allowed:
        logger.warning("Rejected Google redirect_uri=%s allowed=%s", redirect_uri, allowed)
        raise GoogleAuthError("Google sign-in failed.")
    parsed = urlparse(redirect_uri)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise GoogleAuthError("Google sign-in failed.")


def exchange_code(code: str, redirect_uri: str) -> str:
    """Exchange a one-time auth code for an id_token. Returns the id_token string."""
    client_id = getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "") or ""
    client_secret = getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "") or ""
    if not client_id or not client_secret:
        logger.error("GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET are not set")
        raise GoogleAuthError("Google sign-in is not configured.", 500)

    _validate_redirect_uri(redirect_uri)

    try:
        response = requests.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=15,
        )
    except requests.RequestException as exc:
        logger.warning("Google token endpoint request failed: %s", exc)
        raise GoogleAuthError("Google sign-in failed.") from exc

    if response.status_code != 200:
        logger.warning(
            "Google token exchange failed status=%s body=%s",
            response.status_code,
            response.text[:500],
        )
        raise GoogleAuthError("Google sign-in failed.")

    id_token = (response.json() or {}).get("id_token")
    if not id_token:
        logger.warning("Google token response missing id_token")
        raise GoogleAuthError("Google sign-in failed.")
    return id_token


def verify_id_token(id_token: str) -> dict:
    """Verify signature + iss/aud/exp. Returns Google claims."""
    client_id = getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "") or ""
    if not client_id:
        logger.error("GOOGLE_OAUTH_CLIENT_ID is not set")
        raise GoogleAuthError("Google sign-in is not configured.", 500)

    try:
        signing_key = _jwks().get_signing_key_from_jwt(id_token)
        payload = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=client_id,
            options={"verify_iss": False},
        )
    except Exception as exc:
        logger.warning("Google id_token verification failed: %s", exc)
        raise GoogleAuthError("Google sign-in failed.") from exc

    if payload.get("iss") not in GOOGLE_ISSUERS:
        raise GoogleAuthError("Google sign-in failed.")
    if not payload.get("sub") or not payload.get("email"):
        raise GoogleAuthError("Google sign-in failed.")
    if not _truthy(payload.get("email_verified")):
        raise GoogleAuthError("Google email is not verified.")
    return payload


def should_create_account(intent: str, create_account) -> bool:
    """Register only when the client asked to. Missing flags → login (do not create)."""
    value = (intent or "").strip().lower()
    if value == "login":
        return False
    if value == "register":
        return True
    return create_account is True


def find_user(claims: dict):
    """Look up by Google sub, else verified email. Does not create."""
    sub = claims["sub"]
    email = User.objects.normalize_email(claims["email"])
    user = User.objects.filter(google_id=sub).first()
    if user is None:
        user = User.objects.filter(email__iexact=email).first()
    return user


def _link_google_identity(user, claims: dict):
    sub = claims["sub"]
    first_name = (claims.get("given_name") or "")[:150]
    last_name = (claims.get("family_name") or "")[:150]
    picture = claims.get("picture") or None
    updates = ["email_verified", "updated_at"]
    user.email_verified = True
    if not user.google_id:
        user.google_id = sub
        updates.append("google_id")
    if not user.first_name and first_name:
        user.first_name = first_name
        updates.append("first_name")
    if not user.last_name and last_name:
        user.last_name = last_name
        updates.append("last_name")
    if not user.avatar_url and picture:
        user.avatar_url = picture
        updates.append("avatar_url")
    user.save(update_fields=updates)
    return user


def create_google_user(claims: dict):
    email = User.objects.normalize_email(claims["email"])
    return User.objects.create_user(
        email=email,
        password=None,
        first_name=(claims.get("given_name") or "")[:150],
        last_name=(claims.get("family_name") or "")[:150],
        avatar_url=claims.get("picture") or None,
        google_id=claims["sub"],
        email_verified=True,
        plan="free",
        credits_total=50,
        credits_remaining=50,
    )


def resolve_google_user(claims: dict, *, create: bool):
    """Return existing (and link) or create. None if login and no user."""
    user = find_user(claims)
    if user is not None:
        return _link_google_identity(user, claims)
    if not create:
        return None
    return create_google_user(claims)
