"""Sync VideoJob status from fal (poll-on-read)."""

from __future__ import annotations

import logging
import re

from django.db import transaction

from content import fal_client
from content.credits import refund_credits
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
        if job.status != "queued":
            job.status = "queued"
            job.save(update_fields=["status", "updated_at"])
        return job
    if status_raw in ("IN_PROGRESS", "PROCESSING"):
        if job.status != "running":
            job.status = "running"
            job.save(update_fields=["status", "updated_at"])
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

    with transaction.atomic():
        job.status = "succeeded"
        job.video = durable
        job.seed = seed
        job.duration_seconds = duration
        job.credits_used = job.credits_reserved
        job.error = None
        job.save(
            update_fields=[
                "status",
                "video",
                "seed",
                "duration_seconds",
                "credits_used",
                "error",
                "updated_at",
            ]
        )
        sync_library_from_video_job(job)
    return job


def _fail_job(job: VideoJob, message: str) -> None:
    with transaction.atomic():
        job.status = "failed"
        job.error = message
        job.save(update_fields=["status", "error", "updated_at"])
        if job.credits_reserved and job.credits_used is None:
            refund_credits(job.user, int(job.credits_reserved))
            job.credits_reserved = 0
            job.save(update_fields=["credits_reserved", "updated_at"])
        sync_library_from_video_job(job)
