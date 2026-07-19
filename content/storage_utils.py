"""Persist uploads and fal result images under MEDIA_ROOT."""

from __future__ import annotations

import logging
import mimetypes
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def absolute_media_url(relative_path: str, request=None) -> str:
    """Build a public HTTPS/HTTP URL fal (and FE) can fetch."""
    path = relative_path.lstrip("/")
    if request is not None:
        return request.build_absolute_uri(f"{settings.MEDIA_URL}{path}")
    base = getattr(settings, "MEDIA_BASE_URL", "").rstrip("/")
    if base:
        return f"{base}{settings.MEDIA_URL}{path}"
    # Fallback for local: relative MEDIA_URL (FE may need absolute via Vite proxy).
    return f"{settings.MEDIA_URL}{path}"


def persist_remote_image(
    source_url: str,
    *,
    project_id: str,
    job_id: str,
    index: int = 0,
    prefix: str = "out",
    request=None,
) -> dict:
    """Download a fal (or any) image URL into MEDIA and return an ImageAsset dict."""
    resp = requests.get(source_url, timeout=120)
    resp.raise_for_status()
    content_type = resp.headers.get("Content-Type", "image/png").split(";")[0].strip()
    ext = mimetypes.guess_extension(content_type) or Path(urlparse(source_url).path).suffix or ".png"
    if ext == ".jpe":
        ext = ".jpg"

    rel_dir = Path("projects") / str(project_id) / "images" / str(job_id)
    abs_dir = Path(settings.MEDIA_ROOT) / rel_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{prefix}-{index}{ext}"
    abs_path = abs_dir / file_name
    abs_path.write_bytes(resp.content)

    rel = str(rel_dir / file_name).replace("\\", "/")
    return {
        "url": absolute_media_url(rel, request=request),
        # Original fal CDN URL — useful if a client wants a public chain URL.
        "providerUrl": source_url,
        "contentType": content_type,
        "fileName": file_name,
        "width": None,
        "height": None,
    }


def normalize_fal_images(payload: dict) -> tuple[list[dict], dict | None, int | None]:
    """Extract image list, optional mask, and seed from a fal result payload."""
    seed = payload.get("seed")
    mask = None
    images: list[dict] = []

    if "images" in payload and isinstance(payload["images"], list):
        for item in payload["images"]:
            if isinstance(item, dict) and item.get("url"):
                images.append(item)
    elif isinstance(payload.get("image"), dict) and payload["image"].get("url"):
        images.append(payload["image"])

    if isinstance(payload.get("mask_image"), dict) and payload["mask_image"].get("url"):
        mask = payload["mask_image"]

    return images, mask, seed
