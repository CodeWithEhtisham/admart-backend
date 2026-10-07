"""Organic publish to connected social accounts."""

import json
import logging
import time
from urllib.parse import urlparse

import requests
from django.conf import settings

from content.url_resolve import fetch_media
from projects.oauth import REQUEST_TIMEOUT, ensure_fresh_access_token

UPLOAD_TIMEOUT = 600


class PublishUnavailable(Exception):
    """Platform cannot organic-post yet (App Review / Login Kit)."""


logger = logging.getLogger(__name__)

PLATFORM_LABELS = {
    "youtube": "YouTube",
    "facebook": "Facebook",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "snapchat": "Snapchat",
    "meta": "Meta Ads",
    "snap": "Snap Ads",
    "google": "Google Ads",
}


def user_error(exc: Exception, platform: str) -> str:
    """A message safe to show users. Our own errors (and platform API messages) pass through;
    network failures and unexpected exceptions are logged and replaced with plain text."""
    name = PLATFORM_LABELS.get(platform, platform)
    if isinstance(exc, requests.RequestException):
        logger.warning("%s request failed", name, exc_info=exc)
        return f"Couldn't reach {name}. Try again in a minute, or reconnect it on Social Accounts."
    if isinstance(exc, (PublishUnavailable, RuntimeError, ValueError)) and not isinstance(exc, json.JSONDecodeError):
        return str(exc)
    logger.exception("%s request failed", name, exc_info=exc)
    return f"Something went wrong with {name}. Try again, or reconnect it on Social Accounts."


def _fetchable_url(source_url: str) -> str:
    if source_url.startswith("http://") or source_url.startswith("https://"):
        return source_url
    base = (getattr(settings, "MEDIA_BASE_URL", None) or "").rstrip("/")
    if not base:
        raise RuntimeError("sourceUrl is a local path. Set MEDIA_BASE_URL so the file can be fetched.")
    path = source_url if source_url.startswith("/") else f"/{source_url}"
    return f"{base}{path}"


GRAPH = "https://graph.facebook.com/v21.0"
IG_GRAPH = "https://graph.instagram.com/v21.0"


def _google_error(resp) -> str:
    try:
        body = resp.json() or {}
    except ValueError:
        return resp.text[:400]
    err = body.get("error") or body
    if isinstance(err, dict):
        return err.get("message") or str(err)
    return str(err) or resp.text[:400]


def _facebook_accounts(account) -> list[dict]:
    token = ensure_fresh_access_token(account)
    resp = requests.get(
        f"{GRAPH}/me/accounts",
        params={"fields": "id,name,access_token", "access_token": token},
        timeout=REQUEST_TIMEOUT,
    )
    if not resp.ok:
        raise RuntimeError(_google_error(resp))
    return list((resp.json() or {}).get("data") or [])


def list_facebook_pages(account) -> list[dict]:
    if not settings.FACEBOOK_PUBLISH_ENABLED:
        raise PublishUnavailable(
            "Facebook publishing needs App Review. Set FACEBOOK_PUBLISH_ENABLED after approval."
        )
    rows = []
    for page in _facebook_accounts(account):
        page_id = page.get("id") or ""
        if page_id:
            rows.append({"id": page_id, "name": (page.get("name") or "").strip()})
    return rows


def publish_youtube(
    account,
    *,
    kind: str,
    source_url: str,
    title: str,
    privacy: str = "public",
    description: str = "",
    tags: list | None = None,
    thumbnail_url: str = "",
    category_id: str = "22",
    language: str = "",
    license_type: str = "youtube",
    embeddable: bool = True,
    public_stats: bool = True,
    made_for_kids: bool = False,
    synthetic_media: bool = True,
    notify_subscribers: bool = True,
    publish_at: str = "",
    recording_date: str = "",
    playlist_id: str = "",
    paid_promotion: bool = False,
) -> dict:
    token = ensure_fresh_access_token(account)
    media_content, _ = fetch_media(_fetchable_url(source_url), timeout=UPLOAD_TIMEOUT)
    snippet = {
        "title": (title or "Admart video")[:100],
        "description": (description or "")[:5000],
        "categoryId": category_id or "22",
    }
    if tags:
        snippet["tags"] = [str(t)[:100] for t in tags if str(t).strip()][:30]
    if language:
        snippet["defaultLanguage"] = language
        snippet["defaultAudioLanguage"] = language
    privacy = privacy if privacy in ("public", "unlisted", "private") else "public"
    status_body = {
        "privacyStatus": "private" if publish_at else privacy,
        "embeddable": bool(embeddable),
        "license": license_type if license_type in ("youtube", "creativeCommon") else "youtube",
        "publicStatsViewable": bool(public_stats),
        "selfDeclaredMadeForKids": bool(made_for_kids),
        "containsSyntheticMedia": bool(synthetic_media),
    }
    if publish_at:
        status_body["publishAt"] = publish_at
    body = {"snippet": snippet, "status": status_body}
    parts = ["snippet", "status"]
    if recording_date:
        body["recordingDetails"] = {"recordingDate": recording_date}
        parts.append("recordingDetails")
    if paid_promotion:
        body["paidProductPlacementDetails"] = {"hasPaidProductPlacement": True}
        parts.append("paidProductPlacementDetails")
    init = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos",
        params={
            "uploadType": "resumable",
            "part": ",".join(parts),
            "notifySubscribers": "true" if notify_subscribers else "false",
        },
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/*",
        },
        json=body,
        timeout=REQUEST_TIMEOUT,
    )
    if not init.ok:
        raise RuntimeError(_google_error(init))
    upload_url = init.headers.get("Location")
    if not upload_url:
        raise RuntimeError("YouTube did not return an upload URL")
    put = requests.put(
        upload_url,
        data=media_content,
        headers={"Content-Type": "video/*"},
        timeout=UPLOAD_TIMEOUT,
    )
    if not put.ok:
        raise RuntimeError(_google_error(put))
    video_id = (put.json() or {}).get("id", "")
    result = {
        "status": "succeeded",
        "externalId": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}" if video_id else "",
    }
    if video_id and thumbnail_url:
        try:
            _set_youtube_thumbnail(token, video_id, thumbnail_url)
            result["thumbnailSet"] = True
        except Exception as exc:  # noqa: BLE001
            result["thumbnailError"] = user_error(exc, "youtube")
    if video_id and playlist_id:
        try:
            _add_to_youtube_playlist(token, playlist_id, video_id)
            result["playlistId"] = playlist_id
        except Exception as exc:  # noqa: BLE001
            result["playlistError"] = user_error(exc, "youtube")
    return result


def _set_youtube_thumbnail(token: str, video_id: str, thumbnail_url: str) -> None:
    img_content, img_type = fetch_media(_fetchable_url(thumbnail_url), timeout=UPLOAD_TIMEOUT)
    content_type = (img_type or "image/jpeg").split(";")[0].strip()
    if content_type not in ("image/jpeg", "image/png", "image/webp"):
        content_type = "image/jpeg"
    resp = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/thumbnails/set",
        params={"videoId": video_id},
        headers={"Authorization": f"Bearer {token}", "Content-Type": content_type},
        data=img_content,
        timeout=UPLOAD_TIMEOUT,
    )
    if not resp.ok:
        raise RuntimeError(_google_error(resp))


def _add_to_youtube_playlist(token: str, playlist_id: str, video_id: str) -> None:
    resp = requests.post(
        "https://www.googleapis.com/youtube/v3/playlistItems",
        params={"part": "snippet"},
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        },
        timeout=REQUEST_TIMEOUT,
    )
    if not resp.ok:
        raise RuntimeError(_google_error(resp))


def list_youtube_playlists(account) -> list[dict]:
    token = ensure_fresh_access_token(account)
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/playlists",
        params={"part": "snippet", "mine": "true", "maxResults": 50},
        headers={"Authorization": f"Bearer {token}"},
        timeout=REQUEST_TIMEOUT,
    )
    if not resp.ok:
        raise RuntimeError(_google_error(resp))
    rows = []
    for item in (resp.json() or {}).get("items") or []:
        rows.append(
            {
                "id": item.get("id") or "",
                "title": ((item.get("snippet") or {}).get("title") or "").strip(),
            }
        )
    return rows


def _public_media_url(source_url: str) -> str:
    url = _fetchable_url(source_url)
    host = (urlparse(url).hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "0.0.0.0") or host.endswith(".local"):
        raise RuntimeError(
            "Instagram must download the file from a public URL. Set MEDIA_BASE_URL to https (ngrok)."
        )
    return url


def ig_graph(account) -> str:
    """Graph base for an Instagram account.

    "Connect Meta" accounts (Facebook Login, linked to a Page) are granted the Facebook
    Login permission ``instagram_basic`` and use graph.facebook.com. Anything else is an
    older Instagram-login connection (``instagram_business_*`` or no scope stored) and
    keeps using graph.instagram.com.
    """
    granted = set((account.scope or "").replace(" ", ",").split(","))
    return GRAPH if "instagram_basic" in granted else IG_GRAPH


def _ig_user_id(account, token: str) -> str:
    ig_id = (account.external_id or "").strip()
    if ig_id:
        return ig_id
    if ig_graph(account) == GRAPH:
        raise RuntimeError("Instagram account id missing. Reconnect Meta.")
    resp = requests.get(
        f"{IG_GRAPH}/me",
        params={"fields": "user_id", "access_token": token},
        timeout=REQUEST_TIMEOUT,
    )
    if not resp.ok:
        raise RuntimeError(_google_error(resp))
    ig_id = str((resp.json() or {}).get("user_id") or (resp.json() or {}).get("id") or "")
    if not ig_id:
        raise RuntimeError("Instagram user id missing. Reconnect Meta.")
    return ig_id


def _wait_ig_container(creation_id: str, token: str, base: str = IG_GRAPH) -> None:
    deadline = time.time() + min(UPLOAD_TIMEOUT, 180)
    while time.time() < deadline:
        resp = requests.get(
            f"{base}/{creation_id}",
            params={"fields": "status_code,status", "access_token": token},
            timeout=REQUEST_TIMEOUT,
        )
        if not resp.ok:
            raise RuntimeError(_google_error(resp))
        body = resp.json() or {}
        code = (body.get("status_code") or "").upper()
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(body.get("status") or f"Instagram container {code}")
        time.sleep(2)
    raise RuntimeError("Instagram is still processing the video. Try again in a minute.")


def publish_facebook(
    account,
    *,
    kind: str,
    source_url: str,
    title: str,
    caption: str = "",
    page_id: str = "",
    scheduled_at=None,
) -> dict:
    if not settings.FACEBOOK_PUBLISH_ENABLED:
        raise PublishUnavailable(
            "Facebook publishing needs App Review. Set FACEBOOK_PUBLISH_ENABLED after approval."
        )
    pages = _facebook_accounts(account)
    if not pages:
        raise RuntimeError("No Facebook Page found. Create a Page, then reconnect Meta.")
    page = next((p for p in pages if p.get("id") == page_id), None) if page_id else pages[0]
    if page_id and page is None:
        raise RuntimeError("That Facebook Page is not in this account.")
    page_token = (page or {}).get("access_token") or ""
    if not page_token:
        raise RuntimeError("Facebook Page token missing. Reconnect Meta.")
    media_content, media_type = fetch_media(_fetchable_url(source_url), timeout=UPLOAD_TIMEOUT)
    path = "videos" if kind == "video" else "photos"
    filename = "video.mp4" if kind == "video" else "photo.jpg"
    ctype = (media_type or "").split(";")[0].strip()
    if not ctype or ctype == "application/octet-stream":
        ctype = "video/mp4" if kind == "video" else "image/jpeg"
    text = (caption or title or "").strip()
    data = {"access_token": page_token, "published": "true"}
    if scheduled_at:
        data["published"] = "false"
        data["scheduled_publish_time"] = str(int(scheduled_at.timestamp()))
    if kind == "video":
        data["description"] = text
        if title:
            data["title"] = title[:255]
    else:
        data["caption"] = text
    resp = requests.post(
        f"{GRAPH}/{page['id']}/{path}",
        data=data,
        files={"source": (filename, media_content, ctype)},
        timeout=UPLOAD_TIMEOUT,
    )
    if not resp.ok:
        raise RuntimeError(_google_error(resp))
    return {
        "status": "succeeded",
        "externalId": str((resp.json() or {}).get("id", "")),
        "pageId": page["id"],
    }


def publish_instagram(account, *, kind: str, source_url: str, title: str, caption: str = "") -> dict:
    if not settings.INSTAGRAM_PUBLISH_ENABLED:
        raise PublishUnavailable(
            "Instagram publishing needs App Review. Set INSTAGRAM_PUBLISH_ENABLED after approval."
        )
    token = ensure_fresh_access_token(account)
    base = ig_graph(account)
    ig_id = _ig_user_id(account, token)
    media_url = _public_media_url(source_url)
    text = (caption or title or "").strip()[:2200]
    body = {"caption": text, "access_token": token}
    if kind == "video":
        body.update({"media_type": "REELS", "video_url": media_url, "share_to_feed": "true"})
    else:
        body["image_url"] = media_url
    container = requests.post(f"{base}/{ig_id}/media", data=body, timeout=UPLOAD_TIMEOUT)
    if not container.ok:
        raise RuntimeError(_google_error(container))
    creation_id = str((container.json() or {}).get("id") or "")
    if not creation_id:
        raise RuntimeError("Instagram did not return a media container.")
    if kind == "video":
        _wait_ig_container(creation_id, token, base)
    published = requests.post(
        f"{base}/{ig_id}/media_publish",
        data={"creation_id": creation_id, "access_token": token},
        timeout=UPLOAD_TIMEOUT,
    )
    if not published.ok:
        raise RuntimeError(_google_error(published))
    return {"status": "succeeded", "externalId": str((published.json() or {}).get("id", creation_id))}


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
