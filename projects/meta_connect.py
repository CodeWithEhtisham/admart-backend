"""Single "Connect Meta": one Facebook Login -> Facebook, Instagram and Meta Ads.

The same long-lived user token is stored on the project's facebook SocialAccount,
on the instagram SocialAccount (the Instagram Business account linked to the Page,
reached via graph.facebook.com) and on the meta AdAccount. Disconnecting Meta
turns all three off and erases the stored tokens.
"""

from __future__ import annotations

from projects.models import AdAccount, SocialAccount

INSTAGRAM_SKIPPED_NO_LINK = "no_linked_instagram"
INSTAGRAM_SKIPPED_PLAN_LIMIT = "plan_limit"


def connect_meta(user, project, tokens: dict, assets: dict, scope: str) -> dict:
    """Store the connections found in ``assets`` (from MetaConnectProvider.fetch_assets).

    Facebook is required (the caller checks there is a Page). Instagram is added when a
    Page has a linked Instagram Business account and the plan has a free slot; ads when
    the user has an ad account.
    """
    from projects.views import social_limit_response

    token = tokens["access_token"]
    expires_in = tokens.get("expires_in")
    profile = assets.get("profile") or {}
    pages = assets.get("pages") or []

    def store(account, **fields):
        account.connected = True
        for name, value in fields.items():
            setattr(account, name, value)
        # Meta has no refresh token: the long-lived token lasts ~60 days, then reconnect.
        account.store_tokens(access_token=token, refresh_token=None, expires_in=expires_in, scope=scope)
        account.refresh_token = ""
        account.save()
        return account

    facebook, _ = SocialAccount.objects.get_or_create(project=project, platform="facebook")
    store(
        facebook,
        external_id=str(profile.get("id") or ""),
        display_name=", ".join(p["name"] for p in pages if p.get("name")) or profile.get("name", ""),
        handle=profile.get("name", ""),
    )
    result = {
        "facebook": {"pages": [{"id": p["id"], "name": p["name"]} for p in pages]},
        "instagram": None,
        "instagramSkipped": None,
        "ads": None,
    }

    linked = next((p for p in pages if p.get("instagram")), None)
    if linked is None:
        result["instagramSkipped"] = INSTAGRAM_SKIPPED_NO_LINK
    elif social_limit_response(user, project, "instagram") is not None:
        result["instagramSkipped"] = INSTAGRAM_SKIPPED_PLAN_LIMIT
    else:
        ig = linked["instagram"]
        instagram, _ = SocialAccount.objects.get_or_create(project=project, platform="instagram")
        store(
            instagram,
            external_id=str(ig.get("id") or ""),
            handle=ig.get("username") or "",
            display_name=ig.get("name") or ig.get("username") or "",
            avatar_url=ig.get("profile_picture_url"),
        )
        result["instagram"] = {"id": instagram.external_id, "username": instagram.handle, "page": linked["name"]}

    ad_accounts = assets.get("adAccounts") or []
    if ad_accounts:
        first = ad_accounts[0]
        ads, _ = AdAccount.objects.get_or_create(project=project, provider="meta")
        store(
            ads,
            external_id=str(first.get("account_id") or first.get("id") or ""),
            display_name=first.get("name") or "Meta Ads",
            handle=str(first.get("account_id") or ""),
        )
        result["ads"] = {"id": ads.external_id, "name": ads.display_name}
    return result


def disconnect_meta(project) -> int:
    """Turn off Facebook, Instagram and Meta Ads for the project and erase their tokens."""
    cleared = {"connected": False, "access_token": "", "refresh_token": "", "token_expires_at": None}
    n = SocialAccount.objects.filter(project=project, platform__in=("facebook", "instagram")).update(**cleared)
    n += AdAccount.objects.filter(project=project, provider="meta").update(**cleared)
    return n
