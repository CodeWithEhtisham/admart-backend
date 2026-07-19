"""Sync LibraryAsset rows from image (and later video) jobs."""

from __future__ import annotations

from content.models import ImageJob, LibraryAsset


def _title_from_prompt(prompt: str | None) -> str:
    text = (prompt or "").strip()
    if not text:
        return "Untitled"
    return text[:80] + ("…" if len(text) > 80 else "")


def sync_library_from_image_job(job: ImageJob) -> list[LibraryAsset]:
    """Upsert library assets for a terminal image job."""
    if job.status == "succeeded":
        return _sync_succeeded(job)
    if job.status == "failed":
        return _sync_failed(job)
    return list(LibraryAsset.objects.filter(image_job=job, deleted_at__isnull=True))


def _sync_succeeded(job: ImageJob) -> list[LibraryAsset]:
    images = job.images or []
    if not images:
        return []

    assets: list[LibraryAsset] = []
    for index, img in enumerate(images):
        url = (img or {}).get("url") or ""
        if not url:
            continue
        defaults = {
            "project": job.project,
            "user": job.user,
            "media_type": "image",
            "title": _title_from_prompt(job.prompt),
            "status": "ready",
            "thumbnail_url": url,
            "source_url": url,
            "prompt": job.prompt,
            "model": job.model,
            "capability": job.capability,
            "width": img.get("width"),
            "height": img.get("height"),
            "deleted_at": None,
        }
        asset, _ = LibraryAsset.objects.update_or_create(
            image_job=job,
            source_index=index,
            defaults=defaults,
        )
        assets.append(asset)

    # Soft-delete extras if a previous run had more images
    from django.utils import timezone

    LibraryAsset.objects.filter(
        image_job=job, source_index__gte=len(images), deleted_at__isnull=True
    ).update(deleted_at=timezone.now())
    return assets


def _sync_failed(job: ImageJob) -> list[LibraryAsset]:
    assets = list(LibraryAsset.objects.filter(image_job=job, deleted_at__isnull=True))
    if assets:
        for asset in assets:
            asset.status = "failed"
            asset.save(update_fields=["status", "updated_at"])
        return assets

    # Optional failed card so history is visible
    asset = LibraryAsset.objects.create(
        project=job.project,
        user=job.user,
        media_type="image",
        title=_title_from_prompt(job.prompt),
        status="failed",
        prompt=job.prompt,
        model=job.model,
        capability=job.capability,
        image_job=job,
        source_index=0,
    )
    return [asset]


def mark_library_generating(job: ImageJob) -> LibraryAsset:
    """Create/update a generating placeholder when a job is submitted."""
    asset, _ = LibraryAsset.objects.update_or_create(
        image_job=job,
        source_index=0,
        defaults={
            "project": job.project,
            "user": job.user,
            "media_type": "image",
            "title": _title_from_prompt(job.prompt),
            "status": "generating",
            "thumbnail_url": None,
            "source_url": "",
            "prompt": job.prompt,
            "model": job.model,
            "capability": job.capability,
            "deleted_at": None,
        },
    )
    return asset
