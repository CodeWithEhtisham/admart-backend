"""Fetch featured templates from the meigen.ai public gallery into the Template model.

Usage:
    python manage.py fetch_meigen_templates                 # 200 images + 100 videos
    python manage.py fetch_meigen_templates --images 5 --videos 5 --dry-run
    python manage.py fetch_meigen_templates --keep-owned    # keep owned seeds active
"""

from __future__ import annotations

import math
import difflib
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

# Meigen's API only honours a couple of its category slugs (verified: ``logo``
# and ``wallpaper`` return different items, every other slug returns the plain
# featured feed). We still request the working ones so those sections fill up
# properly; the rest of the gallery is classified locally by keyword score.
# (meigen slug -> category override). Only these slugs actually filter on the
# API; everything else is filled from the default feed + local classification.
CATEGORY_HARVEST_SOURCES = (
    ("logo", "brand-logo"),
    ("wallpaper", "wallpaper"),
    ("product", "ads-product"),
    ("poster", "posters-visuals"),
)
CATEGORY_HARVEST_LIMIT = 40  # per category source

# Near-duplicate titles collapse: meigen often lists the same prompt as several
# items (tiny wording/spacing differences). Similarity threshold for treating
# two normalized titles as the same template.
DUP_TITLE_RATIO = 0.93

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

PLACEHOLDER_RE = re.compile(r"\[([^\[\]\n]{1,60})\]")
MIN_PROMPT_LENGTH = 20

# meigen item ids (as seedKeys) that were reviewed and flagged as vulgar content.
VULGAR_SEED_KEYS = frozenset({
    "meigen:2067731526448738460",
    "meigen:2057687680016908379",
    "meigen:2033917202567446610",
})

# Narrow keyword filter for clearly explicit content. Terms like "nude" alone are
# skipped on purpose: they appear in harmless contexts (nude lips/palette).
VULGAR_CONTENT_RE = re.compile(
    r"\b(?:lingerie|boudoir|topless|striptease|stripper|thong|g-?string|"
    r"sexually suggestive|explicit|erotic|pornographic|nsfw|onlyfans)\b"
    r"|\b(?:nude|naked|topless)\s+(?:woman|women|girl|model|body|torso|figure)\b",
    re.IGNORECASE,
)

# Keyword scoring used to mirror meigen.ai's own category sections
# (?category=logo, ?category=ads-product, …). Their public API ignores the
# category param, so we classify with the same signals their site uses.
MEIGEN_CATEGORY_KEYWORDS = {
    "brand-logo": (
        (("brand", 3), ("logo", 4), ("monogram", 4), ("wordmark", 4), ("letterhead", 3),
         ("business card", 3), ("stationery", 2), ("emblem", 3), ("mascot logo", 4),
         ("branding", 3), ("identity design", 3), ("badge", 1)),
    ),
    "illustration-3d": (
        (("3d", 3), ("3d render", 4), ("illustration", 3), ("vector", 2), ("claymorphism", 4),
         ("clay style", 4), ("isometric", 3), ("blender", 3), ("octane render", 3),
         ("cartoon", 2), ("flat design", 2), ("low poly", 4), ("cgi", 3)),
    ),
    "posters-visuals": (
        (("poster", 4), ("flyer", 3), ("billboard", 3), ("typography", 2), ("album cover", 3),
         ("book cover", 3), ("event promo", 3), ("print ad", 3), ("movie poster", 4),
         ("visual identity", 2), ("packaging", 2), ("label design", 2)),
    ),
    "portraits": (
        (("portrait", 4), ("headshot", 4), ("profile picture", 3), ("selfie", 3),
         ("face closeup", 4), ("facial", 3), ("professional photo of a woman", 2),
         ("professional photo of a man", 2), ("studio portrait", 4), ("head shot", 4)),
    ),
    "storyboard-characters": (
        (("storyboard", 5), ("character sheet", 5), ("character design", 5), ("character concept", 4),
         ("turnaround", 4), ("mascot character", 4), ("comic panel", 4), ("sequential art", 4),
         ("expression sheet", 5), ("anime character", 4)),
    ),
    "wallpaper": (
        (("wallpaper", 5), ("desktop background", 5), ("phone wallpaper", 5), ("4k background", 4),
         ("seamless pattern", 3), ("abstract background", 3), ("minimal background", 3),
         ("texture background", 3)),
    ),
    # Default bucket: promo/ads/product/marketing content — matches meigen's
    # "Ads & Product" section, the largest one on the site.
    "ads-product": (
        (("ad", 2), ("advert", 3), ("advertisement", 3), ("commercial", 2), ("product", 2),
         ("promo", 3), ("sale", 2), ("discount", 2), ("offer", 2), ("campaign", 2),
         ("marketing", 2), ("cta", 2), ("instagram", 1), ("social media post", 3),
         ("product photography", 4), ("product shot", 4), ("ecommerce", 3), ("landing page", 2),
         ("banner", 2), ("restaurant", 1), ("menu", 1), ("gym", 1), ("real estate", 2)),
    ),
}

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


def normalize_title(raw: str) -> str:
    """Lowercase and strip every non-letter/digit (Unicode-aware, keeps CJK)."""
    return re.sub(r"[\W_]+", "", (raw or "").lower())


def titles_similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    if a == b:
        return True
    la, lb = len(a), len(b)
    if min(la, lb) / max(la, lb) < 0.85:
        return False
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return matcher.real_quick_ratio() >= DUP_TITLE_RATIO and matcher.ratio() >= DUP_TITLE_RATIO


def dedupe_seeds_by_title(seeds: list[dict]) -> tuple[list[dict], int]:
    """Drop seeds whose title is (near-)identical to one already kept."""
    kept: list[dict] = []
    kept_titles: list[str] = []
    dropped = 0
    for seed in seeds:
        norm = normalize_title(seed["title"])
        if any(titles_similar(norm, existing) for existing in kept_titles):
            dropped += 1
            continue
        kept_titles.append(norm)
        kept.append(seed)
    return kept, dropped


def infer_meigen_category(item: dict, is_video: bool) -> str:
    """Map a meigen item onto one of meigen's own site category slugs.

    The meigen API ignores its ``category`` query param (verified: the same
    items come back for every category), so their site classifies client-side.
    We mirror that with a keyword score over title + prompt. Videos always go
    to the "Videos" section, like the meigen site does.
    """
    if is_video:
        return "video"
    haystack = f"{(item.get('title') or '')}\n{(item.get('prompt') or '')}".lower()
    scores = {}
    for slug, groups in MEIGEN_CATEGORY_KEYWORDS.items():
        score = 0
        for group in groups:
            # Tolerate either a flat ((kw, w), …) tuple or a nested one.
            pairs = group if group and isinstance(group[0], tuple) else (group,)
            for keyword, weight in pairs:
                if keyword in haystack:
                    score += weight
        if score:
            scores[slug] = score
    if not scores:
        return "ads-product"
    best = max(scores.items(), key=lambda pair: (pair[1], pair[0]))
    return best[0]


def build_seed(item: dict, category_override: str | None = None) -> dict | None:
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

    if f"meigen:{meigen_id}" in VULGAR_SEED_KEYS or VULGAR_CONTENT_RE.search(
        f"{title}\n{prompt}"
    ):
        return None
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

    category = category_override or infer_meigen_category(item, is_video)

    return {
        "id": f"meigen-{meigen_id}",
        "title": title,
        "category": category,
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
        parser.add_argument("--images", type=int, default=300)
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
        seen_ids: set[str] = set()

        # Note: all videos are forced into the "video" category by the
        # classifier, so category harvests only make sense for images.
        sources: list[tuple[str, str | None, int]] = [
            (MEIGEN_IMAGES_URL, None, image_count),
            (MEIGEN_VIDEOS_URL, None, video_count),
        ]
        if image_count:
            sources.extend(
                (MEIGEN_IMAGES_URL, slug, CATEGORY_HARVEST_LIMIT)
                for slug in CATEGORY_HARVEST_SOURCES
            )
        for url, category, limit in sources:
            if not limit:
                continue
            source_seeds, source_skipped = self._fetch(
                url, limit, category=category, seen_ids=seen_ids
            )
            seeds.extend(source_seeds)
            skipped += source_skipped

        seeds, title_dupes = dedupe_seeds_by_title(seeds)
        skipped += title_dupes

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
        by_category: dict[str, int] = {}
        for seed in seeds:
            by_category[seed["category"]] = by_category.get(seed["category"], 0) + 1
        breakdown = ", ".join(f"{slug}={n}" for slug, n in sorted(by_category.items()))
        self.stdout.write(
            self.style.SUCCESS(
                f"Meigen templates: {created} created, {updated} updated, "
                f"{len(seeds)} active, {skipped} skipped, {deactivated} deactivated. "
                f"Categories: {breakdown}"
            )
        )

    def _fetch(
        self,
        url: str,
        limit: int,
        *,
        category: str | None = None,
        seen_ids: set[str] | None = None,
    ) -> tuple[list[dict], int]:
        seeds: list[dict] = []
        skipped = 0
        offset = 0
        while len(seeds) < limit:
            page = self._get_json(url, offset, category=category)
            items = page.get("images") or []
            if not items:
                break
            for item in items:
                if len(seeds) >= limit:
                    break
                meigen_id = str(item.get("id") or "")
                if meigen_id and seen_ids is not None:
                    if meigen_id in seen_ids:
                        skipped += 1
                        continue
                    seen_ids.add(meigen_id)
                seed = build_seed(item, category_override=category)
                if seed is None:
                    skipped += 1
                    continue
                seeds.append(seed)
            has_more = bool(page.get("hasMore"))
            offset += len(items)
            if not has_more:
                break
        return seeds, skipped

    def _get_json(self, url: str, offset: int, *, category: str | None = None) -> dict:
        params = {"sort": "featured", "limit": PAGE_SIZE, "offset": offset}
        if category:
            params["category"] = category
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
                    "is_active": True,
                }
                existing = Template.objects.filter(template_config__seedKey=seed_key).first()
                if existing is None:
                    defaults["uses_count"] = seed.get("uses_count") or 0
                    defaults["uses_last_7d"] = seed.get("uses_last_7d") or 0
                    Template.objects.create(**defaults)
                    created += 1
                else:
                    # Never clobber real usage counters with the (always zero)
                    # values meigen reports — only set them on create.
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