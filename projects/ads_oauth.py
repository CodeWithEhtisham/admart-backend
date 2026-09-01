"""Ads Manager OAuth — separate from social Login Kit / organic connect."""

from urllib.parse import urlencode

import requests
from django.conf import settings

from projects.oauth import REQUEST_TIMEOUT

GRAPH_VERSION = "v21.0"


class MetaAdsProvider:
    """Meta Marketing API (Facebook + Instagram ads in one AdAccount)."""

    provider = "meta"
    requires_pkce = False
    # Do not request business_management — Meta rejects it with Invalid Scopes
    # until it is added on the app. ads_management + ads_read are enough to list
    # ad accounts and create a paused campaign.
    SCOPES = ["ads_management", "ads_read"]

    @property
    def app_id(self) -> str:
        return settings.META_ADS_APP_ID or settings.META_APP_ID

    @property
    def app_secret(self) -> str:
        return settings.META_ADS_APP_SECRET or settings.META_APP_SECRET

    def build_auth_url(self, state: str) -> str:
        params = {
            "client_id": self.app_id,
            "redirect_uri": settings.META_ADS_OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": ",".join(self.SCOPES),
            "state": state,
        }
        return f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict:
        short = requests.get(
            f"https://graph.facebook.com/{GRAPH_VERSION}/oauth/access_token",
            params={
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "redirect_uri": settings.META_ADS_OAUTH_REDIRECT_URI,
                "code": code,
            },
            timeout=REQUEST_TIMEOUT,
        )
        short.raise_for_status()
        short_token = short.json()["access_token"]
        long = requests.get(
            f"https://graph.facebook.com/{GRAPH_VERSION}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "fb_exchange_token": short_token,
            },
            timeout=REQUEST_TIMEOUT,
        )
        long.raise_for_status()
        return long.json()

    def fetch_profile(self, access_token: str) -> dict:
        resp = requests.get(
            f"https://graph.facebook.com/{GRAPH_VERSION}/me/adaccounts",
            params={"fields": "id,name,account_id", "access_token": access_token},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        rows = (resp.json() or {}).get("data") or []
        first = rows[0] if rows else {}
        return {
            "externalId": str(first.get("account_id") or first.get("id") or ""),
            "displayName": first.get("name") or "Meta Ads",
            "handle": str(first.get("account_id") or ""),
        }


class TikTokAdsProvider:
    provider = "tiktok"
    requires_pkce = False
    AUTH_URL = "https://business-api.tiktok.com/portal/auth"
    TOKEN_URL = "https://business-api.tiktok.com/open_api/v1.3/oauth2/access_token/"

    def build_auth_url(self, state: str) -> str:
        params = {
            "app_id": settings.TIKTOK_ADS_APP_ID or settings.TIKTOK_CLIENT_KEY,
            "redirect_uri": settings.TIKTOK_ADS_OAUTH_REDIRECT_URI,
            "state": state,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict:
        resp = requests.post(
            self.TOKEN_URL,
            json={
                "app_id": settings.TIKTOK_ADS_APP_ID or settings.TIKTOK_CLIENT_KEY,
                "secret": settings.TIKTOK_ADS_APP_SECRET or settings.TIKTOK_CLIENT_SECRET,
                "auth_code": code,
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json() or {}
        data = payload.get("data") or payload
        if payload.get("code") not in (None, 0, "0") and "access_token" not in data:
            raise ValueError(payload.get("message") or "TikTok ads token exchange failed")
        return {
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
            "expires_in": data.get("expires_in"),
            "advertiser_ids": data.get("advertiser_ids") or [],
        }

    def fetch_profile(self, access_token: str) -> dict:
        return {"externalId": "", "displayName": "TikTok Ads", "handle": ""}


class SnapAdsProvider:
    provider = "snap"
    requires_pkce = False
    AUTH_URL = "https://accounts.snapchat.com/login/oauth2/authorize"
    TOKEN_URL = "https://accounts.snapchat.com/login/oauth2/access_token"

    def build_auth_url(self, state: str) -> str:
        params = {
            "client_id": settings.SNAP_ADS_CLIENT_ID or settings.SNAPCHAT_CLIENT_ID,
            "redirect_uri": settings.SNAP_ADS_OAUTH_REDIRECT_URI,
            "response_type": "code",
            "scope": "snapchat-marketing-api",
            "state": state,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> dict:
        resp = requests.post(
            self.TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.SNAP_ADS_OAUTH_REDIRECT_URI,
                "client_id": settings.SNAP_ADS_CLIENT_ID or settings.SNAPCHAT_CLIENT_ID,
                "client_secret": settings.SNAP_ADS_CLIENT_SECRET or settings.SNAPCHAT_CLIENT_SECRET,
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
        return {"externalId": "", "displayName": "Snap Ads", "handle": ""}


ADS_PROVIDERS = {
    "meta": MetaAdsProvider(),
    "tiktok": TikTokAdsProvider(),
    "snap": SnapAdsProvider(),
}


def create_boost(account, *, kind: str, source_url: str, title: str, placements: list, budget: str) -> dict:
    """Create a campaign via the provider Marketing API. Tests mock this."""
    token = account.get_access_token()
    if account.provider == "meta":
        resp = requests.post(
            f"https://graph.facebook.com/{GRAPH_VERSION}/{account.external_id}/campaigns",
            data={
                "name": title or "Admart boost",
                "objective": "OUTCOME_AWARENESS",
                "status": "PAUSED",
                "special_ad_categories": "[]",
                "access_token": token,
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return {"externalId": str((resp.json() or {}).get("id", ""))}
    if account.provider == "tiktok":
        resp = requests.post(
            "https://business-api.tiktok.com/open_api/v1.3/campaign/create/",
            headers={"Access-Token": token, "Content-Type": "application/json"},
            json={
                "advertiser_id": account.external_id,
                "campaign_name": title or "Admart boost",
                "objective_type": "TRAFFIC",
                "budget": budget or "10",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = (resp.json() or {}).get("data") or {}
        return {"externalId": str(data.get("campaign_id", ""))}
    resp = requests.post(
        "https://adsapi.snapchat.com/v1/adaccounts/" + (account.external_id or "unknown") + "/campaigns",
        headers={"Authorization": f"Bearer {token}"},
        json={"campaigns": [{"name": title or "Admart boost"}]},
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    return {"externalId": ""}
