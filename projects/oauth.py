"""Provider-specific OAuth logic for social account connections.

Each provider knows how to build its authorization URL, exchange an auth code for
tokens, refresh tokens, and fetch the connected account's public profile. New
platforms register here without touching the views or the data model.
"""

from urllib.parse import urlencode

import requests
from django.conf import settings

REQUEST_TIMEOUT = 15


class YouTubeProvider:
    """Google OAuth 2.0 for the YouTube Data API (read profile + upload videos)."""

    platform = "youtube"
    AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
    SCOPES = [
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/youtube.upload",
    ]

    def build_auth_url(self, state: str) -> str:
        """Build the Google consent URL. offline + consent => always get a refresh token."""
        params = {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "redirect_uri": settings.YOUTUBE_OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(self.SCOPES),
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict:
        """Exchange an authorization code for access + refresh tokens."""
        resp = requests.post(
            self.TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                "redirect_uri": settings.YOUTUBE_OAUTH_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def refresh_access_token(self, refresh_token: str) -> dict:
        """Get a fresh access token using a stored refresh token."""
        resp = requests.post(
            self.TOKEN_URL,
            data={
                "refresh_token": refresh_token,
                "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                "grant_type": "refresh_token",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def fetch_profile(self, access_token: str) -> dict:
        """Fetch the authorized user's YouTube channel profile."""
        resp = requests.get(
            self.CHANNELS_URL,
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            return {}
        channel = items[0]
        snippet = channel.get("snippet", {}) or {}
        thumbnails = snippet.get("thumbnails", {}) or {}
        default_thumb = thumbnails.get("default", {}) or {}
        return {
            "externalId": channel.get("id", ""),
            "displayName": snippet.get("title", ""),
            "handle": snippet.get("customUrl", ""),
            "avatarUrl": default_thumb.get("url"),
        }


# Registry of implemented providers. Unknown platform => 400; known platform
# (in SocialAccount.PLATFORM_CHOICES) but absent here => 501 "not available yet".
PROVIDERS = {
    "youtube": YouTubeProvider(),
}


def ensure_fresh_access_token(account) -> str:
    """Return a valid access token for the account, refreshing if near expiry.

    Refreshes when the token expires within 2 minutes (or has no expiry recorded)
    and a refresh token is available. Persists the refreshed token.
    """
    from django.utils import timezone

    provider = PROVIDERS.get(account.platform)
    if provider is None:
        return account.get_access_token()

    expires_at = account.token_expires_at
    if expires_at and (expires_at - timezone.now()).total_seconds() > 120:
        return account.get_access_token()

    refresh_token = account.get_refresh_token()
    if not refresh_token:
        return account.get_access_token()

    tokens = provider.refresh_access_token(refresh_token)
    account.store_tokens(
        access_token=tokens.get("access_token"),
        expires_in=tokens.get("expires_in"),
        scope=tokens.get("scope"),
    )
    account.save(update_fields=["access_token", "token_expires_at", "scope", "updated_at"])
    return account.get_access_token()
