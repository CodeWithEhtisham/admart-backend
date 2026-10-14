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

from agents import hooks, providers, render
from agents.registry import IMAGE_HEIGHT, IMAGE_WIDTH, LENGTHS, STYLES, TONES, get_agent, voice_settings
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


class WaitUntil(Exception):
    """Put the run back in the queue until `when` (a scheduled post); the engine sets locked_until."""

    def __init__(self, when):
        super().__init__(when.isoformat())
        self.when = when


RESEARCH_PROMPT = """Research this topic for a short YouTube Short. Use web search if you have it. List 5-8
specific, surprising, verifiable facts and 2-3 angles that would make a strong hook. Only state facts
you are sure of: no made-up statistics or precise percentages; prefer well-known figures or none.
Plain bullet points, no intro, no markdown headings."""

TITLE_RULES = """at most 60 characters with the subject in the first 40, no hashtags, no hype words
  (amazing, insane, ultimate, secret...): use a number, a name or a date instead"""

CONCEPTS_PROMPT = f"""You are a YouTube Shorts producer. Propose exactly 3 clearly different concepts for
a vertical Short on the topic, grounded in the research notes.
Return JSON only: {{"concepts": [{{"title": string, "formula": string, "hooks": [string, string, string],
"angle": string, "style": string}}]}}
- title: {TITLE_RULES}.
- formula: the name of one hook formula below. The 3 concepts use different formulas.
- hooks: 3 versions of the first spoken line, built on that formula, 9-24 words each. A hook confirms
  what the title promises, opens a question the viewer cannot close yet, and talks to "you". Specific
  beats big. Never open with a greeting, who you are or a subscribe pitch.
- angle: one sentence on the approach (e.g. countdown, myth vs fact, story, how-to).
- style: one of: cinematic, photoreal, illustration, anime, minimal.
Hook formulas (name: shape):
""" + "\n".join(f"- {name}: {shape}" for name, shape in hooks.FORMULAS)

SCRIPT_PROMPT = f"""You write scripts for YouTube Shorts (vertical video, about 40-50 seconds).
Return JSON only, in this shape:
{{"title": string, "thumbnail_text": string, "description": string, "tags": [string],
 "scenes": [{{"narration": string, "visual": "stock" | "image", "stock_query": string, "image_prompt": string}}]}}
Rules:
- 4 to 7 scenes. Scene 1 opens with the concept's hook, word for word, if one is given. The first
  sentence confirms what the title promises.
- No greeting, channel intro or subscribe pitch. One idea per scene. Deliver the payoff the hook
  promised, clearly. End on one short line that loops back to the opening (so the Short replays
  smoothly) or on a single ask, never several.
- Total narration within the word limit given (100 words if none), plain spoken language, no stage
  directions or emojis.
- Use facts from the research notes when given; never invent statistics.
- visual: "stock" when real-world footage fits (people, places, nature, food, cities, objects in use);
  "image" for anything abstract, historical, fantastical or hard to film.
- stock_query: 2-4 plain English words to search stock video for that scene.
- image_prompt: always required, also for stock scenes (used when no clip is found): one vivid
  picture for that scene, vertical 9:16 framing. Never ask for text,
  letters, captions or logos in the image.
- title: {TITLE_RULES}. description: 2-3 sentences ending with #Shorts.
- thumbnail_text: 2-4 punchy words for the thumbnail that add to the title; never repeat its words.
- tags: up to 12 short tags without the # sign.
- Write in the tone given; if there is none, use the brand tone."""


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


DEFAULT_PROMPTS = {"research": RESEARCH_PROMPT, "concepts": CONCEPTS_PROMPT, "script": SCRIPT_PROMPT}


def _prompt(run, key: str) -> str:
    """The recipe's prompt for this step, or the built-in one when the recipe leaves it blank."""
    spec = get_agent(run.deployment.agent_type)
    custom = (spec.prompts.get(key) or "").strip() if spec else ""
    return custom or DEFAULT_PROMPTS[key]


TOPIC_PROMPT = """You plan a YouTube Shorts channel. Suggest ONE fresh topic for the next 45-second Short.
It must fit the channel niche, be specific and curiosity-driven, and must not repeat or closely
resemble the recent topics listed. Return JSON only: {"topic": string} (at most 80 characters)."""


def _topic(run) -> str:
    """The run's topic. Autopilot runs with an empty topic queue pick one from the niche (once)."""
    topic = str(run.input.get("topic", "")).strip()
    if topic or not run.input.get("auto"):
        return topic
    recent = [
        str(r.input.get("topic", ""))
        for r in run.deployment.runs.exclude(id=run.id).order_by("-created_at")[:15]
        if r.input.get("topic")
    ]
    niche = str(_config(run).get("niche") or "").strip()
    if settings.AGENTS_DRY_RUN:
        topic = f"{niche or 'Interesting facts'} #{len(recent) + 1}"
    else:
        raw = providers.text(TOPIC_PROMPT, f"{_brand_lines(run)}Recent topics:\n" + "\n".join(f"- {t}" for t in recent))
        topic = " ".join(str(raw.get("topic") or "").split())[:200]
        if not topic:
            raise RuntimeError("The agent couldn't pick a topic. Please try again.")
    run.input["topic"] = topic
    run.save(update_fields=["input", "updated_at"])
    return topic


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


def _style_lines(run) -> str:
    """Tone and length the user picked for this agent."""
    config = _config(run)
    tone = TONES.get(config.get("tone"))
    seconds = config.get("length") if config.get("length") in LENGTHS else 45
    return (f"Tone: {tone[1]}\n" if tone else "") + f"Length: about {seconds} seconds, at most {LENGTHS[seconds]} words of narration\n"


# ── pre-production ────────────────────────────────────────────────────────


def step_research(run) -> None:
    if "research" in run.output:
        return
    topic = _topic(run)
    if settings.AGENTS_DRY_RUN:
        notes, sources = f"- Dry run: research notes about {topic} would appear here.", []
    else:
        notes, sources = providers.text(_prompt(run, "research"), f"Topic: {topic}\n{_brand_lines(run)}", json_mode=False, search=True)
    run.output["research"] = {"notes": (notes or "").strip()[:3000], "sources": sources}
    _save(run)


def scored_hook(hook: str) -> dict:
    """The hook with its score, band and the one fix that would help most."""
    return {"hook": hook, **{k: v for k, v in hooks.score_hook(hook).items() if k != "weakest"}}


def clean_concepts(raw: dict) -> list[dict]:
    """Bound the concepts, keep each one's best-scoring hook, best concept first."""
    concepts = []
    for item in (raw.get("concepts") or [])[:3]:
        if not isinstance(item, dict):
            continue
        options = item.get("hooks") if isinstance(item.get("hooks"), list) else [item.get("hook")]
        options = [" ".join(str(h or "").split())[:200] for h in options[:5]]
        options = [h for h in options if h]
        if not options:
            continue
        best = max((scored_hook(h) for h in options), key=lambda h: h["score"])
        style = str(item.get("style", "")).strip().lower()
        formula = str(item.get("formula") or "").strip()
        concepts.append(
            {
                "title": str(item.get("title") or "").strip()[:90],
                **best,
                "formula": formula if formula in hooks.FORMULA_NAMES else "",
                "angle": str(item.get("angle") or "").strip()[:300],
                "style": style if style in STYLES else "cinematic",
            }
        )
    concepts = [c for c in concepts if c["title"]]
    if not concepts:
        raise RuntimeError("No usable concepts came back. Please try again.")
    return sorted(concepts, key=lambda c: -c["score"])


def step_concepts(run) -> None:
    if run.output.get("concepts"):
        return
    topic = _topic(run)
    if settings.AGENTS_DRY_RUN:
        raw = {
            "concepts": [
                {"title": f"{topic}: {angle}", "hooks": [f"Here is {angle.lower()} about {topic}."], "angle": angle,
                 "style": style, "formula": "The List"}
                for angle, style in (("Countdown", "cinematic"), ("Myth vs fact", "illustration"), ("A short story", "photoreal"))
            ]
        }
    else:
        notes = run.output.get("research", {}).get("notes", "")
        raw = providers.text(_prompt(run, "concepts"), f"Topic: {topic}\n{_brand_lines(run)}\nResearch notes:\n{notes}")
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
        # Stock scenes still need a picture idea: it's used when no clip is found.
        prompt = " ".join(str(scene.get("image_prompt") or scene.get("stock_query") or narration).split())[:600]
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
    title = (str(raw.get("title") or "").strip() or topic)[:90]
    thumb = " ".join(str(raw.get("thumbnail_text") or "").split()[:4])[:40]
    return {
        "title": title,
        "thumbnail_text": thumb,
        "title_check": hooks.lint_title(title, thumb),
        "description": description,
        "tags": [str(t).strip().lstrip("#")[:60] for t in tags if str(t).strip()][:12],
        "scenes": scenes,
    }


def step_script(run) -> None:
    if run.output.get("scenes"):
        return
    topic = _topic(run)
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
        raw = providers.text(
            _prompt(run, "script"), f"Topic: {topic}\n{_brand_lines(run)}{_style_lines(run)}{concept_lines}Research notes:\n{notes}"
        )
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
            voice, speed = voice_settings(_config(run))
            (folder / name).write_bytes(providers.speech(scene["narration"], voice, speed))
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
        providers.note("pexels")
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


def highlight(run) -> str:
    """The brand colour for captions and the thumbnail box."""
    colors = (run.project.brand_settings or {}).get("colors") or []
    return (colors[0]["hex"] if colors and isinstance(colors[0], dict) else run.project.brand_color_hex) or "#FFD400"


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
    music = _music_track(run)
    workdir = folder / "work"
    try:
        result = render.render_short(
            scenes,
            folder / "short.mp4",
            folder / "thumb.jpg",
            workdir,
            title=run.output.get("thumbnail_text") or run.output.get("title", ""),
            highlight_hex=highlight(run),
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
        width=out.get("width") or render.WIDTH,
        height=out.get("height") or render.HEIGHT,
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
