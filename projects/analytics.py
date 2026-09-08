"""Project analytics from PublishJob rows, plus live platform stats when available."""

from datetime import timedelta

from django.utils import timezone

from projects.insights import attach_metrics
from projects.media_policy import ORGANIC_PLATFORMS
from projects.models import PublishJob, SocialAccount

RANGE_DAYS = {"7d": 7, "30d": 30, "90d": 90}
VALID_RANGES = frozenset({"7d", "30d", "90d", "all"})


def build_project_analytics(project, *, range_key: str = "30d", platform: str = "all") -> dict:
    range_key = range_key if range_key in VALID_RANGES else "30d"
    connected_set = set(
        SocialAccount.objects.filter(
            project=project, connected=True, platform__in=ORGANIC_PLATFORMS
        ).values_list("platform", flat=True)
    )
    connected = [p for p in ORGANIC_PLATFORMS if p in connected_set]
    platform = platform if platform in connected else "all"
    now = timezone.now()
    start = None if range_key == "all" else now - timedelta(days=RANGE_DAYS[range_key])
    qs = PublishJob.objects.filter(project=project)
    if start is not None:
        qs = qs.filter(created_at__gte=start)
    jobs = list(qs.order_by("-created_at"))
    if platform != "all":
        jobs = [job for job in jobs if platform in (job.platforms or [])]
    elif connected:
        jobs = [job for job in jobs if any(p in connected for p in (job.platforms or []))]
    else:
        jobs = []

    by_platform = {p: {"count": 0, "succeeded": 0, "failed": 0} for p in connected}
    succeeded = failed = partial = videos = images = 0
    for job in jobs:
        if job.status == "succeeded":
            succeeded += 1
        elif job.status == "failed":
            failed += 1
        elif job.status == "partial":
            partial += 1
        if job.kind == "video":
            videos += 1
        elif job.kind == "image":
            images += 1
        for item in job.platforms or []:
            if item not in by_platform:
                continue
            by_platform[item]["count"] += 1
            send_status = _send_status(job, item)
            if send_status == "succeeded":
                by_platform[item]["succeeded"] += 1
            elif send_status == "failed":
                by_platform[item]["failed"] += 1

    series_start = start or (jobs[-1].created_at if jobs else now)
    series = _daily_series(jobs, series_start, now, connected)
    posts = []
    for job in jobs[:200]:
        dests = [p for p in (job.platforms or []) if p in connected]
        if platform != "all":
            dests = [p for p in dests if p == platform]
        for dest in dests:
            result = (job.results or {}).get(dest) or {}
            posts.append(
                {
                    "id": f"{job.id}:{dest}",
                    "jobId": str(job.id),
                    "assetId": str(job.library_asset_id) if job.library_asset_id else None,
                    "title": job.title or "Untitled",
                    "kind": job.kind,
                    "platform": dest,
                    "status": _send_status(job, dest) or job.status,
                    "error": result.get("error") or "",
                    "externalId": result.get("externalId") or "",
                    "pageId": result.get("pageId") or "",
                    "url": result.get("url") or "",
                    "sourceUrl": job.source_url,
                    "createdAt": job.created_at.isoformat(),
                }
            )
    attach_metrics(project, posts)
    return {
        "range": range_key,
        "platform": platform,
        "connectedPlatforms": connected,
        "totals": {
            "posts": len(jobs),
            "succeeded": succeeded,
            "failed": failed,
            "partial": partial,
            "videos": videos,
            "images": images,
        },
        "byPlatform": [{"id": p, **by_platform[p]} for p in connected],
        "series": series,
        "posts": posts,
    }


def _send_status(job, platform: str) -> str:
    row = (job.results or {}).get(platform)
    if isinstance(row, dict):
        status = (row.get("status") or "").strip()
        if status:
            return status
    if job.status in ("succeeded", "failed"):
        return job.status
    return ""


def _daily_series(jobs, start, end, platforms: list[str]) -> list[dict]:
    counts = {}
    for job in jobs:
        day = timezone.localtime(job.created_at).date().isoformat()
        bucket = counts.setdefault(day, {p: 0 for p in platforms})
        for item in job.platforms or []:
            if item in bucket:
                bucket[item] += 1
    rows = []
    day = timezone.localtime(start).date()
    last = timezone.localtime(end).date()
    empty = {p: 0 for p in platforms}
    while day <= last:
        key = day.isoformat()
        row = {"date": key}
        row.update(counts.get(key, empty))
        rows.append(row)
        day += timedelta(days=1)
    return rows
