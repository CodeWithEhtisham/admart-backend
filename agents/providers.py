"""AI services for agents: OpenRouter for text, fal.ai for voice, caption timing and images.

OpenRouter tries up to three models in order (AGENTS_OPENROUTER_MODELS). If a job's service
isn't set up or fails, the step fails and the run is refunded; caption timing alone falls back
to an even estimate.
"""

from __future__ import annotations

import base64
import logging
import subprocess
import threading
import time
from decimal import Decimal
from pathlib import Path

import requests
from django.conf import settings

from content import fal_client
from content.prompt_enhancer import _parse_json_text

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
FAL_TIMEOUT_SECONDS = 180
KOKORO_US = "fal-ai/kokoro/american-english"
KOKORO_UK = "fal-ai/kokoro/british-english"


class ProviderUnavailable(RuntimeError):
    """No service for this job is set up (message is safe to show users)."""


_used = threading.local()


def track() -> list[str]:
    """Start recording which services answer on this thread; returns the live list."""
    _used.names = []
    return _used.names


def note(name: str) -> None:
    names = getattr(_used, "names", None)
    if names is not None and name not in names:
        names.append(name)


def _call(job: str, name: str, ready: bool, fn):
    """Run one service call with a clear, user-safe error."""
    if not ready:
        raise ProviderUnavailable(f"No {job} service is set up on this server yet.")
    try:
        result = fn()
    except Exception as exc:
        logger.warning("%s service %s failed: %s", job, name, exc)
        raise RuntimeError(f"The {job} service ({name}) failed. Please try again later.") from exc
    note(name)
    return result


# ── text (research, concepts, script) via OpenRouter ──────────────────────


def _openrouter(system: str, user: str, json_mode: bool, search: bool, temperature: float):
    """One chat call. Returns (text, sources). OpenRouter falls through the listed models."""
    models = [m.strip() for m in settings.AGENTS_OPENROUTER_MODELS.split(",") if m.strip()]
    body = {
        "models": models[:3],
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": 8000,
        "reasoning": {"effort": "low"},  # free models "think" first: leave room for the answer
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if search:
        body["tools"] = [{"type": "openrouter:web_search",
                          "parameters": {"engine": settings.AGENTS_SEARCH_ENGINE, "max_results": 5}}]

    def post():
        return requests.post(OPENROUTER_URL, headers={"Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"},
                             json=body, timeout=180)

    response = post()
    if search and not response.ok:  # e.g. no credit for paid search, or the model can't use tools
        logger.warning("Web search unavailable (%s); researching without it", response.status_code)
        del body["tools"]
        search = False
        response = post()
    response.raise_for_status()
    message = response.json()["choices"][0]["message"]
    content = message.get("content")
    if not content:
        raise RuntimeError("The AI writer returned nothing.")
    sources = [
        {"title": str(c.get("title", ""))[:120], "uri": str(c.get("url", ""))[:500]}
        for a in message.get("annotations") or []
        if a.get("type") == "url_citation" and (c := a.get("url_citation") or {}).get("url")
    ][:8]
    return content, sources


def _as_dict(raw: str) -> dict | None:
    try:
        parsed = _parse_json_text(raw)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def text(system: str, user: str, *, json_mode: bool = True, search: bool = False, temperature: float = 0.8):
    """JSON mode returns a dict; otherwise (text, sources). A garbled JSON answer is retried once."""
    def run():
        for _ in range(2):
            raw, sources = _openrouter(system, user, json_mode, search, temperature)
            if not json_mode:
                return raw, sources
            parsed = _as_dict(raw)
            if parsed is not None:
                return parsed, sources
        raise RuntimeError("The AI writer returned an unexpected format.")

    result, sources = _call("AI writer", "openrouter", bool(settings.OPENROUTER_API_KEY), run)
    return result if json_mode else (result, sources)


# ── fal.ai: voice, caption timing, images ─────────────────────────────────


def _fal(model: str, arguments: dict) -> dict:
    """Submit a fal job, wait for it and return its result."""
    job = fal_client.submit(model, arguments)
    deadline = time.monotonic() + FAL_TIMEOUT_SECONDS
    while True:
        state = str(fal_client.status(status_url=job.status_url).get("status", "")).upper()
        if state == "COMPLETED":
            return fal_client.result(response_url=job.response_url)
        if state in ("FAILED", "ERROR", "CANCELLED") or time.monotonic() > deadline:
            raise RuntimeError(f"fal job {model} ended in state {state or 'timeout'}")
        time.sleep(1)


def _download(url: str) -> requests.Response:
    response = requests.get(url, timeout=120)
    response.raise_for_status()
    return response


def _to_mp3(raw: bytes) -> bytes:
    """Encode any audio FFmpeg understands to MP3."""
    done = subprocess.run(
        ["ffmpeg", "-y", "-i", "pipe:0", "-ac", "1", "-ar", "44100", "-b:a", "128k", "-f", "mp3", "pipe:1"],
        input=raw, capture_output=True, check=True, timeout=300,
    )
    return done.stdout


def speech(text_: str, voice: tuple | None = None, speed: float = 1.0) -> bytes:
    """MP3 bytes of the spoken text, read by Kokoro on fal. `voice` is a registry.VOICES entry."""
    from agents.registry import VOICES

    voice_id = (voice or VOICES["heart"])[1]

    def run():
        out = _fal(KOKORO_UK if voice_id.startswith("b") else KOKORO_US,
                   {"prompt": text_, "voice": voice_id, "speed": speed})
        return _to_mp3(_download(out["audio"]["url"]).content)

    return _call("voice", "fal", bool(settings.FAL_KEY), run)


def word_times(audio: Path) -> list[dict] | None:
    """Exact word timings from Whisper on fal, or None so captions fall back to an even estimate."""
    if not settings.FAL_KEY:
        return None
    try:
        data_uri = "data:audio/mpeg;base64," + base64.b64encode(audio.read_bytes()).decode()
        out = _fal(settings.AGENTS_WHISPER_MODEL, {"audio_url": data_uri, "chunk_level": "word", "language": "en"})
    except Exception:  # noqa: BLE001 — estimated timing is good enough
        logger.warning("Word timings unavailable; using estimated caption timing", exc_info=True)
        return None
    words = []
    for chunk in out.get("chunks") or []:
        word = str(chunk.get("text", "")).strip()
        start, end = (list(chunk.get("timestamp") or []) + [None, None])[:2]
        if word and start is not None:
            words.append({"word": word, "start": round(float(start), 3), "end": round(float(end if end is not None else start), 3)})
    note("fal")
    return words or None


def image(prompt: str, width: int, height: int) -> tuple[bytes, str]:
    def run():
        out = _fal(settings.AGENTS_IMAGE_MODEL, {
            "prompt": f"{prompt}. Vertical 9:16 composition, no text, no letters, no logos.",
            "image_size": {"width": width, "height": height}, "num_images": 1, "enable_safety_checker": True,
        })
        images = out.get("images") or []
        if not images or not images[0].get("url"):
            raise RuntimeError("fal returned no image")
        resp = _download(images[0]["url"])
        kind = resp.headers.get("Content-Type", "").split(";")[0]
        return resp.content, {"image/jpeg": ".jpg", "image/webp": ".webp"}.get(kind, ".png")

    return _call("image", "fal", bool(settings.FAL_KEY), run)


# ── cost estimate (USD) for credit quotes ─────────────────────────────────


def text_usd() -> Decimal:
    """One text call (0 with OpenRouter's free models)."""
    return Decimal(settings.AGENTS_LLM_USD_PER_RUN)


def research_usd() -> Decimal:
    """One web search for research."""
    return Decimal(settings.AGENTS_SEARCH_USD)


def speech_usd(chars: int) -> Decimal:
    return Decimal(settings.AGENTS_TTS_USD_PER_1K_CHARS) * Decimal(chars) / Decimal(1000)


def timing_usd() -> Decimal:
    return Decimal(settings.AGENTS_CAPTIONS_USD_PER_RUN)


def status() -> dict:
    """Which service each job uses — for the admin dashboard."""
    text_ready = "openrouter" if settings.OPENROUTER_API_KEY else None
    fal_ready = "fal" if settings.FAL_KEY else None
    return {"text": text_ready, "voice": fal_ready, "images": fal_ready, "captions": fal_ready or "estimate"}
