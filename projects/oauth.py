"""Provider-specific OAuth logic for social account connections.

Each provider knows how to build its authorization URL, exchange an auth code for
tokens, refresh tokens, and fetch the connected account's public profile. New
platforms register here without touching the views or the data model.
"""

import base64
import hashlib
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
        # force-ssl is the scope Google's own YouTube OAuth samples use so the
        # *second* screen lists Brand Accounts / channels (first screen is always Gmail).
        "https://www.googleapis.com/auth/youtube.force-ssl",
        "https://www.googleapis.com/auth/youtube.upload",
    ]

    def build_auth_url(self, state: str) -> str:
        """Build the Google consent URL.

        Google's flow is two screens, both required:
        1. Pick the Gmail that *owns* the channels
        2. Pick the YouTube channel / Brand Account

        ``consent select_account`` forces both. YouTube scopes must be present or
        screen 2 never appears (Gmail only).
        """
        params = {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "redirect_uri": settings.YOUTUBE_OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(self.SCOPES),
            "access_type": "offline",
            "prompt": "consent select_account",
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
        """Fetch the YouTube channel that the user authorized (not the Google user)."""
        resp = requests.get(
            self.CHANNELS_URL,
            params={"part": "snippet,brandingSettings", "mine": "true", "maxResults": 50},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json().get("items", []) or []
        channel = _pick_youtube_channel(items)
        if not channel:
            return {}
        snippet = channel.get("snippet", {}) or {}
        branding = (channel.get("brandingSettings") or {}).get("channel") or {}
        title = (branding.get("title") or snippet.get("title") or "").strip()
        handle = _youtube_handle(snippet.get("customUrl") or branding.get("customUrl") or "")
        thumbnails = snippet.get("thumbnails", {}) or {}
        thumb = (
            thumbnails.get("medium")
            or thumbnails.get("high")
            or thumbnails.get("default")
            or {}
        )
        return {
            "externalId": channel.get("id", ""),
            "displayName": title,
            "handle": handle,
            "avatarUrl": thumb.get("url"),
        }


def _youtube_handle(custom_url: str) -> str:
    value = (custom_url or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        value = value.rstrip("/").rsplit("/", 1)[-1]
    if value.startswith("@"):
        return value
    if value.startswith(("channel/", "c/", "user/")):
        return f"youtube.com/{value}"
    return f"@{value}"


def _pick_youtube_channel(items: list) -> dict | None:
    """Prefer a channel with a custom @handle (typical Brand Account) over a bare default."""
    if not items:
        return None
    with_handle = [
        item
        for item in items
        if (item.get("snippet") or {}).get("customUrl")
        or ((item.get("brandingSettings") or {}).get("channel") or {}).get("customUrl")
    ]
    return with_handle[0] if with_handle else items[0]


class MetaProvider:
    """Facebook Login (Graph API) for Facebook Pages.

    Meta issues no refresh token — a short-lived token is exchanged for a long-lived
    (~60 day) token, which can later be re-extended with ``fb_exchange_token``.
    """

    GRAPH_VERSION = "v21.0"
    DIALOG_URL = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth"
    GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"

    def __init__(
        self,
        platform: str,
        redirect_setting: str,
        base_scopes: list[str],
        publish_scopes: list[str],
        publish_setting: str,
    ):
        self.platform = platform
        self._redirect_setting = redirect_setting
        self.base_scopes = base_scopes
        self.publish_scopes = publish_scopes
        self._publish_setting = publish_setting

    @property
    def redirect_uri(self) -> str:
        return getattr(settings, self._redirect_setting)

    @property
    def scopes(self) -> list[str]:
        """Base (connect) scopes, plus publish scopes only when enabled via settings.

        Requesting a scope the Meta app hasn't enabled makes Meta reject the entire
        consent screen, so publish scopes are gated behind a per-platform setting.
        """
        enabled = getattr(settings, self._publish_setting, False)
        return self.base_scopes + (self.publish_scopes if enabled else [])

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


def _instagram_short_lived(payload: dict) -> dict:
    """Normalize Instagram's short-lived token JSON (flat or ``{data: [...]}``)."""
    entry = payload
    data = payload.get("data")
    if isinstance(data, list) and data:
        entry = data[0]
    permissions = entry.get("permissions") or ""
    if isinstance(permissions, list):
        permissions = ",".join(permissions)
    return {
        "access_token": entry["access_token"],
        "user_id": str(entry.get("user_id") or ""),
        "permissions": permissions,
    }


class InstagramProvider:
    """Instagram Business Login — signs in with Instagram, not Facebook.

    Requires a Professional (Business or Creator) account. No Facebook Page needed.
    Uses Instagram App ID/Secret when set; otherwise falls back to META_APP_*.
    """

    platform = "instagram"
    AUTH_URL = "https://www.instagram.com/oauth/authorize"
    TOKEN_URL = "https://api.instagram.com/oauth/access_token"
    GRAPH = "https://graph.instagram.com"
    BASE_SCOPES = ["instagram_business_basic"]
    PUBLISH_SCOPES = ["instagram_business_content_publish"]

    def _client_id(self) -> str:
        return settings.INSTAGRAM_APP_ID or settings.META_APP_ID

    def _client_secret(self) -> str:
        return settings.INSTAGRAM_APP_SECRET or settings.META_APP_SECRET

    @property
    def redirect_uri(self) -> str:
        return settings.INSTAGRAM_OAUTH_REDIRECT_URI

    @property
    def scopes(self) -> list[str]:
        extra = self.PUBLISH_SCOPES if settings.INSTAGRAM_PUBLISH_ENABLED else []
        return self.BASE_SCOPES + extra

    def build_auth_url(self, state: str) -> str:
        params = {
            "client_id": self._client_id(),
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": ",".join(self.scopes),
            "state": state,
            "force_reauth": "true",
            "enable_fb_login": "0",
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict:
        """Exchange the auth code for a short-lived token, then upgrade to ~60 days."""
        short = requests.post(
            self.TOKEN_URL,
            data={
                "client_id": self._client_id(),
                "client_secret": self._client_secret(),
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
                "code": code,
            },
            timeout=REQUEST_TIMEOUT,
        )
        short.raise_for_status()
        parsed = _instagram_short_lived(short.json())
        short_token = parsed["access_token"]

        long = requests.get(
            f"{self.GRAPH}/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": self._client_secret(),
                "access_token": short_token,
            },
            timeout=REQUEST_TIMEOUT,
        )
        long.raise_for_status()
        data = long.json()
        token = data["access_token"]
        # ponytail: Instagram has no separate refresh token; reuse the long-lived token.
        return {
            "access_token": token,
            "refresh_token": token,
            "expires_in": data.get("expires_in"),
            "scope": parsed["permissions"],
        }

    def refresh_access_token(self, token: str) -> dict:
        """Re-extend a still-valid long-lived Instagram user token (~60 days)."""
        resp = requests.get(
            f"{self.GRAPH}/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": token},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        new_token = data["access_token"]
        return {
            "access_token": new_token,
            "refresh_token": new_token,
            "expires_in": data.get("expires_in"),
        }

    def fetch_profile(self, access_token: str) -> dict:
        resp = requests.get(
            f"{self.GRAPH}/me",
            params={
                "fields": "user_id,username,name,profile_picture_url",
                "access_token": access_token,
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        username = (data.get("username") or "").strip()
        if not username:
            raise ValueError("Instagram profile missing username")
        return {
            "externalId": str(data.get("user_id") or data.get("id") or ""),
            "displayName": (data.get("name") or username).strip(),
            "handle": username,
            "avatarUrl": data.get("profile_picture_url"),
        }


def _tiktok_oauth_body(resp) -> dict:
    data = resp.json()
    if data.get("error"):
        raise ValueError(data.get("error_description") or data["error"])
    return data


class TikTokProvider:
    """TikTok Login Kit (web). Redirect URI must be https — use ngrok for local."""

    platform = "tiktok"
    AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
    TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
    USER_URL = "https://open.tiktokapis.com/v2/user/info/"
    BASE_SCOPES = ["user.info.basic"]
    PUBLISH_SCOPES = ["video.upload", "video.publish"]

    @property
    def scopes(self) -> list[str]:
        extra = self.PUBLISH_SCOPES if settings.TIKTOK_PUBLISH_ENABLED else []
        return self.BASE_SCOPES + extra

    def build_auth_url(self, state: str) -> str:
        params = {
            "client_key": settings.TIKTOK_CLIENT_KEY,
            "redirect_uri": settings.TIKTOK_OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": ",".join(self.scopes),
            "state": state,
            "disable_auto_auth": "1",
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict:
        resp = requests.post(
            self.TOKEN_URL,
            data={
                "client_key": settings.TIKTOK_CLIENT_KEY,
                "client_secret": settings.TIKTOK_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.TIKTOK_OAUTH_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = _tiktok_oauth_body(resp)
        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token"),
            "expires_in": data.get("expires_in"),
            "scope": data.get("scope", ""),
        }

    def refresh_access_token(self, refresh_token: str) -> dict:
        resp = requests.post(
            self.TOKEN_URL,
            data={
                "client_key": settings.TIKTOK_CLIENT_KEY,
                "client_secret": settings.TIKTOK_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = _tiktok_oauth_body(resp)
        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token"),
            "expires_in": data.get("expires_in"),
            "scope": data.get("scope"),
        }

    def fetch_profile(self, access_token: str) -> dict:
        resp = requests.get(
            self.USER_URL,
            params={"fields": "open_id,display_name,avatar_url"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
        err = payload.get("error") or {}
        if err.get("code") and err.get("code") != "ok":
            raise ValueError(err.get("message") or err["code"])
        user = (payload.get("data") or {}).get("user") or {}
        display = (user.get("display_name") or "").strip()
        if not display and not user.get("open_id"):
            raise ValueError("TikTok profile missing open_id")
        return {
            "externalId": user.get("open_id", ""),
            "displayName": display,
            "handle": "",
            "avatarUrl": user.get("avatar_url"),
        }


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class SnapchatProvider:
    """Snapchat Login Kit (authorization code + PKCE). Identity only — no publish."""

    platform = "snapchat"
    requires_pkce = True
    AUTH_URL = "https://accounts.snapchat.com/accounts/oauth2/auth"
    TOKEN_URL = "https://accounts.snapchat.com/accounts/oauth2/token"
    ME_URL = "https://kit.snapchat.com/v1/me"
    SCOPES = [
        "https://auth.snapchat.com/oauth2/api/user.display_name",
        "https://auth.snapchat.com/oauth2/api/user.external_id",
        "https://auth.snapchat.com/oauth2/api/user.bitmoji.avatar",
    ]

    def _basic_auth(self) -> str:
        raw = f"{settings.SNAPCHAT_CLIENT_ID}:{settings.SNAPCHAT_CLIENT_SECRET}"
        return base64.b64encode(raw.encode()).decode()

    def build_auth_url(self, state: str, code_verifier: str = "") -> str:
        params = {
            "client_id": settings.SNAPCHAT_CLIENT_ID,
            "redirect_uri": settings.SNAPCHAT_OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(self.SCOPES),
            "state": state,
            "code_challenge": _pkce_challenge(code_verifier),
            "code_challenge_method": "S256",
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str, code_verifier: str = "") -> dict:
        resp = requests.post(
            self.TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.SNAPCHAT_OAUTH_REDIRECT_URI,
                "client_id": settings.SNAPCHAT_CLIENT_ID,
                "code_verifier": code_verifier,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {self._basic_auth()}",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            raise ValueError(data.get("error_description") or data["error"])
        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token"),
            "expires_in": data.get("expires_in"),
            "scope": data.get("scope", ""),
        }

    def refresh_access_token(self, refresh_token: str) -> dict:
        resp = requests.post(
            self.TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"Basic {self._basic_auth()}",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("error"):
            raise ValueError(data.get("error_description") or data["error"])
        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token"),
            "expires_in": data.get("expires_in"),
        }

    def fetch_profile(self, access_token: str) -> dict:
        resp = requests.post(
            self.ME_URL,
            json={"query": "{me{displayName bitmoji{avatar} externalId}}"},
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            raise ValueError(str(payload["errors"]))
        me = (payload.get("data") or {}).get("me") or {}
        external_id = me.get("externalId") or ""
        display = (me.get("displayName") or "").strip()
        if not external_id and not display:
            raise ValueError("Snapchat profile empty")
        bitmoji = me.get("bitmoji") or {}
        return {
            "externalId": external_id,
            "displayName": display,
            "handle": "",
            "avatarUrl": bitmoji.get("avatar"),
        }


# Scopes are split into "connect now" vs "publish later":
#   - Login/connect works today with only default scopes.
#   - Publishing scopes are "Invalid Scopes" until enabled on the Meta app AND
#     approved via App Review. Requesting an un-enabled scope makes Meta reject
#     the ENTIRE consent screen — so we only request them once they're enabled.
#
# Gated by FACEBOOK_PUBLISH_ENABLED / INSTAGRAM_PUBLISH_ENABLED (env, default False).
FACEBOOK_PUBLISH_SCOPES = [
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
]

# Registry of implemented providers. Unknown platform => 400; known platform
# (in SocialAccount.PLATFORM_CHOICES) but absent here => 501 "not available yet".
PROVIDERS = {
    "youtube": YouTubeProvider(),
    "facebook": MetaProvider(
        "facebook",
        "FACEBOOK_OAUTH_REDIRECT_URI",
        base_scopes=["public_profile"],
        publish_scopes=FACEBOOK_PUBLISH_SCOPES,
        publish_setting="FACEBOOK_PUBLISH_ENABLED",
    ),
    "instagram": InstagramProvider(),
    "tiktok": TikTokProvider(),
    "snapchat": SnapchatProvider(),
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
        refresh_token=tokens.get("refresh_token"),
        expires_in=tokens.get("expires_in"),
        scope=tokens.get("scope"),
    )
    account.save(
        update_fields=["access_token", "refresh_token", "token_expires_at", "scope", "updated_at"]
    )
    return account.get_access_token()
