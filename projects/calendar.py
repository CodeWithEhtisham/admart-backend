"""Project calendar: publish jobs plus in-progress generations."""

from calendar import monthrange
from datetime import datetime

from django.utils import timezone

from content.models import ImageJob, VideoJob
from projects.models import PublishJob

PLATFORM_CODE = {
    "tiktok": "T",
    "youtube": "Y",
    "instagram": "I",
    "facebook": "F",
}
PLATFORM_NAME = {
    "tiktok": "TikTok",
    "youtube": "YouTube",
    "instagram": "Instagram",
    "facebook": "Facebook",
}

GEN_STATUSES = ("queued", "running")


def build_project_calendar(project, *, year: int, month: int) -> dict:
    start, end = _month_bounds(year, month)
    events = []
    events.extend(_publish_events(project, start, end))
    events.extend(_generation_events(project, start, end))
    events.sort(key=lambda row: row["at"])
    return {"year": year, "month": month, "events": events}


def _month_bounds(year: int, month: int):
    last = monthrange(year, month)[1]
    start = timezone.make_aware(datetime(year, month, 1, 0, 0, 0))
    end = timezone.make_aware(datetime(year, month, last, 23, 59, 59))
    return start, end


def _clip(text, fallback):
    value = " ".join((text or "").split())
    if not value:
        return fallback
    return value[:48] + "…" if len(value) > 48 else value


def _event(eid, title, status, at, platform="", platform_name="", error=""):
    local = timezone.localtime(at)
    hour = local.hour % 12 or 12
    ampm = "AM" if local.hour < 12 else "PM"
    return {
        "id": eid,
        "title": title,
        "status": status,
        "platform": platform,
        "platformName": platform_name,
        "error": error,
        "at": local.isoformat(),
        "time": f"{hour}:{local.strftime('%M')} {ampm}",
    }


def _publish_status(job, platform: str):
    if job.status == "draft":
        return ""
    if job.status in ("scheduled",):
        return "scheduled"
    if job.status in ("queued", "running"):
        return "generating"
    row = (job.results or {}).get(platform) or {}
    send = (row.get("status") or "").strip()
    if send == "scheduled":
        return "scheduled"
    if send == "succeeded":
        return "published"
    if send == "failed":
        return "failed"
    if job.status == "succeeded":
        return "published"
    if job.status == "failed":
        return "failed"
    if job.status == "partial":
        return "failed" if send == "failed" else "published"
    return ""


def _publish_events(project, start, end):
    jobs = PublishJob.objects.filter(project=project).exclude(status="draft")
    rows = []
    for job in jobs:
        when = job.scheduled_at or job.created_at
        if when is None or when < start or when > end:
            continue
        title = _clip(job.title, "Untitled post")
        for platform in job.platforms or []:
            code = PLATFORM_CODE.get(platform)
            if not code:
                continue
            status = _publish_status(job, platform)
            if not status:
                continue
            result = (job.results or {}).get(platform) or {}
            error = str(result.get("error") or "") if status == "failed" else ""
            rows.append(
                _event(
                    f"pub:{job.id}:{platform}",
                    title,
                    status,
                    when,
                    PLATFORM_CODE[platform],
                    PLATFORM_NAME[platform],
                    error,
                )
            )
    return rows


def _generation_events(project, start, end):
    rows = []
    images = ImageJob.objects.filter(project=project, created_at__gte=start, created_at__lte=end)
    for job in images:
        if job.status in GEN_STATUSES:
            status = "generating"
        elif job.status == "failed":
            status = "failed"
        else:
            continue
        title = _clip(job.prompt, "Image generation")
        error = str(job.error or "") if status == "failed" else ""
        rows.append(_event(f"img:{job.id}", title, status, job.created_at, "", "Image", error))
    videos = VideoJob.objects.filter(project=project, created_at__gte=start, created_at__lte=end)
    for job in videos:
        if job.status in GEN_STATUSES:
            status = "generating"
        elif job.status == "failed":
            status = "failed"
        else:
            continue
        title = _clip(job.prompt, "Video generation")
        error = str(job.error or "") if status == "failed" else ""
        rows.append(_event(f"vid:{job.id}", title, status, job.created_at, "", "Video", error))
    return rows
