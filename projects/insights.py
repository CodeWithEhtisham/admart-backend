"""Live views / likes / comments for published posts. Missing stats stay null."""

import requests

from projects.oauth import REQUEST_TIMEOUT, ensure_fresh_access_token
from projects.publish import GRAPH, IG_GRAPH, _facebook_accounts


def _as_int(value):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _token(account) -> str:
    try:
        return ensure_fresh_access_token(account) or ""
    except Exception:
        return ""


def _rate(views, likes, comments, shares):
    if not views:
        return None
    engaged = (likes or 0) + (comments or 0) + (shares or 0)
    return round(100.0 * engaged / views, 1)


def youtube_video_stats(account, video_ids: list[str]) -> dict:
    token = _token(account)
    ids = [vid for vid in dict.fromkeys(video_ids) if vid]
    if not token or not ids:
        return {}
    out = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i : i + 50]
        try:
            resp = requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={"part": "statistics", "id": ",".join(chunk)},
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT,
            )
            if not resp.ok:
                continue
            for item in (resp.json() or {}).get("items") or []:
                vid = item.get("id") or ""
                stats = item.get("statistics") or {}
                if vid:
                    out[vid] = {
                        "views": _as_int(stats.get("viewCount")),
                        "likes": _as_int(stats.get("likeCount")),
                        "comments": _as_int(stats.get("commentCount")),
                        "shares": None,
                    }
        except Exception:
            continue
    return out


def facebook_post_stats(account, post_id: str, page_id: str = "") -> dict:
    if not post_id:
        return {}
    try:
        pages = _facebook_accounts(account)
    except Exception:
        return {}
    page = next((p for p in pages if p.get("id") == page_id), None) if page_id else None
    token = (page or (pages[0] if pages else {})).get("access_token") or ""
    if not token:
        return {}
    likes = comments = shares = views = None
    try:
        resp = requests.get(
            f"{GRAPH}/{post_id}",
            params={
                "fields": "shares,comments.summary(true),reactions.summary(true)",
                "access_token": token,
            },
            timeout=REQUEST_TIMEOUT,
        )
        if resp.ok:
            body = resp.json() or {}
            shares = _as_int((body.get("shares") or {}).get("count"))
            comments = _as_int(((body.get("comments") or {}).get("summary") or {}).get("total_count"))
            likes = _as_int(((body.get("reactions") or {}).get("summary") or {}).get("total_count"))
    except Exception:
        pass
    try:
        resp = requests.get(
            f"{GRAPH}/{post_id}/insights",
            params={"metric": "post_video_views,post_impressions", "access_token": token},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.ok:
            for row in (resp.json() or {}).get("data") or []:
                values = row.get("values") or []
                value = _as_int(values[0].get("value") if values else None)
                name = row.get("name")
                if name == "post_video_views" and value is not None:
                    views = value
                elif name == "post_impressions" and views is None:
                    views = value
    except Exception:
        pass
    if likes is None and comments is None and shares is None and views is None:
        return {}
    return {"views": views, "likes": likes, "comments": comments, "shares": shares}


def instagram_media_stats(account, media_id: str) -> dict:
    token = _token(account)
    if not token or not media_id:
        return {}
    likes = comments = views = None
    try:
        resp = requests.get(
            f"{IG_GRAPH}/{media_id}",
            params={"fields": "like_count,comments_count", "access_token": token},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.ok:
            body = resp.json() or {}
            likes = _as_int(body.get("like_count"))
            comments = _as_int(body.get("comments_count"))
    except Exception:
        pass
    try:
        resp = requests.get(
            f"{IG_GRAPH}/{media_id}/insights",
            params={"metric": "views,plays", "access_token": token},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.ok:
            for row in (resp.json() or {}).get("data") or []:
                values = row.get("values") or []
                value = _as_int(values[0].get("value") if values else None)
                if value is not None:
                    views = value
                    if row.get("name") == "views":
                        break
    except Exception:
        pass
    if likes is None and comments is None and views is None:
        return {}
    return {"views": views, "likes": likes, "comments": comments, "shares": None}


def attach_metrics(project, rows: list[dict]) -> list[dict]:
    from projects.models import SocialAccount

    accounts = {
        account.platform: account
        for account in SocialAccount.objects.filter(project=project, connected=True)
    }
    pending = [row for row in rows if row.get("status") == "succeeded" and row.get("externalId")][:40]
    youtube_ids = [row["externalId"] for row in pending if row["platform"] == "youtube"]
    found = {}
    if youtube_ids and accounts.get("youtube"):
        for vid, stats in youtube_video_stats(accounts["youtube"], youtube_ids).items():
            found[("youtube", vid)] = stats
    for row in pending:
        key = (row["platform"], row["externalId"])
        if key in found:
            continue
        account = accounts.get(row["platform"])
        if not account:
            continue
        if row["platform"] == "facebook":
            found[key] = facebook_post_stats(account, row["externalId"], row.get("pageId") or "")
        elif row["platform"] == "instagram":
            found[key] = instagram_media_stats(account, row["externalId"])
    for row in rows:
        stats = found.get((row["platform"], row.get("externalId"))) or {}
        views = stats.get("views")
        likes = stats.get("likes")
        comments = stats.get("comments")
        shares = stats.get("shares")
        row["views"] = views
        row["likes"] = likes
        row["comments"] = comments
        row["shares"] = shares
        row["engagementRate"] = _rate(views, likes, comments, shares)
    return rows
