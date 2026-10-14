"""Agent catalog.

Agents are *recipes* stored in the database (AgentRecipe) and editable in the admin dashboard:
which step blocks run in which order, the AI prompts, and how the agent is presented. The
three built-in recipes below seed the table and are the fallback if a row is missing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings

from content.pricing import FALLBACK_PRICES, admart_markup_multiplier, get_fal_prices, quantize_credits

SHORT_SCENES = 6
SHORT_NARRATION_CHARS = 900  # ~130 words: the longest (60 s) Short, for cost quotes
IMAGE_WIDTH, IMAGE_HEIGHT = 768, 1344  # 9:16, about 1 megapixel; rendered up to 1080x1920
MAX_TEXT_INPUT = 3000
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,48}$")

# Visual style presets: applied to every image prompt of a Short.
STYLES = {
    "cinematic": ("Cinematic", "cinematic film still, dramatic lighting, shallow depth of field, rich colour grade"),
    "photoreal": ("Photoreal", "photorealistic, natural light, sharp detail, editorial photography"),
    "illustration": ("Flat illustration", "flat vector illustration, bold simple shapes, clean bright colours"),
    "anime": ("Anime", "anime style, clean line art, cel shading, vibrant colours"),
    "minimal": ("Minimal", "minimalist composition, soft pastel palette, lots of negative space"),
}
# Narrator voices: id -> (label, Kokoro voice on fal). British voices use fal's British endpoint.
VOICES = {
    "heart": ("Heart: warm female, US", "af_heart"),
    "bella": ("Bella: bright female, US", "af_bella"),
    "michael": ("Michael: friendly male, US", "am_michael"),
    "fenrir": ("Fenrir: deep male, US", "am_fenrir"),
    "emma": ("Emma: female, UK", "bf_emma"),
    "george": ("George: male, UK", "bm_george"),
}
PACES = {"calm": ("Calm", 0.9), "normal": ("Normal", 1.0), "fast": ("Fast", 1.12)}
TONES = {
    "fun": ("Fun", "playful and funny, light jokes"),
    "educational": ("Educational", "clear and informative, like a good teacher"),
    "story": ("Storytelling", "a gripping story that builds suspense"),
    "calm": ("Calm", "calm, warm and soothing"),
    "motivational": ("Motivational", "energetic and motivational"),
}
LENGTHS = {30: 65, 45: 100, 60: 130}  # seconds -> most narration words (narrators speak ~2.2 words/s)


def voice_settings(config: dict) -> tuple[tuple, float]:
    """(VOICES entry, speed) for a deployment config; unknown values fall back to the defaults."""
    return VOICES.get(config.get("voice"), VOICES["heart"]), PACES.get(config.get("pace"), PACES["normal"])[1]


# Pause points where a person approves before money is spent on the next stage.
GATES = {"pick_concept": "concept", "review_script": "script", "review_storyboard": "storyboard",
         "review_edit": "edit"}

# Video Editor choices (per agent, set when starting it or in Settings).
FORMATS = {  # id -> (label, output size or None to keep the original shape)
    "9:16": ("Vertical 9:16 · Reels, Shorts, TikTok", (1080, 1920)),
    "1:1": ("Square 1:1 · feed posts", (1080, 1080)),
    "4:5": ("Portrait 4:5 · Instagram & Facebook feed", (1080, 1350)),
    "original": ("Keep original shape", None),
}
CUT_STYLES = {  # id -> (label, cut pauses longer than this many seconds)
    "gentle": ("Gentle · only long pauses", 1.0),
    "normal": ("Normal · pauses, um/uh, restarts", 0.6),
    "tight": ("Tight · fast, punchy pace", 0.35),
}
AUDIO_LEVELS = {  # id -> (label, fal model or None for FFmpeg on our server, USD per minute)
    "basic": ("Basic · free noise filter", None, "0"),
    "standard": ("Standard · clean studio voice", "veed/clean-audio", "0.0125"),
    "studio": ("Studio · strongest voice isolation", "fal-ai/elevenlabs/audio-isolation", "0.10"),
}
MAX_VIDEO_SECONDS = 180


def video_settings(config: dict) -> tuple[str, str, str]:
    """(format, cut style, audio level) ids for a deployment config, with defaults."""
    config = config or {}
    return (
        config.get("format") if config.get("format") in FORMATS else "9:16",
        config.get("cut") if config.get("cut") in CUT_STYLES else "normal",
        config.get("audio") if config.get("audio") in AUDIO_LEVELS else "standard",
    )

# Step blocks a recipe can use, and what each needs earlier in the recipe.
STEP_BLOCKS = {
    "research": {"label": "Research the topic (web search)", "needs": []},
    "concepts": {"label": "Propose 3 concepts", "needs": []},
    "pick_concept": {"label": "Check-in: user picks a concept", "needs": ["concepts"]},
    "script": {"label": "Write the script", "needs": []},
    "review_script": {"label": "Check-in: user edits the script", "needs": ["script"]},
    "voice": {"label": "Record the voice", "needs": []},
    "captions": {"label": "Time the captions", "needs": ["voice"]},
    "visuals": {"label": "Make visuals (stock video / AI images)", "needs": ["script"]},
    "review_storyboard": {"label": "Check-in: user reviews the storyboard", "needs": ["visuals"]},
    "render": {"label": "Edit the video", "needs": ["voice", "captions", "visuals"]},
    "prepare": {"label": "Check the uploaded video", "needs": []},
    "transcribe": {"label": "Transcribe it word by word", "needs": ["prepare"]},
    "clean_audio": {"label": "Clean up the audio", "needs": ["prepare"]},
    "plan_edit": {"label": "Plan the cuts and caption fixes", "needs": ["transcribe", "clean_audio"]},
    "review_edit": {"label": "Check-in: user reviews the cuts", "needs": ["plan_edit"]},
    "render_edit": {"label": "Render the edited video", "needs": ["plan_edit"]},
    "package": {"label": "Write title, description and thumbnail", "needs": ["render_edit"]},
    "finish": {"label": "Save the video to the library", "needs": []},
}
TOPIC_STEPS = ("research", "concepts", "script")  # need a topic as input
VIDEO_STEPS = ("prepare", "transcribe", "clean_audio", "plan_edit", "review_edit", "render_edit", "package")
PROMPT_KEYS = ("research", "concepts", "script")
PLATFORMS = ("youtube", "facebook", "instagram")


@dataclass(frozen=True)
class AgentSpec:
    slug: str
    name: str
    kind: str  # "small" (one task) or "large" (full automation)
    description: str
    steps: tuple[str, ...]
    needs: tuple[str, ...] = ()  # connected platforms the outcome needs
    input_kind: str = "topic"  # "topic" (one line), "text" (text to speak) or "video" (an uploaded video)
    input_hint: str = ""
    review: bool = False  # stop at needs_review for human approval of the final result
    uses: tuple[str, ...] = ()  # other agents this one is built from (shown on its card)
    prompts: dict = field(default_factory=dict)  # overrides of the default AI prompts

    @property
    def input_label(self) -> str:
        return {"topic": "Topic", "text": "Text to speak", "video": "Your video"}.get(self.input_kind, "Input")


BUILTIN_AGENTS: dict[str, AgentSpec] = {
    spec.slug: spec
    for spec in (
        AgentSpec(
            slug="youtube-shorts",
            name="YouTube Shorts Creator",
            kind="large",
            description="Writes, illustrates, voices and edits a vertical Short from a topic. "
            "You approve it before anything is posted.",
            steps=(
                "research", "concepts", "pick_concept", "script", "review_script",
                "voice", "captions", "visuals", "review_storyboard", "render", "finish",
            ),
            needs=("youtube",),
            input_hint="e.g. 3 surprising facts about coffee",
            review=True,
            uses=("script-writer", "voiceover"),
        ),
        AgentSpec(
            slug="script-writer",
            name="Script Writer",
            kind="small",
            description="Turns a topic into a Short script: hook, scenes with narration and image ideas, "
            "plus title, description and tags.",
            steps=("script",),
            input_hint="e.g. why cats knock things off tables",
        ),
        AgentSpec(
            slug="voiceover",
            name="Voiceover",
            kind="small",
            description="Turns your text into a natural voice recording (MP3) you can download.",
            steps=("voice",),
            input_kind="text",
            input_hint="Paste up to 3,000 characters",
        ),
        AgentSpec(
            slug="video-editor",
            name="Video Editor",
            kind="large",
            description="Upload your video: it cuts pauses, ums and restarts, cleans the audio, fixes caption "
            "spelling and reframes it for each platform. You approve it before anything is posted.",
            steps=("prepare", "transcribe", "clean_audio", "plan_edit", "review_edit", "render_edit", "package",
                   "finish"),
            input_kind="video",
            input_hint="A video up to 3 minutes",
            review=True,
        ),
    )
}


def spec_from_recipe(recipe) -> AgentSpec:
    return AgentSpec(
        slug=recipe.slug,
        name=recipe.name,
        kind=recipe.kind,
        description=recipe.description,
        steps=tuple(recipe.steps),
        needs=tuple(recipe.needs),
        input_kind=recipe.input_kind,
        input_hint=recipe.input_hint,
        review=recipe.review,
        uses=tuple(recipe.uses),
        prompts=dict(recipe.prompts or {}),
    )


def get_agent(slug: str) -> AgentSpec | None:
    """The agent recipe for a slug (inactive ones too, so existing runs keep working)."""
    from agents.models import AgentRecipe

    recipe = AgentRecipe.objects.filter(slug=slug).first()
    return spec_from_recipe(recipe) if recipe else BUILTIN_AGENTS.get(slug)


def active_agents() -> list[AgentSpec]:
    from agents.models import AgentRecipe

    return [spec_from_recipe(r) for r in AgentRecipe.objects.filter(is_active=True)]


def validate_recipe(data: dict) -> str | None:
    """Return a readable problem with a recipe, or None if it can run."""
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        return "Add at least one step."
    unknown = [s for s in steps if s not in STEP_BLOCKS]
    if unknown:
        return f"Unknown step: {', '.join(map(str, unknown))}."
    if len(set(steps)) != len(steps):
        return "Each step can only be used once."
    for i, step in enumerate(steps):
        missing = [need for need in STEP_BLOCKS[step]["needs"] if need not in steps[:i]]
        if missing:
            return f"'{step}' needs {', '.join(missing)} earlier in the recipe."
    if "finish" in steps and not any(v in steps[: steps.index("finish")] for v in ("render", "render_edit")):
        return "'finish' needs render or render_edit earlier in the recipe."
    input_kind = data.get("input_kind")
    if input_kind not in ("topic", "text", "video"):
        return "Input must be a topic, text or a video."
    if input_kind == "text" and any(s in TOPIC_STEPS for s in steps):
        return "Research, concepts and script need a topic as input, not text."
    if (input_kind == "video") != any(s in VIDEO_STEPS for s in steps) or (
        input_kind == "video" and any(s not in VIDEO_STEPS and s != "finish" for s in steps)
    ):
        return "Video steps need a video as input, and can't be mixed with other steps."
    if "voice" in steps and input_kind == "topic" and "script" not in steps[: steps.index("voice")]:
        return "'voice' needs a script earlier, or text as the input."
    if data.get("kind") not in ("small", "large"):
        return "Kind must be single task or full automation."
    if data.get("review") and "finish" not in steps:
        return "Final approval only applies to recipes that produce a video (ending with 'finish')."
    if any(n not in PLATFORMS for n in data.get("needs") or []):
        return "Unknown platform in 'needs'."
    prompts = data.get("prompts") or {}
    if not isinstance(prompts, dict) or any(k not in PROMPT_KEYS or not isinstance(v, str) or len(v) > 6000
                                            for k, v in prompts.items()):
        return "Prompts must be text (up to 6,000 characters) for research, concepts or script."
    return None


def _image_usd() -> Decimal:
    model = settings.AGENTS_IMAGE_MODEL
    row = get_fal_prices([model]).get(model) or FALLBACK_PRICES.get(model) or {}
    price = Decimal(str(row.get("unit_price", "0.03")))
    if row.get("unit") == "megapixels":
        return price * Decimal(IMAGE_WIDTH * IMAGE_HEIGHT) / Decimal(1_000_000)
    return price


def estimate_credits(spec: AgentSpec, run_input: dict, config: dict | None = None) -> Decimal:
    """Credits to reserve for one run: provider cost estimate x Admart markup."""
    if settings.AGENTS_DRY_RUN:
        return Decimal("0")
    usd = Decimal("0")
    from agents import providers

    llm_calls = sum(step in spec.steps for step in ("concepts", "script", "plan_edit", "package"))
    if "prepare" in spec.steps:  # video: priced by length (seconds probed when the run starts)
        minutes = Decimal(str(run_input.get("seconds") or MAX_VIDEO_SECONDS)) / Decimal(60)
        audio = AUDIO_LEVELS[video_settings(config or {})[2]][2]
        usd += minutes * (Decimal(settings.AGENTS_TRANSCRIBE_USD_PER_MIN) + Decimal(audio))
    usd += providers.text_usd() * llm_calls
    if "research" in spec.steps:
        usd += providers.research_usd()
    if "visuals" in spec.steps:
        usd += _image_usd() * SHORT_SCENES  # worst case: every scene an AI image
    if "voice" in spec.steps:
        chars = SHORT_NARRATION_CHARS if "script" in spec.steps else len(str(run_input.get("text", "")))
        usd += providers.speech_usd(chars)
    if "captions" in spec.steps:
        usd += providers.timing_usd()
    cost = quantize_credits(usd)
    return quantize_credits(cost * admart_markup_multiplier(cost))


def image_credits() -> Decimal:
    """Credits for regenerating one scene image."""
    if settings.AGENTS_DRY_RUN:
        return Decimal("0")
    cost = quantize_credits(_image_usd())
    return quantize_credits(cost * admart_markup_multiplier(cost))


def catalog_entry(spec: AgentSpec) -> dict:
    return {
        "slug": spec.slug,
        "name": spec.name,
        "kind": spec.kind,
        "description": spec.description,
        "needs": list(spec.needs),
        "inputLabel": spec.input_label,
        "inputKind": spec.input_kind,
        "inputHint": spec.input_hint,
        "review": spec.review,
        "uses": [a.name for slug in spec.uses if (a := get_agent(slug))],
        "estimatedCredits": f"{estimate_credits(spec, {'text': 'x' * 500}):f}",
        "steps": [step for step in spec.steps if step not in GATES],
        "styles": [{"id": key, "label": label} for key, (label, _) in STYLES.items()] if "visuals" in spec.steps else [],
        "voices": [{"id": key, "label": v[0]} for key, v in VOICES.items()] if "voice" in spec.steps else [],
        "paces": [{"id": key, "label": label} for key, (label, _) in PACES.items()] if "voice" in spec.steps else [],
        "tones": [{"id": key, "label": label} for key, (label, _) in TONES.items()] if "script" in spec.steps else [],
        "lengths": list(LENGTHS) if "script" in spec.steps else [],
        "redoCredits": f"{image_credits():f}" if "visuals" in spec.steps else None,
        **(_video_catalog(spec) if spec.input_kind == "video" else {}),
    }


def _video_catalog(spec: AgentSpec) -> dict:
    """Choices for the Video Editor, priced per minute of video."""
    per_minute = {"seconds": 60}
    return {
        "estimatedCredits": f"{estimate_credits(spec, per_minute):f}",
        "creditUnit": "minute",
        "maxSeconds": MAX_VIDEO_SECONDS,
        "formats": [{"id": key, "label": label} for key, (label, _) in FORMATS.items()],
        "cutStyles": [{"id": key, "label": label} for key, (label, _) in CUT_STYLES.items()],
        "audioLevels": [
            {"id": key, "label": label, "creditsPerMinute": f"{estimate_credits(spec, per_minute, {'audio': key}):f}"}
            for key, (label, _, _) in AUDIO_LEVELS.items()
        ],
    }
