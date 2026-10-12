"""Agent steps. Each stores its result in run.output and is skipped if already done,
so a run that stopped half-way (restart, crash, approval pause) resumes without
paying twice. Gate steps raise NeedsReview to pause for a person."""

from __future__ import annotations

import hashlib
import logging
import shutil
import time
from pathlib import Path

import requests
from django.conf import settings

from agents import providers, render
from agents.registry import IMAGE_HEIGHT, IMAGE_WIDTH, STYLES
from content.models import LibraryAsset
from content.storage_utils import absolute_media_url

logger = logging.getLogger(__name__)

PLACEHOLDER_COLORS = ("0x2563eb", "0x7c3aed", "0x059669", "0xdb2777", "0xd97706", "0x0891b2", "0x4b5563")
SPEECH_WORDS_PER_SECOND = 2.6
MAX_STOCK_BYTES = 80 * 1024 * 1024
MUSIC_SUFFIXES = (".mp3", ".m4a", ".wav")


class NeedsReview(Exception):
    """Pause the run at a gate until a person approves (agents.views 'continue')."""

    def __init__(self, gate: str):
        super().__init__(gate)
        self.gate = gate


RESEARCH_PROMPT = """Research this topic for a 45-second YouTube Short. Using web search, list 5-8
specific, surprising, verifiable facts or data points (with numbers where possible) and 2-3 angles
that would make a strong hook. Plain bullet points, no intro, no markdown headings."""

CONCEPTS_PROMPT = """You are a YouTube Shorts producer. Propose exactly 3 clearly different concepts for
a vertical Short (about 45 seconds) on the topic, grounded in the research notes.
Return JSON only: {"concepts": [{"title": string, "hook": string, "angle": string, "style": string}]}
- title: at most 90 characters, no hashtags.
- hook: the first spoken line, under 15 words, that stops the scroll.
- angle: one sentence on the approach (e.g. countdown, myth vs fact, story, how-to).
- style: one of: cinematic, photoreal, illustration, anime, minimal."""

SCRIPT_PROMPT = """You write scripts for YouTube Shorts (vertical video, about 40-50 seconds).
Return JSON only, in this shape:
{"title": string, "description": string, "tags": [string],
 "scenes": [{"narration": string, "visual": "stock" | "image", "stock_query": string, "image_prompt": string}]}
Rules:
- 4 to 7 scenes. Scene 1 opens with the concept's hook if one is given.
- Total narration at most 130 words, plain spoken language, no stage directions or emojis.
- Use facts from the research notes when given; never invent statistics.
- visual: "stock" when real-world footage fits (people, places, nature, food, cities, objects in use);
  "image" for anything abstract, historical, fantastical or hard to film.
- stock_query: 2-4 plain English words to search stock video for that scene.
- image_prompt: one vivid picture for that scene, vertical 9:16 framing. Never ask for text,
  letters, captions or logos in the image.
- title: at most 90 characters, no hashtags. description: 2-3 sentences ending with #Shorts.
- tags: up to 12 short tags without the # sign.
- If a brand tone is given, write in that tone."""


def media_dir(run) -> tuple[Path, str]:
    """Absolute folder and MEDIA-relative prefix for a run's files."""
    rel = f"projects/{run.project_id}/agents/{run.id}"
    path = Path(settings.MEDIA_ROOT) / rel
    path.mkdir(parents=True, exist_ok=True)
    return path, rel


def media_path(rel: str) -> Path:
    return Path(settings.MEDIA_ROOT) / rel


def _save(run, fields=("output",)):
    run.save(update_fields=[*fields, "updated_at"])


def _config(run) -> dict:
    return run.deployment.config or {}


def _checkpoints(run) -> bool:
    """Pause at concept/script/storyboard unless the user chose 'final review only'."""
    return _config(run).get("checkpoints", "all") != "final"


def _brand_lines(run) -> str:
    project = run.project
    brand = project.brand_settings or {}
    return (
        f"Channel niche: {str(_config(run).get('niche') or 'none')[:300]}\n"
        f"Brand: {project.brand_name or 'none'}\n"
        f"Industry: {project.brand_industry or 'none'}\n"
        f"Brand tone: {str(brand.get('toneText') or 'none')[:600]}\n"
    )


# ── pre-production ────────────────────────────────────────────────────────


def step_research(run) -> None:
    if "research" in run.output:
        return
    topic = str(run.input.get("topic", "")).strip()
    if settings.AGENTS_DRY_RUN:
        notes, sources = f"- Dry run: research notes about {topic} would appear here.", []
    else:
        notes, sources = providers.text(RESEARCH_PROMPT, f"Topic: {topic}\n{_brand_lines(run)}", json_mode=False, search=True)
    run.output["research"] = {"notes": (notes or "").strip()[:3000], "sources": sources}
    _save(run)


def clean_concepts(raw: dict) -> list[dict]:
    concepts = []
    for item in (raw.get("concepts") or [])[:3]:
        if not isinstance(item, dict):
            continue
        style = str(item.get("style", "")).strip().lower()
        concepts.append(
            {
                "title": str(item.get("title") or "").strip()[:90],
                "hook": str(item.get("hook") or "").strip()[:200],
                "angle": str(item.get("angle") or "").strip()[:300],
                "style": style if style in STYLES else "cinematic",
            }
        )
    concepts = [c for c in concepts if c["title"] and c["hook"]]
    if not concepts:
        raise RuntimeError("No usable concepts came back. Please try again.")
    return concepts


def step_concepts(run) -> None:
    if run.output.get("concepts"):
        return
    topic = str(run.input.get("topic", "")).strip()
    if settings.AGENTS_DRY_RUN:
        raw = {
            "concepts": [
                {"title": f"{topic}: {angle}", "hook": f"Here is {angle.lower()} about {topic}.", "angle": angle,
                 "style": style}
                for angle, style in (("Countdown", "cinematic"), ("Myth vs fact", "illustration"), ("A short story", "photoreal"))
            ]
        }
    else:
        notes = run.output.get("research", {}).get("notes", "")
        raw = providers.text(CONCEPTS_PROMPT, f"Topic: {topic}\n{_brand_lines(run)}\nResearch notes:\n{notes}")
    run.output["concepts"] = clean_concepts(raw)
    _save(run)


def step_pick_concept(run) -> None:
    if run.output.get("concept"):
        return
    if not _checkpoints(run):
        run.output["concept"] = run.output["concepts"][0]
        _save(run)
        return
    raise NeedsReview("concept")


def clean_script(raw: dict, topic: str) -> dict:
    """Bound and normalise a script (LLM or user-edited); reject one that can't make a Short."""
    scenes = []
    for scene in raw.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        narration = " ".join(str(scene.get("narration") or "").split())[:400]
        prompt = " ".join(str(scene.get("image_prompt") or "").split())[:600]
        if narration and prompt:
            scenes.append(
                {
                    "narration": narration,
                    "image_prompt": prompt,
                    "visual": "stock" if scene.get("visual") == "stock" else "image",
                    "stock_query": " ".join(str(scene.get("stock_query") or "").split())[:60],
                }
            )
    scenes = scenes[:7]
    if len(scenes) < 3:
        raise RuntimeError("The script needs at least 3 scenes with narration and an image idea.")
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = tags.split(",")
    description = str(raw.get("description") or "").strip()[:4900]
    if "#shorts" not in description.lower():
        description = f"{description} #Shorts".strip()
    return {
        "title": (str(raw.get("title") or "").strip() or topic)[:90],
        "description": description,
        "tags": [str(t).strip().lstrip("#")[:60] for t in tags if str(t).strip()][:12],
        "scenes": scenes,
    }


def step_script(run) -> None:
    if run.output.get("scenes"):
        return
    topic = str(run.input.get("topic", "")).strip()
    concept = run.output.get("concept") or {}
    if settings.AGENTS_DRY_RUN:
        raw = {
            "title": (concept.get("title") or topic)[:90],
            "description": f"A quick look at {topic}. #Shorts",
            "tags": ["shorts", "dryrun"],
            "scenes": [
                {"narration": f"Scene {i + 1}: here is something about {topic}.", "image_prompt": f"{topic}, scene {i + 1}",
                 "visual": "image", "stock_query": topic}
                for i in range(4)
            ],
        }
    else:
        notes = run.output.get("research", {}).get("notes", "")
        concept_lines = (
            f"Concept title: {concept.get('title', '')}\nHook: {concept.get('hook', '')}\nAngle: {concept.get('angle', '')}\n"
            if concept
            else ""
        )
        raw = providers.text(SCRIPT_PROMPT, f"Topic: {topic}\n{_brand_lines(run)}{concept_lines}Research notes:\n{notes}")
    run.output.update(clean_script(raw, topic))
    _save(run)


def step_review_script(run) -> None:
    if run.output.get("script_ok"):
        return
    if not _checkpoints(run):
        run.output["script_ok"] = True
        _save(run)
        return
    raise NeedsReview("script")


# ── voice + timings ───────────────────────────────────────────────────────


def step_voice(run) -> None:
    folder, rel = media_dir(run)
    if not run.output.get("scenes"):  # Voiceover agent: the input text is one scene
        run.output["scenes"] = [{"narration": " ".join(str(run.input.get("text", "")).split())}]
    for i, scene in enumerate(run.output["scenes"]):
        if scene.get("audio"):
            continue
        name = f"voice-{i}.mp3"
        if settings.AGENTS_DRY_RUN:
            seconds = max(1.5, len(scene["narration"].split()) / SPEECH_WORDS_PER_SECOND)
            render.silent_audio(folder / name, seconds)
        else:
            (folder / name).write_bytes(providers.speech(scene["narration"]))
        scene["audio"] = f"{rel}/{name}"
        scene["duration"] = round(render.duration_of(folder / name), 3)
        _save(run)


def step_captions(run) -> None:
    """Word timings per scene: real ones from transcription, or an even estimate."""
    for scene in run.output["scenes"]:
        if "words" in scene:
            continue
        words = None if settings.AGENTS_DRY_RUN else providers.word_times(media_path(scene["audio"]))
        scene["words"] = words or render.estimate_word_times(scene["narration"], scene["duration"])
        _save(run)


# ── visuals ───────────────────────────────────────────────────────────────


def step_visuals(run) -> None:
    folder, rel = media_dir(run)
    concept_style = (run.output.get("concept") or {}).get("style")
    style = _config(run).get("style") or concept_style or "cinematic"
    style_hint = STYLES.get(style, STYLES["cinematic"])[1]
    use_stock = bool(settings.PEXELS_API_KEY) and not settings.AGENTS_DRY_RUN and _config(run).get("stock", True)
    for i, scene in enumerate(run.output["scenes"]):
        if scene.get("image") or scene.get("clip"):
            continue
        if use_stock and scene.get("visual") == "stock" and scene.get("stock_query"):
            found = _pexels_clip(scene["stock_query"], scene.get("duration", 4))
            if found:
                content, credit = found
                name = f"clip-{i}.mp4"
                (folder / name).write_bytes(content)
                scene.update({"clip": f"{rel}/{name}", "credit": credit})
                _save(run)
                continue
        if settings.AGENTS_DRY_RUN:
            name = f"scene-{i}.png"
            render.placeholder_image(folder / name, PLACEHOLDER_COLORS[i % len(PLACEHOLDER_COLORS)])
        else:
            content, ext = providers.image(f"{scene['image_prompt']}. Style: {style_hint}", IMAGE_WIDTH, IMAGE_HEIGHT)
            name = f"scene-{i}-{int(time.time())}{ext}"  # new name per take so browsers don't show a cached one
            (folder / name).write_bytes(content)
        scene.update({"image": f"{rel}/{name}", "clip": None, "credit": None})
        _save(run)  # after every scene, so a restart doesn't pay for it again


def _pexels_clip(query: str, min_seconds: float) -> tuple[bytes, dict] | None:
    """A portrait stock clip for the query, or None (then an AI image is used)."""
    try:
        response = requests.get(
            "https://api.pexels.com/videos/search",
            params={"query": query, "orientation": "portrait", "size": "medium", "per_page": 10},
            headers={"Authorization": settings.PEXELS_API_KEY},
            timeout=20,
        )
        response.raise_for_status()
        videos = response.json().get("videos") or []
    except (requests.RequestException, ValueError):
        logger.warning("Pexels search failed for %r", query, exc_info=True)
        return None
    # Prefer clips long enough to cover the narration; shorter ones are looped by the renderer.
    for video in sorted(videos, key=lambda v: (v.get("duration", 0) < min_seconds, -v.get("duration", 0))):
        files = [
            f for f in video.get("video_files") or []
            if f.get("file_type") == "video/mp4" and (f.get("height") or 0) >= 1280 and (f.get("height") or 0) > (f.get("width") or 0)
        ]
        if not files:
            continue
        best = min(files, key=lambda f: abs((f.get("height") or 0) - render.HEIGHT))
        try:
            clip = requests.get(best["link"], timeout=120)
            clip.raise_for_status()
        except requests.RequestException:
            continue
        if len(clip.content) > MAX_STOCK_BYTES:
            continue
        user = video.get("user") or {}
        return clip.content, {"source": "Pexels", "by": str(user.get("name", ""))[:80], "url": str(video.get("url", ""))[:300]}
    return None


def step_review_storyboard(run) -> None:
    if run.output.get("storyboard_ok"):
        return
    if not _checkpoints(run):
        run.output["storyboard_ok"] = True
        _save(run)
        return
    raise NeedsReview("storyboard")


# ── edit + finish ─────────────────────────────────────────────────────────


def _music_track(run) -> Path | None:
    if not _config(run).get("music", True):
        return None
    folder = Path(settings.AGENTS_MUSIC_DIR)
    tracks = sorted(p for p in folder.glob("*") if p.suffix.lower() in MUSIC_SUFFIXES) if folder.is_dir() else []
    if not tracks:
        return None
    index = int(hashlib.sha256(str(run.id).encode()).hexdigest(), 16) % len(tracks)  # stable per run
    return tracks[index]


def step_render(run) -> None:
    if run.output.get("video"):
        return
    folder, rel = media_dir(run)
    scenes = [
        {
            "kind": "clip" if s.get("clip") else "image",
            "path": media_path(s.get("clip") or s["image"]),
            "audio": media_path(s["audio"]),
            "duration": s["duration"],
            "words": s["words"],
        }
        for s in run.output["scenes"]
    ]
    colors = (run.project.brand_settings or {}).get("colors") or []
    highlight = colors[0]["hex"] if colors and isinstance(colors[0], dict) else run.project.brand_color_hex
    music = _music_track(run)
    workdir = folder / "work"
    try:
        result = render.render_short(
            scenes,
            folder / "short.mp4",
            folder / "thumb.jpg",
            workdir,
            title=run.output.get("title", ""),
            highlight_hex=highlight or "#FFD400",
            music=music,
            expect_sound=not settings.AGENTS_DRY_RUN,
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    credits = sorted({c["by"] for s in run.output["scenes"] if (c := s.get("credit")) and c.get("by")})
    if credits and "Pexels" not in run.output.get("description", ""):
        run.output["description"] = f"{run.output['description']}\n\nStock footage: {', '.join(credits)} via Pexels."[:5000]
    run.output.update(
        {
            "video": f"{rel}/short.mp4",
            "thumbnail": f"{rel}/thumb.jpg",
            "duration": result["duration"],
            "checks": result["checks"],
            "music": music.name if music else None,
        }
    )
    _save(run)


def step_finish(run) -> None:
    """Put the finished video in the project library (once)."""
    if run.library_asset_id:
        return
    out = run.output
    asset = LibraryAsset.objects.create(
        project_id=run.project_id,
        user_id=run.user_id,
        media_type="video",
        title=out.get("title", "")[:255],
        status="ready",
        source_url=absolute_media_url(out["video"]),
        thumbnail_url=absolute_media_url(out["thumbnail"]),
        prompt=out.get("description", ""),
        model=f"agent:{run.deployment.agent_type}",
        capability="agent",
        duration_seconds=round(out.get("duration") or 0),
        width=render.WIDTH,
        height=render.HEIGHT,
    )
    run.library_asset = asset
    _save(run, fields=("library_asset",))


STEPS = {
    "research": step_research,
    "concepts": step_concepts,
    "pick_concept": step_pick_concept,
    "script": step_script,
    "review_script": step_review_script,
    "voice": step_voice,
    "captions": step_captions,
    "visuals": step_visuals,
    "review_storyboard": step_review_storyboard,
    "render": step_render,
    "finish": step_finish,
}
