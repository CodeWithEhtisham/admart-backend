"""Suggest YouTube title, description, tags, category, and language."""

from __future__ import annotations

import requests
from django.conf import settings

from content.prompt_enhancer import GEMINI_ENDPOINT, _extract_candidate_text, _parse_json_text


class YoutubeSuggestConfigError(RuntimeError):
    """GEMINI_API_KEY is missing."""


class YoutubeSuggestProviderError(RuntimeError):
    """Gemini call failed."""

CATEGORY_IDS = {
    "1",
    "2",
    "10",
    "15",
    "17",
    "19",
    "20",
    "22",
    "23",
    "24",
    "25",
    "26",
    "27",
    "28",
    "29",
}
LANGUAGE_IDS = {"en", "es", "fr", "de", "pt", "hi", "ur", "ar", "ja", "ko", "zh", "id", "tr"}

SYSTEM_PROMPT = """
You write YouTube metadata for a social-media brand. Return JSON only:
{"title":"...","description":"...","tags":["..."],"categoryId":"22","language":"en"}

Rules:
- title: max 100 characters, no clickbait all-caps, no hashtags in the title
- description: 2-4 short paragraphs, no invented prices or claims
- tags: 8-15 short search phrases, no # symbols
- categoryId: one of 1,2,10,15,17,19,20,22,23,24,25,26,27,28,29
- language: ISO 639-1 from en,es,fr,de,pt,hi,ur,ar,ja,ko,zh,id,tr
- Keep the user's language if the prompt is not English
""".strip()


def suggest_youtube_copy(*, prompt: str = "", title: str = "", brand_name: str = "", industry: str = "") -> dict:
    prompt = (prompt or "").strip()
    title = (title or "").strip()
    if not prompt and not title:
        raise ValueError("prompt or title is required")
    if not settings.GEMINI_API_KEY:
        raise YoutubeSuggestConfigError(
            "Set GEMINI_API_KEY in the backend .env (Google AI Studio). FAL_KEY is only for image/video generation."
        )
    try:
        return _normalize(_call_gemini(prompt=prompt, title=title, brand_name=brand_name, industry=industry))
    except YoutubeSuggestProviderError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise YoutubeSuggestProviderError(str(exc)) from exc


def _call_gemini(*, prompt: str, title: str, brand_name: str, industry: str) -> dict:
    url = GEMINI_ENDPOINT.format(model=settings.PROMPT_ENHANCER_MODEL)
    user = (
        f"Brand: {brand_name or 'none'}\n"
        f"Industry: {industry or 'none'}\n"
        f"Working title: {title or 'none'}\n"
        f"Creative prompt: {prompt or 'none'}\n"
    )
    response = requests.post(
        url,
        headers={"Content-Type": "application/json", "x-goog-api-key": settings.GEMINI_API_KEY},
        json={
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0.5,
                "maxOutputTokens": 800,
                "responseMimeType": "application/json",
            },
        },
        timeout=settings.PROMPT_ENHANCER_TIMEOUT,
    )
    if response.status_code >= 400:
        raise YoutubeSuggestProviderError(
            f"Gemini HTTP {response.status_code}: {(response.text or '')[:240]}"
        )
    parsed = _parse_json_text(_extract_candidate_text(response.json()))
    if not isinstance(parsed, dict):
        raise RuntimeError("Gemini returned non-object JSON")
    return parsed


def _normalize(raw: dict) -> dict:
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    title = str(raw.get("title") or "").strip()[:100]
    description = str(raw.get("description") or "").strip()[:5000]
    category = str(raw.get("categoryId") or "22").strip()
    language = str(raw.get("language") or "en").strip().lower()
    clean_tags = [str(t).strip().lstrip("#")[:100] for t in tags if str(t).strip()][:30]
    return {
        "title": title or "Admart video",
        "description": description,
        "tags": clean_tags,
        "categoryId": category if category in CATEGORY_IDS else "22",
        "language": language if language in LANGUAGE_IDS else "en",
    }
