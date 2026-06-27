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


class MetaProvider:
    """Facebook Login (Graph API) — shared base for Facebook Pages and Instagram.

    A single Meta app backs both platforms; only the requested scopes, redirect URI,
    and post-auth profile lookup differ. Meta issues no refresh token — instead a
    short-lived token is exchanged for a long-lived (~60 day) token, which can later
    be re-extended with ``fb_exchange_token``.
    """

    GRAPH_VERSION = "v21.0"
    DIALOG_URL = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth"
    GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"

    def __init__(self, platform: str, redirect_setting: str, scopes: list[str]):
        self.platform = platform
        self._redirect_setting = redirect_setting
        self.scopes = scopes

    @property
    def redirect_uri(self) -> str:
        return getattr(settings, self._redirect_setting)

    def build_auth_url(self, state: str) -> str:
        params = {
            "client_id": settings.META_APP_ID,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": ",".join(self.scopes),
            "state": state,
        }
        return f"{self.DIALOG_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict:
        """Exchange the auth code for a short-lived token, then upgrade to long-lived."""
        short = requests.get(
            f"{self.GRAPH}/oauth/access_token",
            params={
                "client_id": settings.META_APP_ID,
                "client_secret": settings.META_APP_SECRET,
                "redirect_uri": self.redirect_uri,
                "code": code,
            },
            timeout=REQUEST_TIMEOUT,
        )
        short.raise_for_status()
        short_token = short.json()["access_token"]

        long = requests.get(
            f"{self.GRAPH}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.META_APP_ID,
                "client_secret": settings.META_APP_SECRET,
                "fb_exchange_token": short_token,
            },
            timeout=REQUEST_TIMEOUT,
        )
        long.raise_for_status()
        return long.json()  # { access_token, token_type, expires_in }

    def refresh_access_token(self, token: str) -> dict:
        """Re-extend a still-valid long-lived token (Meta has no refresh token)."""
        resp = requests.get(
            f"{self.GRAPH}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.META_APP_ID,
                "client_secret": settings.META_APP_SECRET,
                "fb_exchange_token": token,
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def fetch_profile(self, access_token: str) -> dict:
        """Facebook profile (the connected user/account name)."""
        resp = requests.get(
            f"{self.GRAPH}/me",
            params={"fields": "id,name", "access_token": access_token},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "externalId": data.get("id", ""),
            "displayName": data.get("name", ""),
            "handle": "",
            "avatarUrl": None,
        }


class InstagramProvider(MetaProvider):
    """Instagram via Facebook Login — resolves the IG Business account linked to a Page."""

    def fetch_profile(self, access_token: str) -> dict:
        pages = requests.get(
            f"{self.GRAPH}/me/accounts",
            params={"fields": "name,instagram_business_account", "access_token": access_token},
            timeout=REQUEST_TIMEOUT,
        )
        pages.raise_for_status()
        for page in pages.json().get("data", []):
            ig = page.get("instagram_business_account")
            if not ig:
                continue
            ig_id = ig["id"]
            profile = requests.get(
                f"{self.GRAPH}/{ig_id}",
                params={"fields": "username,profile_picture_url", "access_token": access_token},
                timeout=REQUEST_TIMEOUT,
            )
            profile.raise_for_status()
            data = profile.json()
            return {
                "externalId": ig_id,
                "displayName": data.get("username", ""),
                "handle": data.get("username", ""),
                "avatarUrl": data.get("profile_picture_url"),
            }
        # No Instagram Professional account linked to any of the user's Pages.
        return {}


# Scopes are split into "connect now" vs "publish later":
#   - Login/connect works today with only default scopes.
#   - The page/IG publishing scopes (pages_manage_posts, pages_read_engagement,
#     pages_show_list, instagram_content_publish, …) are "Invalid Scopes" until they're
#     enabled on the Meta app AND approved via App Review. Requesting an un-enabled scope
#     makes Meta reject the ENTIRE consent screen — so we only request them once they're
#     enabled. Flip FACEBOOK_PUBLISH_ENABLED / INSTAGRAM_PUBLISH_ENABLED to True after the
#     permissions are added + approved in the Meta dashboard.
FACEBOOK_PUBLISH_ENABLED = False
INSTAGRAM_PUBLISH_ENABLED = False

FACEBOOK_PUBLISH_SCOPES = [
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
]
INSTAGRAM_PUBLISH_SCOPES = [
    "instagram_basic",
    "instagram_content_publish",
    "pages_show_list",
    "pages_read_engagement",
    "business_management",
]

FACEBOOK_SCOPES = ["public_profile"] + (FACEBOOK_PUBLISH_SCOPES if FACEBOOK_PUBLISH_ENABLED else [])
INSTAGRAM_SCOPES = ["public_profile"] + (INSTAGRAM_PUBLISH_SCOPES if INSTAGRAM_PUBLISH_ENABLED else [])

# Registry of implemented providers. Unknown platform => 400; known platform
# (in SocialAccount.PLATFORM_CHOICES) but absent here => 501 "not available yet".
PROVIDERS = {
    "youtube": YouTubeProvider(),
    "facebook": MetaProvider("facebook", "FACEBOOK_OAUTH_REDIRECT_URI", FACEBOOK_SCOPES),
    "instagram": InstagramProvider("instagram", "INSTAGRAM_OAUTH_REDIRECT_URI", INSTAGRAM_SCOPES),
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
