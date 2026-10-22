"""The writing (OpenRouter) and image (fal) models users can pick per agent, and their prices.

A deployment stores its picks in config["models"] = {"text": id, "image": id}; anything missing or
unknown falls back to the server defaults (first of AGENTS_OPENROUTER_MODELS, AGENTS_IMAGE_MODEL).
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings

from content.catalog import MODEL_CATALOG

logger = logging.getLogger(__name__)

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
PRICES_TTL_SECONDS = 30 * 60
# Typical tokens of one agent text call, for credit quotes: the prompt with brand lines, research notes
# or a transcript excerpt (~3,000), and a JSON answer such as a script or a set of posts (~1,500).
PROMPT_TOKENS = 3000
COMPLETION_TOKENS = 1500

# Cheapest first. strength: "free" (daily limits), "fast" (cheap, good enough), "balanced", "strong", "top".
TEXT_MODELS = [
    {"id": "nvidia/nemotron-3-super-120b-a12b:free", "label": "Nemotron 3 Super (free)", "strength": "free"},
    {"id": "qwen/qwen3.7-flash", "label": "Qwen3.7 Flash", "strength": "fast"},
    {"id": "deepseek/deepseek-v4-flash", "label": "DeepSeek V4 Flash", "strength": "fast"},
    {"id": "google/gemini-2.5-flash-lite", "label": "Gemini 2.5 Flash Lite", "strength": "fast"},
    {"id": "deepseek/deepseek-v4-pro", "label": "DeepSeek V4 Pro", "strength": "balanced"},
    {"id": "anthropic/claude-sonnet-5.5", "label": "Claude Sonnet 5.5", "strength": "strong"},
    {"id": "google/gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro", "strength": "strong"},
    {"id": "openai/gpt-5.5", "label": "GPT-5.5", "strength": "top"},
]
# Credits a run pays on top for its writer: free and fast models are included in the run's price, smarter ones
# add a flat fee per CALLS_PER_FEE text calls (one Short). Set at 2.5-3x their real cost on the cheapest credits.
TEXT_FEES = {"free": Decimal("0"), "fast": Decimal("0"), "balanced": Decimal("0.05"), "strong": Decimal("0.25"),
             "top": Decimal("0.50")}
CALLS_PER_FEE = 3
# USD per (prompt, completion) token, from OpenRouter's /api/v1/models on 2026-10-19. Used offline.
FALLBACK_TEXT_PRICES: dict[str, tuple[Decimal, Decimal]] = {
    "nvidia/nemotron-3-super-120b-a12b:free": (Decimal("0"), Decimal("0")),
    "qwen/qwen3.7-flash": (Decimal("0.00000003"), Decimal("0.00000013")),
    "deepseek/deepseek-v4-flash": (Decimal("0.000000091"), Decimal("0.000000182")),
    "google/gemini-2.5-flash-lite": (Decimal("0.0000001"), Decimal("0.0000004")),
    "deepseek/deepseek-v4-pro": (Decimal("0.00000095526"), Decimal("0.00000191052")),
    "anthropic/claude-sonnet-5.5": (Decimal("0.000002"), Decimal("0.00001")),
    "google/gemini-3.1-pro-preview": (Decimal("0.000002"), Decimal("0.000012")),
    "openai/gpt-5.5": (Decimal("0.000005"), Decimal("0.00003")),
}
# Left out for agents: GPT Image 2 has only a placeholder $1 price; Nano Banana 2.1 gets no 9:16 option yet.
_NOT_FOR_AGENTS = {"openai/gpt-image-2", "google/nano-banana-2.1"}
IMAGE_MODELS = [
    {"id": m["id"], "label": m["label"]} for m in MODEL_CATALOG["textToImage"] if m["id"] not in _NOT_FOR_AGENTS
]
TEXT_IDS = {m["id"] for m in TEXT_MODELS}
IMAGE_IDS = {m["id"] for m in IMAGE_MODELS}

_CACHE: dict = {"expires_at": 0.0, "prices": None}


def default_text_model() -> str:
    return next((m.strip() for m in settings.AGENTS_OPENROUTER_MODELS.split(",") if m.strip()), "")


def chosen_models(config: dict | None) -> dict:
    """{"text": id, "image": id} for a deployment config; unknown ids fall back to the defaults."""
    picked = (config or {}).get("models")
    picked = picked if isinstance(picked, dict) else {}
    return {
        "text": picked["text"] if picked.get("text") in TEXT_IDS else default_text_model(),
        "image": picked["image"] if picked.get("image") in IMAGE_IDS else settings.AGENTS_IMAGE_MODEL,
    }


def text_prices() -> dict[str, tuple[Decimal, Decimal]]:
    """USD per prompt and completion token by model id: OpenRouter's live list (cached), else the fallback."""
    now = time.monotonic()
    if _CACHE["prices"] is not None and now < _CACHE["expires_at"]:
        return _CACHE["prices"]
    prices = dict(FALLBACK_TEXT_PRICES)
    if settings.OPENROUTER_API_KEY:  # no key: agents don't write with OpenRouter, so don't ask it
        try:
            response = requests.get(OPENROUTER_MODELS_URL, timeout=10)
            response.raise_for_status()
            rows = response.json().get("data") or []
        except (requests.RequestException, ValueError, AttributeError) as exc:
            logger.warning("OpenRouter prices unavailable (%s); using the last known ones", exc)
            rows = []
        for row in rows:
            try:
                model_id, pricing = str(row["id"]), row["pricing"]
                prompt, completion = Decimal(str(pricing["prompt"])), Decimal(str(pricing["completion"]))
            except (KeyError, TypeError, InvalidOperation):
                continue
            if prompt >= 0 and completion >= 0:  # routers like openrouter/auto report -1
                prices[model_id] = (prompt, completion)
    _CACHE.update(prices=prices, expires_at=now + PRICES_TTL_SECONDS)
    return prices


def text_fee(model: str) -> Decimal:
    """The flat credits this writer adds per CALLS_PER_FEE text calls (0: included in the run's price)."""
    strength = next((m["strength"] for m in TEXT_MODELS if m["id"] == model), "fast")
    return TEXT_FEES.get(strength, Decimal("0"))


def text_credits(model: str, calls: int) -> Decimal:
    """Credits on top of a run for `calls` text calls with this writer: its flat fee per CALLS_PER_FEE calls, and
    never less than the real cost with Admart's markup (so a price rise can't make a run lose money)."""
    from content.pricing import admart_markup_multiplier, quantize_credits

    fee = text_fee(model)
    if not fee or calls <= 0:
        return Decimal("0")
    cost = quantize_credits(text_call_usd(model) * calls)
    return max(fee * -(-calls // CALLS_PER_FEE), quantize_credits(cost * admart_markup_multiplier(cost)))


def text_call_usd(model: str) -> Decimal:
    """Estimated USD for one agent text call with this model (the flat setting for an unpriced model)."""
    price = text_prices().get(model)
    if price is None:
        from agents.providers import text_usd

        return text_usd()
    return PROMPT_TOKENS * price[0] + COMPLETION_TOKENS * price[1]
