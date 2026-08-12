"""Fetch featured templates from the meigen.ai public gallery into the Template model.

Usage:
    python manage.py fetch_meigen_templates                 # 200 images + 100 videos
    python manage.py fetch_meigen_templates --images 5 --videos 5 --dry-run
    python manage.py fetch_meigen_templates --keep-owned    # keep owned seeds active
"""

from __future__ import annotations

import math
import re
import time

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from content.models import Template

MEIGEN_IMAGES_URL = "https://www.meigen.ai/api/images"
MEIGEN_VIDEOS_URL = "https://www.meigen.ai/api/videos"

PAGE_SIZE = 24
REQUEST_TIMEOUT = 30
REQUEST_RETRIES = 3
REQUEST_DELAY = 0.35  # seconds between API calls (rate limiting courtesy)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

PLACEHOLDER_RE = re.compile(r"\[([^\[\]\n]{1,60})\]")
MIN_PROMPT_LENGTH = 20

# meigen display name -> fal model id used for actual generation
IMAGE_MODEL_MAP = {
    "GPT Image": "openai/gpt-image-2",
    "Nanobanana Pro": "fal-ai/nano-banana-pro",
    "Midjourney": "fal-ai/nano-banana-2",
    "Z Image Turbo": "fal-ai/nano-banana-2",
}
VIDEO_MODEL_MAP = {
    "Seedance": "bytedance/seedance-2.0/text-to-video",
}
IMAGE_FALLBACK_MODEL = "fal-ai/flux/dev"
VIDEO_FALLBACK_MODEL = "bytedance/seedance-2.0/text-to-video"


def normalize_key(raw: str) -> str:
    """Mirror the frontend normalizeFieldKey() so keys agree across stacks."""
    key = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", raw)
    key = re.sub(r"[^a-zA-Z0-9]+", "_", key).strip("_")
    return key.upper()


def humanize_key(key: str) -> str:
    return key.lower().replace("_", " ").title()


def extract_placeholders(prompt: str) -> list[dict]:
    """Pull [PLACEHOLDER] tokens from a prompt into quickField definitions.

    Non-Latin tokens (e.g. Chinese) get a stable ``token_N`` key so the
    frontend can render inputs and substitute values by raw token text.
    Structured JSON prompts are skipped — their brackets are not fields.
    """
    prompt = prompt or ""
    if prompt.lstrip().startswith(("{", "[")):
        return []
    seen: dict[str, str] = {}
    fallback_index = 0
    for match in PLACEHOLDER_RE.findall(prompt):
        token = match.strip()
        if len(token) < 2 or not re.search(r"[A-Za-z\u4e00-\u9fff]", token):
            continue
        key = normalize_key(token)
        if not key:
            key = f"token_{fallback_index}"
            fallback_index += 1
        seen.setdefault(key, token)
    return [
        {
            "key": key,
            "label": token if key.startswith("token_") else humanize_key(key),
            "placeholder": "",
            "defaultValue": "",
            "type": "text",
        }
        for key, token in seen.items()
    ]


def infer_aspect_ratio(width: int | None, height: int | None) -> str:
    """Map image dimensions to the closest supported aspect ratio."""
    try:
        w = int(width or 0)
        h = int(height or 0)
    except (TypeError, ValueError):
        w = h = 0
    if w <= 0 or h <= 0:
        return "1:1"
    ratio = w / h
    if ratio >= 1.5:
        return "16:9"
    if ratio >= 1.3:
        return "4:3"
    if 0.9 <= ratio < 1.3:
        return "1:1"
    if ratio >= 0.7:
        return "4:5"
    return "9:16"


VIDEO_ASPECT_STANDARDS = [
    ("21:9", 21 / 9),
    ("16:9", 16 / 9),
    ("4:3", 4 / 3),
    ("1:1", 1.0),
    ("3:4", 3 / 4),
    ("9:16", 9 / 16),
]


def normalize_video_aspect(aspect: str) -> str:
    """Snap a meigen video aspect string (e.g. '319:180') to a supported ratio."""
    raw = (aspect or "").strip()
    if raw in {label for label, _ in VIDEO_ASPECT_STANDARDS}:
        return raw
    try:
        w_text, h_text = raw.split(":")
        ratio = float(w_text) / float(h_text)
    except (ValueError, ZeroDivisionError):
        return "9:16"
    best = min(VIDEO_ASPECT_STANDARDS, key=lambda item: abs(item[1] - ratio))
    return best[0]


def build_seed(item: dict) -> dict | None:
    """Convert a meigen API item into a Template seed payload (or None to skip)."""
    is_video = (item.get("mediaType") or "").lower() == "video"
    prompt = (item.get("prompt") or "").strip()
    if item.get("promptReady") is False or len(prompt) < MIN_PROMPT_LENGTH:
        return None

    meigen_model = (item.get("model") or "other").strip() or "other"
    if is_video:
        model = VIDEO_MODEL_MAP.get(meigen_model, VIDEO_FALLBACK_MODEL)
        capability = "textToVideo"
    else:
        model = IMAGE_MODEL_MAP.get(meigen_model, IMAGE_FALLBACK_MODEL)
        capability = "textToImage"

    if is_video:
        aspect = normalize_video_aspect(item.get("aspectRatio") or "9:16")
        settings = {
            "aspectRatio": aspect,
            "resolution": "1080p",
            "duration": "8",
            "numImages": 1,
        }
    else:
        aspect = infer_aspect_ratio(item.get("imageWidth"), item.get("imageHeight"))
        settings = {
            "aspectRatio": aspect,
            "resolution": "1K",
            "numImages": 1,
        }

    preview_url = (item.get("image") or "").strip()
    if not preview_url:
        images = item.get("images") or []
        preview_url = (images[0] if images else "").strip()
    if not preview_url:
        return None

    author = item.get("author") or {}
    stats = item.get("stats") or {}
    meigen_id = str(item.get("id") or "")
    if not meigen_id:
        return None

    title = ((item.get("title") or "").strip() or prompt)[:180]
    if len(title) < 20:
        # Garbage titles like "{" fall back to the start of the prompt.
        title = prompt[:180]
    try:
        likes = int(stats.get("likes") or 0)
    except (TypeError, ValueError):
        likes = 0

    config = {
        "source": "meigen",
        "seedKey": f"meigen:{meigen_id}",
        "kind": "video" if is_video else "image",
        "capability": capability,
        "model": model,
        "modelName": meigen_model,
        "prompt": prompt,
        "negativePrompt": "",
        "description": title,
        "quickFields": extract_placeholders(prompt),
        "settings": settings,
        "author": {
            "name": (author.get("name") or "").strip() or (author.get("username") or "").strip(),
            "username": (author.get("username") or "").strip(),
            "avatar": (author.get("avatar") or "").strip(),
            "profileUrl": (author.get("profileUrl") or "").strip(),
        },
        "stats": {"likes": likes, "views": stats.get("views") or 0},
        "sourceUrl": f"https://x.com/{author.get('username') or ''}/status/{meigen_id}",
        "sourceMeigenId": meigen_id,
    }
    if is_video and (item.get("videoUrl") or "").strip():
        config["videoUrl"] = (item.get("videoUrl") or "").strip()

    return {
        "id": f"meigen-{meigen_id}",
        "title": title,
        "category": "reel" if is_video else "ad",
        "format": f"{aspect} {'video' if is_video else 'image'}",
        "is_video": is_video,
        "preview_url": preview_url,
        "uses_count": likes,
        "uses_last_7d": 0,
        "template_config": config,
    }


class Command(BaseCommand):
    help = "Fetch featured meigen.ai templates and seed/update the Template gallery."

    def add_arguments(self, parser):
        parser.add_argument("--images", type=int, default=200)
        parser.add_argument("--videos", type=int, default=100)
        parser.add_argument("--keep-owned", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        image_count = max(0, options["images"])
        video_count = max(0, options["videos"])
        keep_owned = bool(options["keep_owned"])
        dry_run = bool(options["dry_run"])

        self.stdout.write(f"Fetching featurered templates: {image_count} images, {video_count} videos ...")

        seeds: list[dict] = []
        skipped = 0
        if image_count:
            seeds, skipped = self._fetch(MEIGEN_IMAGES_URL, image_count)
        if video_count:
            video_seeds, video_skipped = self._fetch(MEIGEN_VIDEOS_URL, video_count)
            seeds.extend(video_seeds)
            skipped += video_skipped

        if not seeds:
            raise CommandError("No usable templates were fetched from meigen.ai.")

        if dry_run:
            videos = sum(1 for s in seeds if s["is_video"])
            models = sorted({s["template_config"]["modelName"] for s in seeds})
            self.stdout.write(
                self.style.WARNING(
                    f"[dry-run] {len(seeds)} seeds ready "
                    f"({len(seeds) - videos} images, {videos} videos, {skipped} skipped). "
                    f"Models: {', '.join(models)}"
                )
            )
            for seed in seeds[:5]:
                self.stdout.write(
                    f"  - {seed['title'][:80]} | {seed['template_config']['modelName']} | "
                    f"{seed['preview_url'][:100]}"
                )
            return

        created, updated, deactivated = self._store(seeds, keep_owned=keep_owned)
        self.stdout.write(
            self.style.SUCCESS(
                f"Meigen templates: {created} created, {updated} updated, "
                f"{len(seeds)} active, {skipped} skipped, {deactivated} deactivated."
            )
        )

    def _fetch(self, url: str, limit: int) -> tuple[list[dict], int]:
        seeds: list[dict] = []
        skipped = 0
        offset = 0
        while len(seeds) < limit:
            page = self._get_json(url, offset)
            items = page.get("images") or []
            if not items:
                break
            for item in items:
                if len(seeds) >= limit:
                    break
                seed = build_seed(item)
                if seed is None:
                    skipped += 1
                    continue
                seeds.append(seed)
            has_more = bool(page.get("hasMore"))
            offset += len(items)
            if not has_more:
                break
        return seeds, skipped

    def _get_json(self, url: str, offset: int) -> dict:
        params = {"sort": "featured", "limit": PAGE_SIZE, "offset": offset}
        last_error: Exception | None = None
        for attempt in range(1, REQUEST_RETRIES + 1):
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Unexpected meigen response shape.")
                return payload
            except Exception as exc:  # noqa: BLE001 - network retry loop
                last_error = exc
                self.stderr.write(f"  retry {attempt}/{REQUEST_RETRIES} for {url} offset={offset}: {exc}")
                time.sleep(REQUEST_DELAY * attempt * 2)
        raise CommandError(f"Could not fetch {url} offset={offset}: {last_error}")

    @staticmethod
    def _store(seeds: list[dict], *, keep_owned: bool) -> tuple[int, int, int]:
        created = 0
        updated = 0
        active_keys: set[str] = set()
        with transaction.atomic():
            for seed in seeds:
                config = seed["template_config"]
                seed_key = config["seedKey"]
                defaults = {
                    "title": seed["title"],
                    "category": seed["category"],
                    "format": seed["format"],
                    "is_video": seed["is_video"],
                    "preview_url": seed["preview_url"],
                    "template_config": config,
                    "uses_count": seed.get("uses_count") or 0,
                    "uses_last_7d": seed.get("uses_last_7d") or 0,
                    "is_active": True,
                }
                existing = Template.objects.filter(template_config__seedKey=seed_key).first()
                if existing is None:
                    Template.objects.create(**defaults)
                    created += 1
                else:
                    Template.objects.filter(id=existing.id).update(**defaults)
                    updated += 1
                active_keys.add(seed_key)

            qs = Template.objects.filter(is_active=True)
            if not keep_owned:
                # Replace everything not in this seed set (owned + stale meigen rows).
                qs = qs.exclude(template_config__seedKey__in=active_keys)
            else:
                # Only deactivate stale meigen rows; keep owned seeds untouched.
                qs = qs.filter(template_config__source="meigen").exclude(
                    template_config__seedKey__in=active_keys
                )
            deactivated = qs.update(is_active=False)
        return created, updated, deactivated