"""Make image URLs reachable by fal (localhost media → data URI)."""

from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings

logger = logging.getLogger(__name__)

LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "[::1]"}


def resolve_urls_for_fal(urls: list[str]) -> list[str]:
    """Rewrite local / private media URLs into data URIs fal can consume."""
    return [resolve_url_for_fal(u) for u in urls]


def resolve_url_for_fal(url: str) -> str:
    if not url:
        return url
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    # Already a data URI
    if parsed.scheme == "data":
        return url

    # Public remote URL — pass through (fal will fetch it).
    if parsed.scheme in ("http", "https") and host not in LOCAL_HOSTS:
        return url

    # Local media URL → read from disk → data URI
    media_url = settings.MEDIA_URL or "/media/"
    path = parsed.path or ""
    if media_url.rstrip("/") and path.startswith(media_url.rstrip("/")):
        rel = path[len(media_url.rstrip("/")) :].lstrip("/")
    elif path.startswith("/media/"):
        rel = path[len("/media/") :]
    else:
        raise ValueError(
            "Image URL is not publicly reachable by fal. "
            "Upload via /images/uploads or use a public HTTPS URL "
            "(localhost media cannot be fetched by fal)."
        )

    abs_path = Path(settings.MEDIA_ROOT) / rel
    if not abs_path.is_file():
        raise ValueError(f"Local media file not found for image URL: {url}")

    content_type = mimetypes.guess_type(str(abs_path))[0] or "image/jpeg"
    raw = abs_path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    logger.info("Rewrote local media URL to data URI (%s bytes) for fal", len(raw))
    return f"data:{content_type};base64,{b64}"
