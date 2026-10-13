"""Switchable AI providers for agents, free ones first.

Each job (text, speech, image, word timings) has an ordered provider list in settings,
e.g. AGENTS_TTS_PROVIDERS="kokoro,gemini,openai". Providers that aren't set up (no key,
package or model files) are skipped; if one fails (e.g. a free-tier limit) the next is
tried. Only when every provider fails does the step fail (and the run is refunded).
"""

from __future__ import annotations

import base64
import logging
import subprocess
import threading
import time
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

import requests
from django.conf import settings

from content import fal_client
from content.prompt_enhancer import GEMINI_ENDPOINT, _extract_candidate_text, _parse_json_text

logger = logging.getLogger(__name__)

IMAGE_TIMEOUT_SECONDS = 180
KOKORO_MODEL = "kokoro-v1.0.int8.onnx"
KOKORO_VOICES = "voices-v1.0.bin"


class ProviderUnavailable(RuntimeError):
    """No provider for this job is set up (message is safe to show users)."""


def _chain(setting: str) -> list[str]:
    return [p.strip().lower() for p in str(getattr(settings, setting, "")).split(",") if p.strip()]


_used = threading.local()


def track() -> list[str]:
    """Start recording which services answer on this thread; returns the live list."""
    _used.names = []
    return _used.names


def note(name: str) -> None:
    names = getattr(_used, "names", None)
    if names is not None and name not in names:
        names.append(name)


def _run_chain(job: str, setting: str, ready: dict, call: dict, *args, **kwargs):
    """Try each configured provider in order; return (provider, result)."""
    tried = []
    for name in _chain(setting):
        if name not in call or not ready.get(name, lambda: False)():
            continue
        try:
            result = call[name](*args, **kwargs)
            note(name)
            return name, result
        except Exception as exc:  # noqa: BLE001 — fall through to the next provider
            logger.warning("%s provider %s failed: %s", job, name, exc)
            tried.append(name)
    if tried:
        raise RuntimeError(f"Every {job} service failed ({', '.join(tried)}). Please try again later.")
    raise ProviderUnavailable(f"No {job} service is set up on this server yet.")


def first_ready(setting: str, ready: dict) -> str | None:
    return next((n for n in _chain(setting) if ready.get(n, lambda: False)()), None)


# ── text (script, concepts, research) ─────────────────────────────────────

TEXT_READY = {
    "gemini": lambda: bool(settings.GEMINI_API_KEY),
    "groq": lambda: bool(settings.GROQ_API_KEY),
}


def _gemini_text(system: str, user: str, json_mode: bool, search: bool, temperature: float):
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": 2500},
    }
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    if search:
        body["tools"] = [{"google_search": {}}]
    response = requests.post(
        GEMINI_ENDPOINT.format(model=settings.PROMPT_ENHANCER_MODEL),
        headers={"Content-Type": "application/json", "x-goog-api-key": settings.GEMINI_API_KEY},
        json=body,
        timeout=90,
    )
    response.raise_for_status()
    data = response.json()
    text = _extract_candidate_text(data)
    sources = []
    if search:
        chunks = ((data.get("candidates") or [{}])[0].get("groundingMetadata") or {}).get("groundingChunks") or []
        sources = [
            {"title": str(c["web"].get("title", ""))[:120], "uri": str(c["web"].get("uri", ""))[:500]}
            for c in chunks
            if isinstance(c, dict) and isinstance(c.get("web"), dict)
        ][:8]
    return text, sources


def _groq_text(system: str, user: str, json_mode: bool, search: bool, temperature: float):
    """Groq (OpenAI-compatible). No web search: research comes from the model's own knowledge."""
    body = {
        "model": settings.AGENTS_GROQ_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": 2500,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
        json=body,
        timeout=90,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"], []


def text(system: str, user: str, *, json_mode: bool = True, search: bool = False, temperature: float = 0.8):
    """JSON mode returns a dict; otherwise (text, sources)."""
    _, (raw, sources) = _run_chain(
        "AI writer", "AGENTS_LLM_PROVIDERS", TEXT_READY,
        {"gemini": _gemini_text, "groq": _groq_text}, system, user, json_mode, search, temperature,
    )
    if not json_mode:
        return raw, sources
    parsed = _parse_json_text(raw)
    if not isinstance(parsed, dict):
        raise RuntimeError("The AI writer returned an unexpected format. Please try again.")
    return parsed


# ── speech ────────────────────────────────────────────────────────────────


def _kokoro_ready() -> bool:
    folder = Path(settings.AGENTS_KOKORO_DIR)
    if not ((folder / KOKORO_MODEL).exists() and (folder / KOKORO_VOICES).exists()):
        return False
    try:
        import kokoro_onnx  # noqa: F401
    except ImportError:
        return False
    return True


SPEECH_READY = {
    "kokoro": _kokoro_ready,
    "gemini": lambda: bool(settings.GEMINI_API_KEY),
    "openai": lambda: bool(settings.OPENAI_API_KEY),
}


def _to_mp3(raw: bytes, input_args: list[str]) -> bytes:
    """Encode raw audio (from stdin) to MP3 with FFmpeg."""
    done = subprocess.run(
        ["ffmpeg", "-y", *input_args, "-i", "pipe:0", "-ac", "1", "-ar", "44100", "-b:a", "128k", "-f", "mp3", "pipe:1"],
        input=raw, capture_output=True, check=True, timeout=300,
    )
    return done.stdout


@lru_cache(maxsize=1)
def _kokoro():
    from kokoro_onnx import Kokoro

    folder = Path(settings.AGENTS_KOKORO_DIR)
    return Kokoro(str(folder / KOKORO_MODEL), str(folder / KOKORO_VOICES))


def _kokoro_speech(text_: str, voice: tuple | None, speed: float) -> bytes:
    import numpy as np

    name = voice[1] if voice else settings.AGENTS_KOKORO_VOICE
    lang = "en-gb" if name.startswith("b") else "en-us"
    samples, rate = _kokoro().create(text_, voice=name, speed=speed, lang=lang)
    return _to_mp3(np.asarray(samples, dtype="float32").tobytes(), ["-f", "f32le", "-ar", str(rate), "-ac", "1"])


def _gemini_speech(text_: str, voice: tuple | None, speed: float) -> bytes:
    pace = "slowly and calmly" if speed < 1 else "briskly" if speed > 1 else "clearly"
    response = requests.post(
        GEMINI_ENDPOINT.format(model=settings.AGENTS_GEMINI_TTS_MODEL),
        headers={"Content-Type": "application/json", "x-goog-api-key": settings.GEMINI_API_KEY},
        json={
            "contents": [{"parts": [{"text": f"Say {pace} and with energy, like a friendly narrator: {text_}"}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice[2] if voice else settings.AGENTS_GEMINI_TTS_VOICE}}},
            },
        },
        timeout=120,
    )
    response.raise_for_status()
    part = response.json()["candidates"][0]["content"]["parts"][0]
    pcm = base64.b64decode(part["inlineData"]["data"])
    return _to_mp3(pcm, ["-f", "s16le", "-ar", "24000", "-ac", "1"])


def _openai_speech(text_: str, voice: tuple | None, speed: float) -> bytes:
    body = {"model": settings.AGENTS_TTS_MODEL, "voice": voice[3] if voice else settings.AGENTS_TTS_VOICE,
            "input": text_[:4000], "response_format": "mp3", "speed": speed}
    if settings.AGENTS_TTS_MODEL.startswith("gpt-4o"):
        body["instructions"] = "Speak clearly and with energy, like a friendly YouTube Shorts narrator."
    response = requests.post(
        "https://api.openai.com/v1/audio/speech",
        headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
        json=body,
        timeout=120,
    )
    response.raise_for_status()
    return response.content


def speech(text_: str, voice: tuple | None = None, speed: float = 1.0) -> bytes:
    """MP3 bytes of the spoken text. `voice` is a registry.VOICES entry (None: the server default)."""
    _, audio = _run_chain(
        "voice", "AGENTS_TTS_PROVIDERS", SPEECH_READY,
        {"kokoro": _kokoro_speech, "gemini": _gemini_speech, "openai": _openai_speech}, text_, voice, speed,
    )
    return audio


# ── images ────────────────────────────────────────────────────────────────

IMAGE_READY = {
    "cloudflare": lambda: bool(settings.CLOUDFLARE_ACCOUNT_ID and settings.CLOUDFLARE_API_TOKEN),
    "fal": lambda: bool(settings.FAL_KEY),
}


def _cloudflare_image(prompt: str, width: int, height: int) -> tuple[bytes, str]:
    """Workers AI FLUX schnell (free daily allowance). Output is square; the renderer crops to 9:16."""
    response = requests.post(
        f"https://api.cloudflare.com/client/v4/accounts/{settings.CLOUDFLARE_ACCOUNT_ID}/ai/run/"
        f"{settings.AGENTS_CLOUDFLARE_IMAGE_MODEL}",
        headers={"Authorization": f"Bearer {settings.CLOUDFLARE_API_TOKEN}"},
        json={"prompt": f"{prompt}. Main subject centred.", "steps": 4},
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    image = (data.get("result") or {}).get("image") or data.get("image")
    if not image:
        raise RuntimeError("Cloudflare returned no image")
    return base64.b64decode(image), ".jpg"


def _fal_image(prompt: str, width: int, height: int) -> tuple[bytes, str]:
    job = fal_client.submit(
        settings.AGENTS_IMAGE_MODEL,
        {"prompt": prompt, "image_size": {"width": width, "height": height}, "num_images": 1,
         "enable_safety_checker": True},
    )
    deadline = time.monotonic() + IMAGE_TIMEOUT_SECONDS
    while True:
        state = str(fal_client.status(status_url=job.status_url).get("status", "")).upper()
        if state == "COMPLETED":
            break
        if state in ("FAILED", "ERROR", "CANCELLED") or time.monotonic() > deadline:
            raise RuntimeError(f"fal image job ended in state {state or 'timeout'}")
        time.sleep(2)
    images = fal_client.result(response_url=job.response_url).get("images") or []
    if not images or not images[0].get("url"):
        raise RuntimeError("fal returned no image")
    resp = requests.get(images[0]["url"], timeout=120)
    resp.raise_for_status()
    kind = resp.headers.get("Content-Type", "").split(";")[0]
    return resp.content, {"image/jpeg": ".jpg", "image/webp": ".webp"}.get(kind, ".png")


def image(prompt: str, width: int, height: int) -> tuple[bytes, str]:
    _, result = _run_chain(
        "image", "AGENTS_IMAGE_PROVIDERS", IMAGE_READY,
        {"cloudflare": _cloudflare_image, "fal": _fal_image},
        f"{prompt}. Vertical 9:16 composition, no text, no letters, no logos.", width, height,
    )
    return result


# ── word timings (captions) ───────────────────────────────────────────────


def _local_whisper_ready() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


TIMING_READY = {"local": _local_whisper_ready, "openai": lambda: bool(settings.OPENAI_API_KEY)}


@lru_cache(maxsize=1)
def _whisper():
    from faster_whisper import WhisperModel

    return WhisperModel(settings.AGENTS_WHISPER_MODEL, device="cpu", compute_type="int8",
                        download_root=settings.AGENTS_WHISPER_DIR)


def _local_words(audio: Path) -> list[dict]:
    import numpy as np

    # Decode with FFmpeg (16 kHz mono float) instead of faster-whisper's PyAV loader,
    # which breaks with some PyAV releases.
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(audio), "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"],
        capture_output=True, check=True, timeout=120,
    ).stdout
    samples = np.frombuffer(raw, dtype="float32")
    segments, _ = _whisper().transcribe(samples, word_timestamps=True, beam_size=1, language="en")
    return [
        {"word": w.word.strip(), "start": round(float(w.start), 3), "end": round(float(w.end), 3)}
        for seg in segments for w in (seg.words or []) if w.word.strip()
    ]


def _openai_words(audio: Path) -> list[dict]:
    with audio.open("rb") as fh:
        response = requests.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            data={"model": settings.AGENTS_TRANSCRIBE_MODEL, "response_format": "verbose_json",
                  "timestamp_granularities[]": "word"},
            files={"file": (audio.name, fh, "audio/mpeg")},
            timeout=120,
        )
    response.raise_for_status()
    return [
        {"word": str(w.get("word", "")).strip(), "start": round(float(w["start"]), 3), "end": round(float(w["end"]), 3)}
        for w in response.json().get("words") or []
        if str(w.get("word", "")).strip()
    ]


def word_times(audio: Path) -> list[dict] | None:
    """Exact word timings, or None so captions fall back to an even estimate."""
    try:
        _, words = _run_chain("caption timing", "AGENTS_CAPTION_PROVIDERS", TIMING_READY,
                              {"local": _local_words, "openai": _openai_words}, audio)
    except RuntimeError:
        logger.warning("Word timings unavailable; using estimated caption timing", exc_info=True)
        return None
    return words or None


# ── cost estimate (USD) for credit quotes ─────────────────────────────────

FREE = Decimal("0")


def text_usd() -> Decimal:
    return Decimal(settings.AGENTS_LLM_USD_PER_RUN) if first_ready("AGENTS_LLM_PROVIDERS", TEXT_READY) else FREE


def research_usd() -> Decimal:
    # Search grounding is billed on Gemini only; Groq research has no web search.
    return Decimal(settings.AGENTS_RESEARCH_USD) if first_ready("AGENTS_LLM_PROVIDERS", TEXT_READY) == "gemini" else FREE


def speech_usd(chars: int) -> Decimal:
    if first_ready("AGENTS_TTS_PROVIDERS", SPEECH_READY) != "openai":
        return FREE  # Kokoro runs locally; Gemini TTS is within its free tier
    return Decimal(settings.AGENTS_TTS_USD_PER_1K_CHARS) * Decimal(chars) / Decimal(1000)


def timing_usd() -> Decimal:
    if first_ready("AGENTS_CAPTION_PROVIDERS", TIMING_READY) != "openai":
        return FREE
    return Decimal(settings.AGENTS_TRANSCRIBE_USD_PER_MIN)


def image_uses_fal() -> bool:
    return first_ready("AGENTS_IMAGE_PROVIDERS", IMAGE_READY) == "fal"


def status() -> dict:
    """Which provider each job will use first — for the setup doc / admin."""
    return {
        "text": first_ready("AGENTS_LLM_PROVIDERS", TEXT_READY),
        "voice": first_ready("AGENTS_TTS_PROVIDERS", SPEECH_READY),
        "images": first_ready("AGENTS_IMAGE_PROVIDERS", IMAGE_READY),
        "captions": first_ready("AGENTS_CAPTION_PROVIDERS", TIMING_READY) or "estimate",
    }
