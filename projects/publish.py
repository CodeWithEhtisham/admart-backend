"""Organic publish to connected social accounts."""

import requests
from django.conf import settings

from projects.oauth import REQUEST_TIMEOUT, ensure_fresh_access_token

UPLOAD_TIMEOUT = 600


class PublishUnavailable(Exception):
    """Platform cannot organic-post yet (App Review / Login Kit)."""


def _fetchable_url(source_url: str) -> str:
    if source_url.startswith("http://") or source_url.startswith("https://"):
        return source_url
    base = (getattr(settings, "MEDIA_BASE_URL", None) or "").rstrip("/")
    if not base:
        raise RuntimeError("sourceUrl is a local path. Set MEDIA_BASE_URL so the file can be fetched.")
    path = source_url if source_url.startswith("/") else f"/{source_url}"
    return f"{base}{path}"


def _google_error(resp) -> str:
    try:
        body = resp.json() or {}
    except ValueError:
        return resp.text[:400]
    err = body.get("error") or body
    if isinstance(err, dict):
        return err.get("message") or str(err)
    return str(err) or resp.text[:400]


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
    media = requests.get(_fetchable_url(source_url), timeout=UPLOAD_TIMEOUT)
    media.raise_for_status()
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
        data=media.content,
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
            result["thumbnailError"] = str(exc)
    if video_id and playlist_id:
        try:
            _add_to_youtube_playlist(token, playlist_id, video_id)
            result["playlistId"] = playlist_id
        except Exception as exc:  # noqa: BLE001
            result["playlistError"] = str(exc)
    return result


def _set_youtube_thumbnail(token: str, video_id: str, thumbnail_url: str) -> None:
    img = requests.get(_fetchable_url(thumbnail_url), timeout=UPLOAD_TIMEOUT)
    img.raise_for_status()
    content_type = (img.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
    if content_type not in ("image/jpeg", "image/png", "image/webp"):
        content_type = "image/jpeg"
    resp = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/thumbnails/set",
        params={"videoId": video_id},
        headers={"Authorization": f"Bearer {token}", "Content-Type": content_type},
        data=img.content,
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
