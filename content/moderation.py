"""Content moderation: refuse adult or harmful prompts, input images and generated output.

Every check goes to OpenAI's free Moderation API (omni-moderation-latest), which reads text
and images. Plain "violence", "harassment" and "illicit" pass: ads mention fights, rivals
and crime dramas, and those flags fire on them. Everything stronger (sexual content, minors,
self-harm, graphic violence, threats, hate, violent wrongdoing) is blocked.

A refused check is logged as a ModerationEvent; LOCK_AFTER unreviewed events in a day pause
the user's generation until an admin marks them reviewed.
"""

import base64
import contextlib
import contextvars
import logging
import subprocess
from datetime import timedelta

import requests
from django.conf import settings
from django.utils import timezone

from content.models import ModerationEvent

logger = logging.getLogger(__name__)

MODERATION_URL = "https://api.openai.com/v1/moderations"
MODEL = "omni-moderation-latest"
ALLOWED_CATEGORIES = frozenset({"violence", "harassment", "illicit"})
CHUNK_CHARS = 2000  # OpenAI's guidance: shorter chunks are classified more accurately
MAX_TEXT_CHARS = 40_000
LOCK_AFTER = 5
LOCK_WINDOW = timedelta(hours=24)
TIMEOUT = 20

BLOCKED_MESSAGE = (
    "This was blocked by Admart's content rules: no adult, sexual or harmful content. "
    "Change it and try again."
)
LOCKED_MESSAGE = (
    "Generation is paused on your account after several blocked requests. Contact support to have it reviewed."
)
UNAVAILABLE_MESSAGE = "Admart's content check is unavailable right now. Try again in a minute."

# Gemini's own filters at their strictest, for every Gemini text call.
GEMINI_SAFETY_SETTINGS = [
    {"category": category, "threshold": "BLOCK_LOW_AND_ABOVE"}
    for category in (
        "HARM_CATEGORY_HARASSMENT",
        "HARM_CATEGORY_HATE_SPEECH",
        "HARM_CATEGORY_SEXUALLY_EXPLICIT",
        "HARM_CATEGORY_DANGEROUS_CONTENT",
    )
]

_acting_user_id = contextvars.ContextVar("moderation_user_id", default=None)


class ContentBlocked(ValueError):
    """The content (or the user) is not allowed to generate. The message is safe to show."""


class ModerationUnavailable(RuntimeError):
    """The check could not run. Generation is refused rather than let through unchecked."""


@contextlib.contextmanager
def acting_as(user_id):
    """Attribute checks inside this block to a user (agent runs, which have no request)."""
    token = _acting_user_id.set(user_id)
    try:
        yield
    finally:
        _acting_user_id.reset(token)


def _user_id(user):
    return getattr(user, "pk", user) if user is not None else _acting_user_id.get()


def _active() -> bool:
    if settings.OPENAI_API_KEY:
        return True
    if settings.MODERATION_REQUIRED:
        raise ModerationUnavailable(UNAVAILABLE_MESSAGE)
    return False


def ensure_allowed(user=None) -> None:
    """Refuse a user whose generation is paused."""
    uid = _user_id(user)
    if uid and (
        ModerationEvent.objects.filter(
            user_id=uid, reviewed=False, created_at__gt=timezone.now() - LOCK_WINDOW
        ).count()
        >= LOCK_AFTER
    ):
        raise ContentBlocked(LOCKED_MESSAGE)


def _blocked_categories(inputs: list) -> list[str]:
    try:
        resp = requests.post(
            MODERATION_URL,
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            json={"model": MODEL, "input": inputs},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.warning("Moderation request failed: %s", exc)
        raise ModerationUnavailable(UNAVAILABLE_MESSAGE) from exc
    if not resp.ok:
        logger.warning("Moderation returned %s: %s", resp.status_code, resp.text[:300])
        raise ModerationUnavailable(UNAVAILABLE_MESSAGE)
    hits = set()
    for result in resp.json().get("results") or []:
        hits |= {name for name, on in (result.get("categories") or {}).items() if on and name not in ALLOWED_CATEGORIES}
    return sorted(hits)


def _refuse(categories, *, user, source: str, kind: str, excerpt: str) -> None:
    ModerationEvent.objects.create(
        user_id=_user_id(user), source=source[:40], kind=kind, categories=categories, excerpt=excerpt[:500]
    )
    logger.info("Moderation blocked %s from %s: %s", kind, source, categories)
    raise ContentBlocked(BLOCKED_MESSAGE)


def check_text(text: str, *, user=None, source: str = "") -> None:
    ensure_allowed(user)
    text = (text or "").strip()
    if not text or not _active():
        return
    text = text[:MAX_TEXT_CHARS]
    hits = _blocked_categories([text[i : i + CHUNK_CHARS] for i in range(0, len(text), CHUNK_CHARS)])
    if hits:
        _refuse(hits, user=user, source=source, kind="text", excerpt=text)


def check_image(url: str, *, user=None, source: str = "", kind: str = "image") -> None:
    """`url` is a public https URL or a data: URI. One image per request (the API's limit)."""
    ensure_allowed(user)
    if not url or not _active():
        return
    hits = _blocked_categories([{"type": "image_url", "image_url": {"url": url}}])
    if hits:
        _refuse(hits, user=user, source=source, kind=kind, excerpt=url if url.startswith("http") else "(inline image)")


def check_image_bytes(data: bytes, content_type: str = "image/png", *, user=None, source: str = "", kind: str = "image"):
    check_image(
        f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}", user=user, source=source, kind=kind
    )


def check_video(url: str, *, user=None, source: str = "") -> None:
    """Three frames (start, middle, end) through the image check. Needs FFmpeg."""
    ensure_allowed(user)
    if not url or not _active():
        return
    for frame in _frames(url):
        check_image_bytes(frame, "image/jpeg", user=user, source=source, kind="video")


def _frames(url: str) -> list[bytes]:
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", url],
            capture_output=True, text=True, check=True, timeout=60,
        )
        duration = float(probe.stdout.strip() or 0)
        frames = []
        for at in sorted({0.5, duration / 2, max(duration - 0.5, 0.0)}):
            done = subprocess.run(
                ["ffmpeg", "-v", "error", "-ss", f"{at:.2f}", "-i", url, "-frames:v", "1",
                 "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"],
                capture_output=True, check=True, timeout=120,
            )
            if done.stdout:
                frames.append(done.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        logger.warning("Could not read video frames for moderation: %s", exc)
        raise ModerationUnavailable(UNAVAILABLE_MESSAGE) from exc
    if not frames:
        raise ModerationUnavailable(UNAVAILABLE_MESSAGE)
    return frames


def check_fal_input(arguments: dict, *, user=None, source: str = "generation") -> None:
    """The prompt and every input image of a fal job (start/end frames, references, edits)."""
    check_text(
        "\n".join(arguments[key] for key in ("prompt", "text") if isinstance(arguments.get(key), str)),
        user=user,
        source=source,
    )
    for key, value in arguments.items():
        if "image_url" not in key:
            continue
        for url in value if isinstance(value, list) else [value]:
            if isinstance(url, str) and url.startswith(("http", "data:image")):
                check_image(url, user=user, source=source)
