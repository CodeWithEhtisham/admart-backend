"""Make image URLs reachable by fal (localhost media → data URI)."""

from __future__ import annotations

import base64
import ipaddress
import logging
import mimetypes
import socket
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
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
    abs_path = media_file(url)
    content_type = mimetypes.guess_type(str(abs_path))[0] or "image/jpeg"
    raw = abs_path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    logger.info("Rewrote local media URL to data URI (%s bytes) for fal", len(raw))
    return f"data:{content_type};base64,{b64}"


def media_file(url: str) -> Path:
    """Map one of our ``/media/...`` URLs to its file, never outside MEDIA_ROOT.

    Payment proof screenshots are excluded: they are never valid generation or
    publish inputs.
    """
    path = urlparse(url).path or ""
    prefix = (settings.MEDIA_URL or "/media/").rstrip("/") + "/"
    if not path.startswith(prefix):
        raise ValueError(
            "Image URL is not publicly reachable by fal. "
            "Upload via /images/uploads or use a public HTTPS URL "
            "(localhost media cannot be fetched by fal)."
        )
    root = Path(settings.MEDIA_ROOT).resolve()
    file = (root / unquote(path[len(prefix):])).resolve()
    if not file.is_relative_to(root) or file.relative_to(root).parts[:1] == ("payments",):
        raise ValueError(f"Media URL is not allowed: {url}")
    if not file.is_file():
        raise ValueError(f"Local media file not found for image URL: {url}")
    return file


def fetch_media(url: str, *, timeout: int) -> tuple[bytes, str]:
    """Return (bytes, content type) for media to publish.

    Our own media (localhost or MEDIA_BASE_URL host) is read from disk. Anything
    else is fetched only if it resolves to public internet addresses, without
    following redirects, so user-supplied URLs can't reach internal services.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    own_hosts = set(LOCAL_HOSTS) | {"::1"}
    media_base_host = urlparse(getattr(settings, "MEDIA_BASE_URL", "") or "").hostname
    if media_base_host:
        own_hosts.add(media_base_host.lower())
    if host in own_hosts:
        file = media_file(url)
        return file.read_bytes(), mimetypes.guess_type(str(file))[0] or ""

    if parsed.scheme not in ("http", "https") or not host:
        raise ValueError("Media URL must be http(s).")
    # ponytail: the host is resolved here and again by requests (DNS-rebinding
    # window); pin the checked IP if attacker-controlled DNS becomes a concern.
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror as exc:
        raise ValueError(f"Media host could not be resolved: {host}") from exc
    if not addresses or not all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses):
        raise ValueError("Media URL must point to a public internet address.")
    resp = requests.get(url, timeout=timeout, allow_redirects=False)
    if resp.is_redirect:
        raise ValueError("Media URL redirects are not allowed.")
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type") or ""
