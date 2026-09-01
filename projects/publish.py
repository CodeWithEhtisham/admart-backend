"""Organic publish to connected social accounts."""

import requests
from django.conf import settings

from projects.oauth import REQUEST_TIMEOUT, ensure_fresh_access_token

UPLOAD_TIMEOUT = 120


class PublishUnavailable(Exception):
    """Platform cannot organic-post yet (App Review / Login Kit)."""


def publish_youtube(account, *, kind: str, source_url: str, title: str) -> dict:
    token = ensure_fresh_access_token(account)
    media = requests.get(source_url, timeout=UPLOAD_TIMEOUT)
    media.raise_for_status()
    init = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos",
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/*",
        },
        json={
            "snippet": {"title": title or "Admart video", "description": ""},
            "status": {"privacyStatus": "unlisted"},
        },
        timeout=REQUEST_TIMEOUT,
    )
    init.raise_for_status()
    upload_url = init.headers.get("Location")
    if not upload_url:
        raise RuntimeError("YouTube did not return an upload URL")
    put = requests.put(
        upload_url,
        data=media.content,
        headers={"Content-Type": "video/*"},
        timeout=UPLOAD_TIMEOUT,
    )
    put.raise_for_status()
    video_id = (put.json() or {}).get("id", "")
    return {"status": "succeeded", "externalId": video_id}


def publish_facebook(account, *, kind: str, source_url: str, title: str) -> dict:
    if not settings.FACEBOOK_PUBLISH_ENABLED:
        raise PublishUnavailable("Facebook publishing needs App Review. Set FACEBOOK_PUBLISH_ENABLED after approval.")
    token = ensure_fresh_access_token(account)
    path = "videos" if kind == "video" else "photos"
    resp = requests.post(
        f"https://graph.facebook.com/v21.0/me/{path}",
        data={"url": source_url, "description": title, "access_token": token},
        timeout=UPLOAD_TIMEOUT,
    )
    resp.raise_for_status()
    return {"status": "succeeded", "externalId": str((resp.json() or {}).get("id", ""))}


def publish_instagram(account, *, kind: str, source_url: str, title: str) -> dict:
    if not settings.INSTAGRAM_PUBLISH_ENABLED:
        raise PublishUnavailable("Instagram publishing needs App Review. Set INSTAGRAM_PUBLISH_ENABLED after approval.")
    token = ensure_fresh_access_token(account)
    ig_id = account.external_id
    media_type = "REELS" if kind == "video" else "IMAGE"
    body = {"caption": title, "access_token": token}
    if kind == "video":
        body.update({"media_type": media_type, "video_url": source_url})
    else:
        body["image_url"] = source_url
    container = requests.post(
        f"https://graph.facebook.com/v21.0/{ig_id}/media",
        data=body,
        timeout=UPLOAD_TIMEOUT,
    )
    container.raise_for_status()
    creation_id = container.json()["id"]
    publish = requests.post(
        f"https://graph.facebook.com/v21.0/{ig_id}/media_publish",
        data={"creation_id": creation_id, "access_token": token},
        timeout=UPLOAD_TIMEOUT,
    )
    publish.raise_for_status()
    return {"status": "succeeded", "externalId": str(publish.json().get("id", creation_id))}


def publish_tiktok(account, *, kind: str, source_url: str, title: str) -> dict:
    if not settings.TIKTOK_PUBLISH_ENABLED:
        raise PublishUnavailable("TikTok publishing needs Content Posting API approval. Set TIKTOK_PUBLISH_ENABLED after review.")
    token = ensure_fresh_access_token(account)
    resp = requests.post(
        "https://open.tiktokapis.com/v2/post/publish/video/init/",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"},
        json={
            "post_info": {"title": title or "Admart video", "privacy_level": "SELF_ONLY"},
            "source_info": {"source": "PULL_FROM_URL", "video_url": source_url},
        },
        timeout=UPLOAD_TIMEOUT,
    )
    resp.raise_for_status()
    data = (resp.json() or {}).get("data") or {}
    return {"status": "succeeded", "externalId": str(data.get("publish_id", ""))}


def publish_snapchat(*_args, **_kwargs) -> dict:
    raise PublishUnavailable("Snapchat does not support organic posts. Use as ad instead.")


PUBLISHERS = {
    "youtube": publish_youtube,
    "facebook": publish_facebook,
    "instagram": publish_instagram,
    "tiktok": publish_tiktok,
    "snapchat": publish_snapchat,
}
