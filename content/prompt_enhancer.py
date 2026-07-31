"""Gemini-backed prompt enhancement with a deterministic local fallback."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SYSTEM_PROMPT = """
You are Admart's professional prompt writer for image and video generation.
Your job is to turn a short user idea into a clear, detailed, production-ready
prompt for commercial social-media creative.

Rules:
- Preserve the user's original intent, product, offer, venue, people, and language.
- Do not mention Gemini, fal.ai, APIs, model names, or hidden implementation details.
- Do not invent factual claims, discounts, prices, venue names, dates, or brand names.
- Add useful creative direction: subject, composition, setting, lighting, color,
  camera/angle, mood, texture, text placement when requested, and final polish.
- For image prompts, write one strong static scene.
- For video prompts, include motion, camera movement, pacing, scene progression,
  subject action, and final frame direction.
- Keep generated-media text short and readable if the user asks for text in the ad.
- Return strict JSON only with exactly these keys:
  {"enhancedPrompt": "...", "negativePrompt": "..."}
""".strip()

DEFAULT_NEGATIVE_IMAGE = (
    "blurry, low quality, low resolution, distorted subject, distorted hands, "
    "warped objects, unreadable text, misspelled text, bad typography, overexposed, "
    "underexposed, cluttered composition, watermark, logo artifacts"
)

DEFAULT_NEGATIVE_VIDEO = (
    "blurry, low quality, jitter, flicker, distorted motion, warped subject, "
    "unreadable text, misspelled text, bad typography, jump cuts, camera shake, "
    "motion artifacts, compression artifacts, watermark"
)


class PromptEnhancerError(RuntimeError):
    """Raised when the remote enhancer response cannot be used."""


def enhance_prompt(
    *,
    prompt: str,
    kind: str = "image",
    negative_prompt: str = "",
    context: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Return an enhanced prompt and negative prompt.

    The remote Gemini call is best-effort. If configuration is missing or the
    provider is unavailable, return a stronger local enhancement so the UI still
    helps the user.
    """

    base = _clean(prompt)
    media_kind = "video" if kind == "video" else "image"
    existing_negative = _clean(negative_prompt)
    safe_context = context if isinstance(context, dict) else {}

    if not base:
        return {"enhancedPrompt": "", "negativePrompt": existing_negative}

    if not settings.GEMINI_API_KEY:
        return _fallback(base, media_kind, existing_negative, safe_context)

    try:
        remote = _call_gemini(base, media_kind, existing_negative, safe_context)
        enhanced = _clean(remote.get("enhancedPrompt"))
        negative = _clean(remote.get("negativePrompt")) or existing_negative
        if len(enhanced.split()) < max(12, min(len(base.split()) + 5, 24)):
            raise PromptEnhancerError("Remote prompt was too short")
        return {
            "enhancedPrompt": enhanced[:3000],
            "negativePrompt": negative[:1000],
        }
    except Exception as exc:  # pragma: no cover - exact network failures vary
        logger.warning("Prompt enhancer fallback used: %s", exc)
        return _fallback(base, media_kind, existing_negative, safe_context)


def _call_gemini(
    prompt: str,
    kind: str,
    negative_prompt: str,
    context: dict[str, Any],
) -> dict[str, str]:
    model = settings.PROMPT_ENHANCER_MODEL
    url = GEMINI_ENDPOINT.format(model=model)
    payload = {
        "systemInstruction": {
            "parts": [{"text": SYSTEM_PROMPT}],
        },
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": _build_user_message(
                            prompt=prompt,
                            kind=kind,
                            negative_prompt=negative_prompt,
                            context=context,
                        )
                    }
                ],
            }
        ],
        "generationConfig": {
            "temperature": 0.65,
            "topP": 0.9,
            "maxOutputTokens": 1100,
            "responseMimeType": "application/json",
        },
    }
    response = requests.post(
        url,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": settings.GEMINI_API_KEY,
        },
        json=payload,
        timeout=settings.PROMPT_ENHANCER_TIMEOUT,
    )
    if response.status_code >= 400:
        raise PromptEnhancerError(f"Gemini HTTP {response.status_code}")

    data = response.json()
    text = _extract_candidate_text(data)
    parsed = _parse_json_text(text)
    if not isinstance(parsed, dict):
        raise PromptEnhancerError("Gemini returned non-object JSON")
    return parsed


def _build_user_message(
    *,
    prompt: str,
    kind: str,
    negative_prompt: str,
    context: dict[str, Any],
) -> str:
    context_json = json.dumps(_safe_context(context), ensure_ascii=True)
    negative_line = negative_prompt or "Create a helpful negative prompt."
    return (
        f"Media type: {kind}\n"
        f"User prompt: {prompt}\n"
        f"Existing negative prompt: {negative_line}\n"
        f"Generation settings/context: {context_json}\n\n"
        "Enhance this into a detailed professional prompt the user can review "
        "and edit before generation."
    )


def _safe_context(context: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "capability",
        "model",
        "aspectRatio",
        "resolution",
        "numImages",
        "duration",
        "generateAudio",
        "hasStartImage",
        "hasEndImage",
    }
    clean: dict[str, Any] = {}
    for key, value in context.items():
        if key not in allowed:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            clean[key] = value
    return clean


def _extract_candidate_text(data: dict[str, Any]) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        raise PromptEnhancerError("Gemini returned no candidates")
    parts = ((candidates[0].get("content") or {}).get("parts")) or []
    text = "\n".join(str(part.get("text") or "") for part in parts).strip()
    if not text:
        raise PromptEnhancerError("Gemini returned empty text")
    return text


def _parse_json_text(text: str) -> Any:
    clean = text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean)
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", clean, re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _fallback(
    prompt: str,
    kind: str,
    negative_prompt: str,
    context: dict[str, Any],
) -> dict[str, str]:
    if kind == "video":
        enhanced = _fallback_video(prompt, context)
        negative = negative_prompt or DEFAULT_NEGATIVE_VIDEO
    else:
        enhanced = _fallback_image(prompt, context)
        negative = negative_prompt or DEFAULT_NEGATIVE_IMAGE
    return {"enhancedPrompt": enhanced[:3000], "negativePrompt": negative[:1000]}


def _fallback_image(prompt: str, context: dict[str, Any]) -> str:
    ratio = context.get("aspectRatio")
    resolution = context.get("resolution")
    settings = []
    if ratio:
        settings.append(f"{ratio} composition")
    if resolution:
        settings.append(f"{resolution} output detail")
    settings_text = f" Use {', '.join(settings)}." if settings else ""
    return (
        f"Professional advertising image of {prompt}. Clear hero subject, polished "
        "commercial composition, realistic textures, attractive product styling, "
        "clean background with intentional negative space, soft directional studio "
        "lighting, crisp focus, high detail, natural color grading, premium social "
        "media campaign look, readable typography only if text is requested."
        f"{settings_text}"
    )


def _fallback_video(prompt: str, context: dict[str, Any]) -> str:
    duration = context.get("duration")
    ratio = context.get("aspectRatio")
    resolution = context.get("resolution")
    settings = []
    if duration:
        settings.append(f"{duration} duration")
    if ratio:
        settings.append(f"{ratio} framing")
    if resolution:
        settings.append(f"{resolution} finish")
    settings_text = f" Match {', '.join(settings)}." if settings else ""
    return (
        f"Professional social media video of {prompt}. Start with a strong hook "
        "frame, keep the subject clearly visible, use smooth camera movement, "
        "natural motion, cinematic lighting, realistic textures, clean pacing, "
        "stable framing, appetizing or premium product detail, and finish on a "
        "clear final frame with space for a short offer or call to action if needed."
        f"{settings_text}"
    )


def _clean(value: Any) -> str:
    return str(value or "").strip()
