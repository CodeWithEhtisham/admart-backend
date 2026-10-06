"""Sync ImageJob status from fal (poll-on-read)."""

from __future__ import annotations

import logging


from content import fal_client
from content.credits import fail_open_job, mark_open_job, succeed_open_job
from content.library import sync_library_from_image_job
from content.models import ImageJob
from content.storage_utils import normalize_fal_images, persist_remote_image

logger = logging.getLogger(__name__)


def refresh_job(job: ImageJob, *, request=None) -> ImageJob:
    """If job is open, ask fal for status and finalize when complete."""
    if job.status in ("succeeded", "failed") or not job.fal_request_id:
        return job

    try:
        st = fal_client.status(
            status_url=job.fal_status_url,
            model=job.model,
            request_id=job.fal_request_id,
        )
    except fal_client.FalError as exc:
        logger.warning("fal status error job=%s: %s", job.id, exc)
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

    raw_images, raw_mask, seed = normalize_fal_images(payload)
    if not raw_images:
        _fail_job(job, "Provider returned no images")
        return job

    durable: list[dict] = []
    for i, item in enumerate(raw_images):
        try:
            asset = persist_remote_image(
                item["url"],
                project_id=str(job.project_id),
                job_id=str(job.id),
                index=i,
                prefix="out",
                request=request,
            )
            if item.get("width"):
                asset["width"] = item["width"]
            if item.get("height"):
                asset["height"] = item["height"]
            durable.append(asset)
        except Exception:
            logger.exception("Failed to persist fal image for job=%s", job.id)
            durable.append(
                {
                    "url": item["url"],
                    "contentType": item.get("content_type") or item.get("contentType"),
                    "fileName": item.get("file_name") or item.get("fileName"),
                    "width": item.get("width"),
                    "height": item.get("height"),
                }
            )

    mask_asset = None
    if raw_mask and raw_mask.get("url"):
        try:
            mask_asset = persist_remote_image(
                raw_mask["url"],
                project_id=str(job.project_id),
                job_id=str(job.id),
                index=0,
                prefix="mask",
                request=request,
            )
        except Exception:
            mask_asset = {
                "url": raw_mask["url"],
                "contentType": raw_mask.get("content_type"),
                "fileName": raw_mask.get("file_name"),
            }

    # Only the first finisher wins; if the job was cancelled (and refunded) meanwhile,
    # the result is discarded rather than delivered for free.
    if succeed_open_job(job, images=durable, mask_image=mask_asset, seed=seed):
        sync_library_from_image_job(job)
    return job


def _fail_job(job, message: str) -> None:
    fail_open_job(job, message)
    sync_library_from_image_job(job)
