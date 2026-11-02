"""Sync VideoJob status from fal (poll-on-read)."""

from __future__ import annotations

import logging
import re


from content import fal_client
from content.credits import fail_open_job, mark_open_job, succeed_open_job
from content.library import sync_library_from_video_job
from content.models import VideoJob
from content.storage_utils import normalize_fal_video, persist_remote_video

logger = logging.getLogger(__name__)


def _parse_duration_seconds(raw) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return max(0, int(raw))
    text = str(raw).strip().lower().rstrip("s")
    if text.isdigit():
        return int(text)
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else None


def refresh_video_job(job: VideoJob, *, request=None) -> VideoJob:
    if job.status in ("succeeded", "failed") or not job.fal_request_id:
        return job

    try:
        st = fal_client.status(
            status_url=job.fal_status_url,
            model=job.model,
            request_id=job.fal_request_id,
        )
    except fal_client.FalError as exc:
        logger.warning("fal status error video_job=%s: %s", job.id, exc)
        return job

    status_raw = (st.get("status") or "").upper()
    if status_raw in ("IN_QUEUE", "QUEUED"):
        mark_open_job(job, "queued")
        return job
    if status_raw in ("IN_PROGRESS", "PROCESSING"):
        mark_open_job(job, "running")
        return job
    if status_raw in ("FAILED", "ERROR", "CANCELLED"):
        _fail_job(job, st.get("error") or "Generation failed")
        return job
    if status_raw not in ("COMPLETED", "OK", "SUCCESS"):
        return job

    try:
        payload = fal_client.result(
            response_url=job.fal_response_url,
            model=job.model,
            request_id=job.fal_request_id,
        )
    except fal_client.FalError as exc:
        _fail_job(job, str(exc) or "Provider error")
        return job

    raw_video, seed = normalize_fal_video(payload)
    if not raw_video or not raw_video.get("url"):
        _fail_job(job, "Provider returned no video")
        return job

    try:
        durable = persist_remote_video(
            raw_video["url"],
            project_id=str(job.project_id),
            job_id=str(job.id),
            request=request,
        )
    except Exception:
        logger.exception("Failed to persist fal video for job=%s", job.id)
        durable = {
            "url": raw_video["url"],
            "providerUrl": raw_video["url"],
            "contentType": raw_video.get("content_type") or raw_video.get("contentType") or "video/mp4",
            "fileName": raw_video.get("file_name") or raw_video.get("fileName"),
        }

    duration = _parse_duration_seconds(
        (job.request or {}).get("duration")
    ) or _parse_duration_seconds(payload.get("duration"))

    # Only the first finisher wins; see content/jobs.py.
    if succeed_open_job(job, video=durable, seed=seed, duration_seconds=duration):
        sync_library_from_video_job(job)
    return job


def _fail_job(job, message: str) -> None:
    fail_open_job(job, message)
    sync_library_from_video_job(job)
