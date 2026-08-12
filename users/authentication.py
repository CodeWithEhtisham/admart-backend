import base64
import logging
import jwt
from jwt import PyJWKClient
import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication as SimpleJWTAuthentication

logger = logging.getLogger(__name__)
User = get_user_model()

_JWKS_CLIENT_CACHE = {}


def _get_jwks_client(jwks_url: str) -> PyJWKClient:
    """Retrieve or cache PyJWKClient instance for a given JWKS URL."""
    if jwks_url not in _JWKS_CLIENT_CACHE:
        _JWKS_CLIENT_CACHE[jwks_url] = PyJWKClient(jwks_url, cache_keys=True)
    return _JWKS_CLIENT_CACHE[jwks_url]


def _derive_jwks_url_from_publishable_key(publishable_key: str) -> str:
    """Derive JWKS URL from a Clerk publishable key (pk_test_... or pk_live_...)."""
    if not publishable_key:
        return ""
    try:
        parts = publishable_key.split("_", 2)
        if len(parts) >= 3:
            raw_b64 = parts[2]
            raw_b64 += "=" * ((4 - len(raw_b64) % 4) % 4)
            decoded = base64.b64decode(raw_b64).decode("utf-8").rstrip("$")
            if decoded:
                return f"https://{decoded}/.well-known/jwks.json"
    except Exception as exc:
        logger.debug("Failed to parse Clerk publishable key: %s", exc)
    return ""


class ClerkJWTAuthentication(BaseAuthentication):
    """DRF Authentication class for Clerk JWT session tokens."""

    def authenticate_header(self, request):
        return 'Bearer realm="api"'

    def authenticate(self, request):
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None

        raw_token = parts[1]

        # Quick check: attempt to unverify payload to get issuer
        try:
            unverified_payload = jwt.decode(raw_token, options={"verify_signature": False})
        except Exception:
            return None

        iss = unverified_payload.get("iss", "")

        # Determine JWKS URL
        jwks_url = getattr(settings, "CLERK_JWKS_URL", "")
        if not jwks_url:
            if iss.startswith("http"):
                jwks_url = f"{iss.rstrip('/')}/.well-known/jwks.json"
            else:
                pub_key = getattr(settings, "CLERK_PUBLISHABLE_KEY", "")
                jwks_url = _derive_jwks_url_from_publishable_key(pub_key)

        if not jwks_url:
            return None

        # Verify signature with PyJWKClient
        try:
            jwks_client = _get_jwks_client(jwks_url)
            signing_key = jwks_client.get_signing_key_from_jwt(raw_token)
            payload = jwt.decode(
                raw_token,
                signing_key.key,
                algorithms=["RS256", "RS384", "RS512", "EdDSA"],
                options={"verify_aud": False},
            )
        except Exception as exc:
            logger.warning("Clerk JWT verification failed: %s", exc)
            raise AuthenticationFailed("Invalid Clerk authentication token.") from exc

        clerk_user_id = payload.get("sub")
        if not clerk_user_id:
            raise AuthenticationFailed("Clerk token missing subject.")

        # Find or create Django user
        user = User.objects.filter(google_id=clerk_user_id).first()
        if not user:
            email = payload.get("email") or payload.get("email_address")
            first_name = payload.get("first_name") or ""
            last_name = payload.get("last_name") or ""
            avatar_url = payload.get("image_url") or ""

            clerk_secret_key = getattr(settings, "CLERK_SECRET_KEY", "")
            if not email and clerk_secret_key:
                try:
                    resp = requests.get(
                        f"https://api.clerk.com/v1/users/{clerk_user_id}",
                        headers={"Authorization": f"Bearer {clerk_secret_key}"},
                        timeout=5,
                    )
                    if resp.status_code == 200:
                        clerk_data = resp.json()
                        email_addresses = clerk_data.get("email_addresses", [])
                        if email_addresses:
                            email = email_addresses[0].get("email_address")
                        first_name = clerk_data.get("first_name") or first_name
                        last_name = clerk_data.get("last_name") or last_name
                        avatar_url = clerk_data.get("image_url") or avatar_url
                except Exception as exc:
                    logger.warning("Failed to fetch user profile from Clerk API: %s", exc)

            if not email:
                email = f"{clerk_user_id}@clerk.user"

            user = User.objects.filter(email=email).first()
            if user:
                user.google_id = clerk_user_id
                user.save(update_fields=["google_id", "updated_at"])
            else:
                user = User.objects.create(
                    email=email,
                    google_id=clerk_user_id,
                    first_name=first_name,
                    last_name=last_name,
                    avatar_url=avatar_url,
                    plan="free",
                    credits_total=50,
                    credits_remaining=50,
                )

        return (user, raw_token)


class CombinedJWTAuthentication(BaseAuthentication):
    """Try SimpleJWT first, fallback to Clerk JWT if SimpleJWT fails."""

    def authenticate_header(self, request):
        return 'Bearer realm="api"'

    def authenticate(self, request):
        simple_jwt_auth = SimpleJWTAuthentication()
        try:
            res = simple_jwt_auth.authenticate(request)
            if res is not None:
                return res
        except Exception:
            pass

        clerk_auth = ClerkJWTAuthentication()
        return clerk_auth.authenticate(request)
