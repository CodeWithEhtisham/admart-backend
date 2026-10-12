"""Agent catalog. Adding an agent = a spec here + any new steps in agents.steps."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings

from content.pricing import FALLBACK_PRICES, admart_markup_multiplier, get_fal_prices, quantize_credits

SHORT_SCENES = 6
SHORT_NARRATION_CHARS = 900  # ~130 words, ~45 seconds of speech
IMAGE_WIDTH, IMAGE_HEIGHT = 768, 1344  # 9:16, about 1 megapixel; rendered up to 1080x1920
MAX_TEXT_INPUT = 3000

# Visual style presets: applied to every image prompt of a Short.
STYLES = {
    "cinematic": ("Cinematic", "cinematic film still, dramatic lighting, shallow depth of field, rich colour grade"),
    "photoreal": ("Photoreal", "photorealistic, natural light, sharp detail, editorial photography"),
    "illustration": ("Flat illustration", "flat vector illustration, bold simple shapes, clean bright colours"),
    "anime": ("Anime", "anime style, clean line art, cel shading, vibrant colours"),
    "minimal": ("Minimal", "minimalist composition, soft pastel palette, lots of negative space"),
}
# Pause points where a person approves before money is spent on the next stage.
GATES = {"pick_concept": "concept", "review_script": "script", "review_storyboard": "storyboard"}


@dataclass(frozen=True)
class AgentSpec:
    slug: str
    name: str
    kind: str  # "small" (one task) or "large" (full automation)
    description: str
    steps: tuple[str, ...]
    needs: tuple[str, ...] = ()  # connected platforms the outcome needs
    input_label: str = "Topic"
    input_hint: str = ""
    review: bool = False  # large agents stop at needs_review for human approval
    uses: tuple[str, ...] = ()  # small agents a large agent is built from (shown on its card)


AGENTS: dict[str, AgentSpec] = {
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
            input_label="Text to speak",
            input_hint="Paste up to 3,000 characters",
        ),
    )
}


def _image_usd() -> Decimal:
    from agents import providers

    if not providers.image_uses_fal():
        return Decimal("0")  # Cloudflare free allowance
    model = settings.AGENTS_IMAGE_MODEL
    row = get_fal_prices([model]).get(model) or FALLBACK_PRICES.get(model) or {}
    price = Decimal(str(row.get("unit_price", "0.03")))
    if row.get("unit") == "megapixels":
        return price * Decimal(IMAGE_WIDTH * IMAGE_HEIGHT) / Decimal(1_000_000)
    return price


def estimate_credits(spec: AgentSpec, run_input: dict) -> Decimal:
    """Credits to reserve for one run: provider cost estimate x Admart markup."""
    if settings.AGENTS_DRY_RUN:
        return Decimal("0")
    usd = Decimal("0")
    from agents import providers

    llm_calls = sum(step in spec.steps for step in ("concepts", "script"))
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
        "inputHint": spec.input_hint,
        "review": spec.review,
        "uses": [AGENTS[slug].name for slug in spec.uses],
        "estimatedCredits": f"{estimate_credits(spec, {'text': 'x' * 500}):f}",
        "steps": [step for step in spec.steps if step not in GATES],
        "styles": [{"id": key, "label": label} for key, (label, _) in STYLES.items()] if "visuals" in spec.steps else [],
        "redoCredits": f"{image_credits():f}" if "visuals" in spec.steps else None,
    }
