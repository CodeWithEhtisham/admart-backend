"""Cross-poster agent: one Library video → a post written for each connected platform → you approve → it posts.

fetch → listen → write_post → review_post → wait → post. Plan: docs/plans/2026-10-14-cross-poster-agent.md
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from agents import hooks, providers, render
from agents import steps as base
from agents.video_edit import asset_file, probe, step_transcribe
from content.models import LibraryAsset
from content.storage_utils import absolute_media_url
from content.url_resolve import fetch_media
from projects.models import PublishJob, SocialAccount
from projects.publish import PLATFORM_LABELS, PUBLISHERS, user_error

PLATFORMS = ("youtube", "instagram", "facebook")
LISTEN_SECONDS = 180  # enough of the video to know what it is about
SHORT_SECONDS = 180

POST_PROMPT = f"""You write social posts for one video, from its transcript. Return JSON only, with a key for
each platform you are asked for:
{{"youtube": {{"title": string, "description": string, "tags": [string], "thumbnail_text": string}},
  "instagram": {{"caption": string}},
  "facebook": {{"caption": string}}}}
- youtube.title: {base.TITLE_RULES}.
- youtube.description: 2-4 short sentences that make people want to watch, then 3 hashtags.
- youtube.tags: up to 12 short search phrases without #. thumbnail_text: 2-4 punchy words, not the title's.
- instagram.caption: a strong first line (it shows before "more"), 1-3 short lines, then 5-10 hashtags.
- facebook.caption: 1-3 friendly sentences that start a conversation, at most 2 hashtags.
Never invent facts, numbers or claims that are not in the transcript. Write in the brand tone if given."""


def connected(project_id) -> list[str]:
    """Platforms this agent can post to that the project has connected, in a fixed order."""
    names = set(
        SocialAccount.objects.filter(project_id=project_id, platform__in=PLATFORMS, connected=True)
        .values_list("platform", flat=True)
    )
    return [p for p in PLATFORMS if p in names]


def _text(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def clean_posts(raw: dict, platforms: list[str], fallback: str, short: bool) -> dict:
    """The AI's posts, trimmed to each platform's limits."""
    posts = {}
    if "youtube" in platforms:
        yt = raw.get("youtube") if isinstance(raw.get("youtube"), dict) else {}
        tags = yt.get("tags") or []
        if isinstance(tags, str):
            tags = tags.split(",")
        description = _text(yt.get("description"), 4900)
        if short and "#shorts" not in description.lower():
            description = f"{description}\n\n#Shorts".strip()
        posts["youtube"] = {
            "title": _text(yt.get("title"), 100) or fallback[:100],
            "description": description,
            "tags": [str(t).strip().lstrip("#")[:60] for t in tags if str(t).strip()][:12],
            "thumbnail_text": " ".join(str(yt.get("thumbnail_text") or "").split()[:4])[:40],
            "privacy": "public",
        }
    for platform, limit in (("instagram", 2200), ("facebook", 5000)):
        if platform in platforms:
            row = raw.get(platform) if isinstance(raw.get(platform), dict) else {}
            posts[platform] = {"caption": _text(row.get("caption"), limit) or fallback}
    return posts


def _asset(run) -> LibraryAsset:
    asset = LibraryAsset.objects.filter(
        id=run.input.get("assetId"), project_id=run.project_id, media_type="video", deleted_at__isnull=True
    ).first()
    if asset is None:
        raise RuntimeError("The video is no longer in your library.")
    return asset


def _video_path(run) -> Path:
    """The video on our disk (downloaded into the run folder if it is stored elsewhere)."""
    asset = _asset(run)
    local = asset_file(asset)
    if local:
        return local
    folder, _ = base.media_dir(run)
    target = folder / "source.mp4"
    if not target.exists():
        target.write_bytes(fetch_media(asset.source_url, timeout=300)[0])
    return target


# ── steps ─────────────────────────────────────────────────────────────────


def step_fetch(run) -> None:
    if run.output.get("source_info"):
        return
    asset = _asset(run)
    path = _video_path(run)
    info = probe(path)
    folder, rel = base.media_dir(run)
    out = {
        "source_info": info,
        "source_title": asset.title,
        "asset_url": asset.source_url,
        "short": info["height"] > info["width"] and info["duration"] <= SHORT_SECONDS + 1,
    }
    if info["has_audio"]:
        render._run(["ffmpeg", "-y", "-i", str(path), "-t", str(LISTEN_SECONDS), "-vn", "-ac", "1", "-ar", "16000",
                     "-b:a", "64k", str(folder / "audio.mp3")])
        out["audio"] = f"{rel}/audio.mp3"
    run.output.update(out)
    base._save(run)


def step_listen(run) -> None:
    if "words" in run.output:
        return
    if not run.output.get("audio"):
        run.output["words"] = []
        base._save(run)
        return
    step_transcribe(run)


def step_write_post(run) -> None:
    if run.output.get("posts"):
        return
    platforms = connected(run.project_id)
    if not platforms:
        raise RuntimeError("Connect YouTube, Instagram or Facebook on Social Accounts first.")
    out = run.output
    asset = _asset(run)
    fallback = out.get("source_title") or "New video"
    transcript = " ".join(w["word"] for w in out.get("words") or [])
    if settings.AGENTS_DRY_RUN:
        raw = {p: {"title": fallback, "description": fallback, "caption": fallback, "tags": [],
                   "thumbnail_text": ""} for p in platforms}
    else:
        names = ", ".join(PLATFORM_LABELS[p] for p in platforms)
        kind = "a vertical Short / Reel" if out["short"] else "a video"
        raw = providers.text(POST_PROMPT, f"{base._brand_lines(run)}Write posts for: {names}.\n"
                             f"The video is {kind} called '{fallback}'.\n"
                             f"Transcript:\n{transcript[:12000] or '(no speech)'}", model=base._model(run, "text"))
    posts = clean_posts(raw, platforms, fallback, out["short"])
    out.update({"platforms": platforms, "posts": posts, "title": posts.get("youtube", {}).get("title") or fallback})
    if "youtube" in posts:
        yt = posts["youtube"]
        out["title_check"] = hooks.lint_title(yt["title"], yt["thumbnail_text"])
        if asset.capability == "agent" and asset.thumbnail_url:
            out["thumbnail_url"] = asset.thumbnail_url  # agent-made: already has a designed thumbnail
        else:
            folder, rel = base.media_dir(run)
            workdir = folder / "work"
            workdir.mkdir(parents=True, exist_ok=True)
            try:
                render.thumbnail(_video_path(run), yt["thumbnail_text"] or yt["title"], base.highlight(run),
                                 folder / "thumb.jpg", workdir)
            finally:
                shutil.rmtree(workdir, ignore_errors=True)
            out["thumbnail"] = f"{rel}/thumb.jpg"
    base._save(run)


def step_review_post(run) -> None:
    if not run.output.get("post_ok"):
        raise base.NeedsReview("post")


def step_wait(run) -> None:
    at = run.output.get("post_at")
    if at and datetime.fromisoformat(at) > timezone.now():
        raise base.WaitUntil(datetime.fromisoformat(at))


def _publish_kwargs(platform: str, post: dict, asset: LibraryAsset, thumbnail: str) -> dict:
    if platform == "youtube":
        return {"title": post["title"], "description": post["description"], "tags": post["tags"],
                "privacy": post.get("privacy", "public"), "thumbnail_url": thumbnail,
                "synthetic_media": asset.capability != "upload"}
    return {"title": "", "caption": post["caption"]}


def step_post(run) -> None:
    out = run.output
    asset = _asset(run)
    chosen = out.get("chosen") or out["platforms"]
    posted = out.setdefault("posted", {})
    thumbnail = out.get("thumbnail_url") or (absolute_media_url(out["thumbnail"]) if out.get("thumbnail") else "")
    job = PublishJob.objects.filter(id=out.get("publish_job")).first()
    if job is None:
        job = PublishJob.objects.create(
            project_id=run.project_id, user_id=run.user_id, library_asset=asset, kind="video",
            source_url=asset.source_url, title=out.get("title", "")[:255], platforms=chosen,
            payload={"agentRun": str(run.id)}, status="running",
        )
        out["publish_job"] = str(job.id)
        base._save(run)
    accounts = {a.platform: a for a in SocialAccount.objects.filter(project_id=run.project_id, connected=True,
                                                                     platform__in=chosen)}
    for platform in chosen:
        row = posted.get(platform) or {}
        if row.get("status") in ("succeeded", "unknown"):
            continue
        if row.get("status") == "running":  # the worker stopped mid-upload: it may or may not be live
            posted[platform] = {"status": "unknown", "error": f"The upload was interrupted. Check "
                                f"{PLATFORM_LABELS[platform]} before posting it again."}
            base._save(run)
            continue
        if platform not in accounts:
            posted[platform] = {"status": "failed", "error": f"{PLATFORM_LABELS[platform]} is no longer connected."}
            continue
        posted[platform] = {"status": "running"}
        base._save(run)
        try:
            result = PUBLISHERS[platform](accounts[platform], kind="video", source_url=asset.source_url,
                                          **_publish_kwargs(platform, out["posts"][platform], asset, thumbnail))
        except Exception as exc:  # noqa: BLE001 — shown per platform
            result = {"status": "failed", "error": user_error(exc, platform)}
        posted[platform] = result
        base._save(run)

    statuses = [posted[p].get("status") for p in chosen]
    job.status = ("succeeded" if all(s == "succeeded" for s in statuses)
                  else "partial" if "succeeded" in statuses else "failed")
    job.results = posted
    job.error = "; ".join(f"{p}: {posted[p]['error']}" for p in chosen if posted[p].get("error"))
    job.save(update_fields=["status", "results", "error", "updated_at"])
    if "succeeded" not in statuses:
        raise RuntimeError(f"Nothing was posted. {job.error}")


STEPS = {
    "fetch": step_fetch,
    "listen": step_listen,
    "write_post": step_write_post,
    "review_post": step_review_post,
    "wait": step_wait,
    "post": step_post,
}
