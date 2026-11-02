"""Sync LibraryAsset rows from image and video jobs."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.utils import timezone

from content.models import ImageJob, LibraryAsset, VideoJob
from content.storage_quota import storage_changed
from content.url_resolve import media_file


def _title_from_prompt(prompt: str | None) -> str:
    text = (prompt or "").strip()
    if not text:
        return "Untitled"
    return text[:80] + ("…" if len(text) > 80 else "")


def delete_asset_file(asset: LibraryAsset) -> None:
    """Free the storage of a library item the user deleted: remove its file from the project's folder,
    unless another item still in the library shows the same file."""
    url = asset.source_url
    if not url or LibraryAsset.objects.filter(
        project_id=asset.project_id, source_url=url, deleted_at__isnull=True
    ).exclude(pk=asset.pk).exists():
        return
    try:
        path = media_file(url)
    except ValueError:  # not our file (e.g. a fal URL), or already gone
        return
    root = Path(settings.MEDIA_ROOT).resolve()
    if not path.is_relative_to(root / "projects" / str(asset.project_id)):
        return
    from agents.management.commands.cleanup_clip_sources import FINISHED
    from agents.models import AgentRun

    if AgentRun.objects.filter(
        project_id=asset.project_id, output__clip_source=path.relative_to(root).as_posix()
    ).exclude(status__in=FINISHED).exists():
        return  # Clip Maker is still working on it; cleanup_clip_sources removes it once that run is done
    path.unlink(missing_ok=True)
    storage_changed(asset.user_id)


def sync_library_from_image_job(job: ImageJob) -> list[LibraryAsset]:
    """Upsert library assets for a terminal image job."""
    if job.status == "succeeded":
        return _sync_image_succeeded(job)
    if job.status == "failed":
        return _sync_image_failed(job)
    return list(LibraryAsset.objects.filter(image_job=job, deleted_at__isnull=True))


def _sync_image_succeeded(job: ImageJob) -> list[LibraryAsset]:
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

    LibraryAsset.objects.filter(
        image_job=job, source_index__gte=len(images), deleted_at__isnull=True
    ).update(deleted_at=timezone.now())
    return assets


def _sync_image_failed(job: ImageJob) -> list[LibraryAsset]:
    assets = list(LibraryAsset.objects.filter(image_job=job, deleted_at__isnull=True))
    if assets:
        for asset in assets:
            asset.status = "failed"
            asset.save(update_fields=["status", "updated_at"])
        return assets

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
    """Create/update a generating placeholder when an image job is submitted."""
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


def sync_library_from_video_job(job: VideoJob) -> list[LibraryAsset]:
    if job.status == "succeeded":
        return _sync_video_succeeded(job)
    if job.status == "failed":
        return _sync_video_failed(job)
    return list(LibraryAsset.objects.filter(video_job=job, deleted_at__isnull=True))


def _sync_video_succeeded(job: VideoJob) -> list[LibraryAsset]:
    video = job.video or {}
    url = video.get("url") or ""
    if not url:
        return []
    defaults = {
        "project": job.project,
        "user": job.user,
        "media_type": "video",
        "title": _title_from_prompt(job.prompt),
        "status": "ready",
        "thumbnail_url": url,
        "source_url": url,
        "prompt": job.prompt,
        "model": job.model,
        "capability": job.capability,
        "duration_seconds": job.duration_seconds,
        "deleted_at": None,
    }
    asset, _ = LibraryAsset.objects.update_or_create(
        video_job=job,
        source_index=0,
        defaults=defaults,
    )
    return [asset]


def _sync_video_failed(job: VideoJob) -> list[LibraryAsset]:
    assets = list(LibraryAsset.objects.filter(video_job=job, deleted_at__isnull=True))
    if assets:
        for asset in assets:
            asset.status = "failed"
            asset.save(update_fields=["status", "updated_at"])
        return assets

    asset = LibraryAsset.objects.create(
        project=job.project,
        user=job.user,
        media_type="video",
        title=_title_from_prompt(job.prompt),
        status="failed",
        prompt=job.prompt,
        model=job.model,
        capability=job.capability,
        video_job=job,
        source_index=0,
    )
    return [asset]


def mark_library_generating_video(job: VideoJob) -> LibraryAsset:
    asset, _ = LibraryAsset.objects.update_or_create(
        video_job=job,
        source_index=0,
        defaults={
            "project": job.project,
            "user": job.user,
            "media_type": "video",
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
