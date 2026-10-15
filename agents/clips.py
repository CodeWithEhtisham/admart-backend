"""Clip Maker agent: a long video (YouTube link or upload) → several vertical clips.

get_video → transcribe_long → find_clips → review_clips → render_clips → finish_clips

Moments are chosen by sentence number, not by timestamp, so every clip starts and ends on a whole
sentence; edges then get a short lead-in and tail that never reach into the next sentence.
Plan: docs/plans/2026-10-14-clip-maker-agent.md
"""

from __future__ import annotations

import difflib
import logging
import os
import re
import shutil
import subprocess
import time
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from django.conf import settings

from agents import providers, reframe, render, video_edit
from agents import steps as base
from agents.video_edit import VIDEO_SUFFIXES, asset_file, probe
from content.models import LibraryAsset
from content.storage_utils import absolute_media_url
from content.url_resolve import fetch_media

logger = logging.getLogger(__name__)

FREE_MAX_SECONDS = 30 * 60
PAID_MAX_SECONDS = 2 * 60 * 60
CLIP_LENGTHS = {  # id -> (label, shortest, longest seconds)
    "short": ("15–30 s · fast and punchy", 15, 30),
    "medium": ("30–60 s · most popular", 30, 60),
    "long": ("60–90 s · stories and explainers", 60, 90),
}
CLIP_COUNTS = range(3, 11)
LAYOUTS = {
    "auto": "Follow the speaker (face tracking, split screen for two)",
    "crop": "Fill the screen (crop the centre)",
    "fit": "Show the whole picture (blurred background)",
}
CHUNK_SECONDS = 600  # transcription pieces: Groq takes up to 25 MB per file
WINDOW_SECONDS = 20 * 60  # transcript the AI reads per call
WINDOW_OVERLAP = 60
LEAD, TAIL = 0.25, 0.35  # seconds kept before the first and after the last word
SENTENCE_GAP = 1.2  # a pause this long ends a sentence even without punctuation
MAX_SENTENCE_WORDS = 40
HOOK_SECONDS = 3.5
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"}

CLIPS_PROMPT = f"""You are an expert short-form video editor (TikTok, Instagram Reels, YouTube Shorts).
You get part of a long video's transcript as numbered sentences: "[n] (m:ss) text".
Find the moments that work best as stand-alone vertical clips of {{low}}-{{high}} seconds.
A great clip:
- opens with a hook in its first sentence: a bold claim, a question, a surprising fact, a conflict or
  the start of a story. Never a greeting, an intro or "so, as I was saying";
- makes sense to someone who has not seen the rest of the video;
- builds to a payoff (punchline, answer, insight, emotional peak) and ends right after it;
- is about one idea.
Return JSON only: {{{{"clips": [{{{{"from": int, "to": int, "score": int, "title": string, "hook": string,
"reason": string}}}}]}}}}
- from / to: the first and last sentence numbers of the clip (inclusive). Use the times shown so the
  clip lasts {{low}}-{{high}} seconds.
- score: 0-100 chance it does well as a Short: hook strength, emotion, insight or humour, payoff, and
  whether it stands alone. Be strict: most moments are 40-70, only exceptional ones above 85.
- title: {base.TITLE_RULES}.
- hook: on-screen text for the first seconds, at most 8 words, in the language of the transcript,
  no emojis or hashtags.
- reason: one short sentence on why it works.
Up to {{count}} clips, best first. Fewer if there are fewer good moments. Never invent anything that is
not said in the transcript."""


# ── input ─────────────────────────────────────────────────────────────────


def parse_youtube_url(text: str) -> str | None:
    """The canonical watch URL for a single YouTube video link, or None."""
    raw = (text or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    try:
        url = urlparse(raw)
    except ValueError:
        return None
    if url.scheme not in ("http", "https") or (url.hostname or "").lower() not in YOUTUBE_HOSTS:
        return None
    parts = [p for p in url.path.split("/") if p]
    if url.hostname.lower().endswith("youtu.be"):
        video_id = parts[0] if parts else ""
    elif parts[:1] == ["watch"]:
        video_id = (parse_qs(url.query).get("v") or [""])[0]
    elif len(parts) >= 2 and parts[0] in ("shorts", "live", "embed", "v"):
        video_id = parts[1]
    else:
        return None
    return f"https://www.youtube.com/watch?v={video_id}" if YOUTUBE_ID.match(video_id) else None


def max_seconds(user) -> int:
    """Longest source video for the user's plan."""
    return FREE_MAX_SECONDS if getattr(user, "plan", "free") == "free" else PAID_MAX_SECONDS


def _ytdlp_options(**extra) -> dict:
    options = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        # Slow or flaky connections: wait longer, retry more, and resume a half-done download on "Try again".
        "socket_timeout": 60,
        "retries": 10,
        "fragment_retries": 10,
        "continuedl": True,
        # YouTube needs a JavaScript runtime to unlock formats; Deno is yt-dlp's default, Node also works.
        "js_runtimes": {name.strip(): {} for name in settings.CLIPS_YTDLP_JS_RUNTIMES.split(",") if name.strip()},
    }
    if settings.CLIPS_YTDLP_PROXY:
        options["proxy"] = settings.CLIPS_YTDLP_PROXY
    if settings.CLIPS_YTDLP_COOKIES:
        options["cookiefile"] = settings.CLIPS_YTDLP_COOKIES
    if settings.CLIPS_YTDLP_POT_URL:  # PO-token sidecar (bgutil) against "confirm you're not a bot" on server IPs
        options["extractor_args"] = {"youtubepot-bgutilhttp": {"base_url": [settings.CLIPS_YTDLP_POT_URL]}}
    return {**options, **extra}


def _youtube_error(exc: Exception) -> RuntimeError:
    logger.warning("YouTube request failed: %s", exc)
    text = str(exc).lower()
    if "not a bot" in text or "sign in" in text:
        return RuntimeError("YouTube is blocking downloads from our server right now. Upload the video file "
                            "instead, or try again later.")
    if "timed out" in text or "connection" in text or "reset by peer" in text:
        return RuntimeError("The download from YouTube kept stalling (a slow connection). Try again: it continues "
                            "where it stopped.")
    if "private" in text or "unavailable" in text or "members" in text:
        return RuntimeError("This YouTube video is private or unavailable. Use a public video.")
    return RuntimeError("We couldn't open that YouTube video. Check the link, or upload the file instead.")


def youtube_info(url: str) -> dict:
    """{"title", "duration", "live"} for a YouTube video, without downloading it. Raises RuntimeError."""
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL(_ytdlp_options(skip_download=True)) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # noqa: BLE001 — yt-dlp raises many types; all mean "can't use this link"
        raise _youtube_error(exc) from exc
    return {
        "title": str(info.get("title") or "YouTube video")[:120],
        "duration": float(info.get("duration") or 0),
        "live": bool(info.get("is_live")) or info.get("live_status") in ("is_live", "is_upcoming"),
    }


def progress_hook(run, every: float = 3.0):
    """A yt-dlp progress hook that shows the download on the run (part, percent, speed, time left)
    and keeps the run's lease alive; it saves at most every `every` seconds."""
    last = [0.0]

    def hook(status: dict):
        if status.get("status") != "downloading" or time.monotonic() - last[0] < every:
            return
        last[0] = time.monotonic()
        total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
        info = status.get("info_dict") or {}
        run.output["download"] = {
            "part": "sound" if info.get("vcodec") == "none" else "video",
            "percent": int(100 * (status.get("downloaded_bytes") or 0) / total) if total else 0,
            "speed": int(status.get("speed") or 0),
            "eta": int(status["eta"]) if status.get("eta") is not None else None,
        }
        base._save(run)
        base.keep_alive(run)

    return hook


def download_youtube(url: str, folder: Path, run=None) -> Path:
    """Download a YouTube video (up to 1080p) as folder/source.mp4. Raises RuntimeError."""
    import yt_dlp

    options = _ytdlp_options(
        format="bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080][ext=mp4]/bv*[height<=1080]+ba/b[height<=1080]/b",
        merge_output_format="mp4",
        outtmpl=str(folder / "source.%(ext)s"),
        max_filesize=settings.CLIPS_MAX_DOWNLOAD_BYTES,
        progress_hooks=[progress_hook(run)] if run is not None else [],
    )
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])
    except base.RunCancelled:
        raise
    except Exception as exc:  # noqa: BLE001
        if run is not None and not type(run).objects.filter(id=run.id, status="running").exists():
            raise base.RunCancelled from exc  # yt-dlp wrapped our cancel from the progress hook
        raise _youtube_error(exc) from exc
    target = folder / "source.mp4"
    if not target.exists():
        raise RuntimeError("The YouTube download didn't finish. Please try again.")
    return target


# ── transcription ─────────────────────────────────────────────────────────


def silences(audio: Path) -> list[float]:
    """Middle of each pause (>= 0.4 s) in the audio, in seconds."""
    out = render._run(["ffmpeg", "-i", str(audio), "-af", "silencedetect=noise=-35dB:d=0.4", "-f", "null", "-"],
                      timeout=1800).stderr
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    return [round((a + b) / 2, 3) for a, b in zip(starts, ends)]


def chunk_bounds(duration: float, pauses: list[float], target: int = CHUNK_SECONDS, window: int = 30) -> list[tuple]:
    """Split [0, duration] into pieces of about `target` seconds, cutting at the pause nearest each mark."""
    bounds, pos = [], 0
    while duration - pos > target:
        mark = pos + target
        near = [p for p in pauses if abs(p - mark) <= window and p > pos]
        cut = min(near, key=lambda p: abs(p - mark)) if near else mark
        bounds.append((pos, cut))
        pos = cut
    bounds.append((pos, duration))
    return bounds


def punctuate(words: list[dict], segments: list[dict]) -> list[dict]:
    """Put sentence punctuation back on word timings (Whisper word timestamps come without it)."""
    words = [dict(w) for w in words]
    for n, seg in enumerate(segments):
        last = n == len(segments) - 1
        inside = [w for w in words if w["start"] >= seg["start"] and (w["start"] < seg["end"] or last)]
        tokens = str(seg.get("text") or "").split()
        if not inside or not tokens:
            continue
        if len(tokens) == len(inside):
            for w, token in zip(inside, tokens):
                w["word"] = token
        elif tokens[-1][-1] in ".?!" and inside[-1]["word"][-1:] not in ".?!":
            inside[-1]["word"] += tokens[-1][-1]
    return words


def _groq_words(audio: Path, language: str) -> list[dict]:
    for attempt in range(3):
        response = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}"},
            files={"file": (audio.name, audio.read_bytes(), "audio/mpeg")},
            data={"model": settings.CLIPS_GROQ_MODEL, "response_format": "verbose_json", "language": language,
                  "timestamp_granularities[]": ["word", "segment"]},
            timeout=300,
        )
        if response.status_code == 429 and attempt < 2:  # free tier rate limit: wait as told
            time.sleep(min(float(response.headers.get("retry-after") or 20), 60))
            continue
        if response.status_code != 200:
            raise RuntimeError(f"Groq answered {response.status_code}")
        data = response.json()
        raw = [{"word": str(w.get("word", "")).strip(), "start": float(w["start"]), "end": float(w["end"])}
               for w in data.get("words") or [] if str(w.get("word", "")).strip()]
        return punctuate(raw, data.get("segments") or [])
    raise RuntimeError("Groq rate limit")


@lru_cache(maxsize=1)
def _local_model():
    from faster_whisper import WhisperModel

    return WhisperModel(settings.CLIPS_LOCAL_WHISPER_MODEL, device="cpu", compute_type="int8",
                        cpu_threads=os.cpu_count() or 4)  # its default is 4 threads


def _local_words(audio: Path, language: str) -> list[dict] | None:
    """Words from faster-whisper on our CPU (free), or None if it isn't installed."""
    try:
        model = _local_model()
    except ImportError:
        return None
    # Decode with FFmpeg ourselves: faster-whisper's own decoder breaks with PyAV 19.
    import numpy

    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio), "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"],
                         capture_output=True, check=True, timeout=900).stdout
    samples = numpy.frombuffer(raw, dtype=numpy.float32)
    segments, _info = model.transcribe(samples, language=language, word_timestamps=True, vad_filter=True)
    return [{"word": w.word.strip(), "start": float(w.start), "end": float(w.end)}
            for seg in segments for w in seg.words or [] if w.word.strip()]


def _fal_words(audio: Path, language: str) -> list[dict]:
    out = providers._fal(settings.AGENTS_WHISPER_MODEL, {"audio_url": providers._data_uri(audio), "chunk_level": "word",
                                                         "language": language})
    words = []
    for chunk in out.get("chunks") or []:
        word = str(chunk.get("text", "")).strip()
        start, end = (list(chunk.get("timestamp") or []) + [None, None])[:2]
        if word and start is not None:
            words.append({"word": word, "start": float(start), "end": float(end if end is not None else start)})
    return words


def transcribe_chunk(audio: Path, offset: float, language: str = "en") -> tuple[list[dict], str]:
    """Word timings for one audio piece, shifted by `offset`, from the first service that works.

    Every piece uses the same `language` (detecting it per piece mistook music for Welsh).
    Services are tried in CLIPS_TRANSCRIBE_PROVIDERS order: groq (free tier), local (faster-whisper on
    our CPU, free), fal (paid). Returns (words, service name). Raises RuntimeError.
    """
    tried = False
    for name in [n.strip() for n in settings.CLIPS_TRANSCRIBE_PROVIDERS.split(",") if n.strip()]:
        if (name == "groq" and not settings.GROQ_API_KEY) or (name == "fal" and not settings.FAL_KEY):
            continue
        try:
            words = {"groq": _groq_words, "local": _local_words, "fal": _fal_words}[name](audio, language)
        except KeyError:
            continue
        except Exception as exc:  # noqa: BLE001 — try the next service
            tried = True
            logger.warning("Transcription with %s failed: %s", name, exc)
            continue
        if words is None:  # local model not installed
            continue
        providers.note(name)
        shifted = [{"word": w["word"], "start": round(w["start"] + offset, 3), "end": round(w["end"] + offset, 3)}
                   for w in words]
        return shifted, name
    if tried:
        raise RuntimeError("The transcription services failed. Please try again later.")
    raise RuntimeError("No transcription service is set up on this server yet.")


# ── finding moments ───────────────────────────────────────────────────────


def sentences(words: list[dict]) -> list[dict]:
    """Group words into sentences: [{start, end, text, first, last}] (first/last are word indexes)."""
    out, first = [], 0
    for i, word in enumerate(words):
        ends = word["word"].rstrip("\"')]”’")[-1:] in (".", "?", "!")
        gap = i + 1 < len(words) and words[i + 1]["start"] - word["end"] > SENTENCE_GAP
        if ends or gap or i + 1 == len(words) or i - first + 1 >= MAX_SENTENCE_WORDS:
            group = words[first : i + 1]
            out.append({"start": group[0]["start"], "end": group[-1]["end"],
                        "text": " ".join(w["word"] for w in group), "first": first, "last": i})
            first = i + 1
    return out


def fit_clip(first: int, last: int, sents: list[dict], low: float, high: float, duration: float) -> dict | None:
    """Clip edges for sentences first..last, grown or trimmed to whole sentences within [low, high] seconds."""
    if not sents:
        return None
    first, last = max(0, min(first, len(sents) - 1)), max(0, min(last, len(sents) - 1))
    first, last = min(first, last), max(first, last)

    def span(a, b):
        return sents[b]["end"] - sents[a]["start"]

    while span(first, last) > high and last > first:
        last -= 1
    while span(first, last) < low and last + 1 < len(sents) and span(first, last + 1) <= high:
        last += 1
    while span(first, last) < low and first > 0 and span(first - 1, last) <= high:
        first -= 1
    if span(first, last) > high or span(first, last) < low * 0.6:
        return None
    start = sents[first]["start"] - LEAD
    if first > 0:
        start = max(start, sents[first - 1]["end"])
    end = sents[last]["end"] + TAIL
    if last + 1 < len(sents):
        end = min(end, sents[last + 1]["start"])
    return {"from": first, "to": last, "start": round(max(0.0, start), 3), "end": round(min(duration, end), 3)}


def dedupe(moments: list[dict]) -> list[dict]:
    """Best first; drop any moment that overlaps a better one by more than half of the shorter."""
    kept = []
    for m in sorted(moments, key=lambda m: -m["score"]):
        if all(min(m["end"], k["end"]) - max(m["start"], k["start"])
               <= 0.5 * min(m["end"] - m["start"], k["end"] - k["start"]) for k in kept):
            kept.append(m)
    return kept


def _clock(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}" if seconds >= 3600 else \
        f"{seconds // 60}:{seconds % 60:02d}"


def _windows(sents: list[dict]) -> list[list[int]]:
    """Sentence numbers per AI call: ~20 minutes each, overlapping by a minute so no moment is cut in two."""
    windows, start = [], 0
    while start < len(sents):
        end_time = sents[start]["start"] + WINDOW_SECONDS
        stop = start
        while stop < len(sents) and sents[stop]["end"] <= end_time:
            stop += 1
        stop = max(stop, start + 1)
        windows.append(list(range(start, stop)))
        if stop >= len(sents):
            break
        back = stop
        while back > start + 1 and sents[stop - 1]["end"] - sents[back - 1]["start"] < WINDOW_OVERLAP:
            back -= 1
        start = back
    return windows


def clip_language(config: dict) -> str:
    """The video's spoken language (ISO 639-1); English unless the agent is set otherwise."""
    language = str((config or {}).get("language") or "en").lower()
    return language if re.fullmatch(r"[a-z]{2}", language) else "en"


def clip_settings(config: dict) -> tuple[str, int, str]:
    """(length id, number of clips, layout) for a deployment config, with defaults."""
    config = config or {}
    length = config.get("clipLength") if config.get("clipLength") in CLIP_LENGTHS else "medium"
    try:
        count = int(config.get("clipCount"))
    except (TypeError, ValueError):
        count = 5
    layout = config.get("layout") if config.get("layout") in LAYOUTS else "auto"
    return length, min(max(count, CLIP_COUNTS.start), CLIP_COUNTS.stop - 1), layout


def _clean_moment(raw: dict, sents: list[dict], low: float, high: float, duration: float) -> dict | None:
    try:
        first, last = int(raw.get("from")), int(raw.get("to"))
        score = max(0, min(100, int(float(raw.get("score") or 0))))
    except (TypeError, ValueError):
        return None
    edges = fit_clip(first, last, sents, low, high, duration)
    if edges is None:
        return None
    text = " ".join(s["text"] for s in sents[edges["from"] : edges["to"] + 1])
    hook = " ".join(str(raw.get("hook") or "").split()[:8])[:80]
    span = [sents[edges["from"]]["first"], sents[edges["to"]]["last"]]  # word indexes, for caption edits
    return {**edges, "w": span, "score": score, "title": " ".join(str(raw.get("title") or "").split())[:90] or hook or text[:60],
            "hook": hook, "reason": " ".join(str(raw.get("reason") or "").split())[:200], "text": text[:2000]}


def _dry_moments(sents: list[dict], low: float, high: float, duration: float) -> list[dict]:
    moments, i = [], 0
    while i < len(sents):
        edges = fit_clip(i, i, sents, low, high, duration)
        if edges is None:
            break
        n = len(moments) + 1
        moments.append({"from": edges["from"], "to": edges["to"], "score": 90 - n * 5, "title": f"Moment {n}",
                        "hook": f"Moment {n}", "reason": "Dry run."})
        i = edges["to"] + 1
    return moments


# ── steps ─────────────────────────────────────────────────────────────────


def step_get_video(run) -> None:
    if run.output.get("clip_source"):
        return
    folder, rel = base.media_dir(run)
    if run.input.get("url"):
        target = download_youtube(run.input["url"], folder, run=run)
        title = run.input.get("title") or "YouTube video"
    else:
        asset = LibraryAsset.objects.filter(
            id=run.input.get("assetId"), project_id=run.project_id, media_type="video"
        ).first()
        if asset is None:
            raise RuntimeError("The video is no longer in your library.")
        suffix = Path(urlparse(asset.source_url or "").path).suffix.lower()
        target = folder / f"source{suffix if suffix in VIDEO_SUFFIXES else '.mp4'}"
        local = asset_file(asset)
        if local:
            shutil.copyfile(local, target)
        else:
            target.write_bytes(fetch_media(asset.source_url, timeout=600)[0])
        title = asset.title
    info = probe(target)
    if not info["has_audio"]:
        raise RuntimeError("This video has no sound, so there is nothing to find clips in.")
    if info["duration"] > max_seconds(run.user) + 5:
        raise RuntimeError(f"This video is longer than your plan allows ({max_seconds(run.user) // 60} minutes).")
    if info["duration"] < 10:
        raise RuntimeError("This video is too short to make clips from.")
    render._run(["ffmpeg", "-y", "-i", str(target), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k",
                 str(folder / "audio.mp3")], timeout=1800)
    run.output.update({"clip_source": f"{rel}/{target.name}", "clip_info": info, "clip_audio": f"{rel}/audio.mp3",
                       "source_title": (title or "")[:120]})
    base._save(run)


DRY_TEXT = ("Here is a bold claim about coffee. Most people brew it wrong every single morning. "
            "The fix takes ten seconds and costs nothing. Want to know what it is? Keep watching. ")


def step_transcribe_long(run) -> None:
    if "words" in run.output:
        return
    duration = run.output["clip_info"]["duration"]
    if settings.AGENTS_DRY_RUN:
        text = DRY_TEXT * max(1, round(duration / 14))
        run.output["words"] = render.estimate_word_times(text.strip(), duration)
        base._save(run)
        return
    folder, _rel = base.media_dir(run)
    audio = base.media_path(run.output["clip_audio"])
    done = run.output.setdefault("chunk_words", {})  # piece number -> words, so a restart resumes
    pieces = chunk_bounds(duration, silences(audio))
    used = set(run.output.get("transcribed_with") or [])
    for n, (a, b) in enumerate(pieces):
        if str(n) in done:
            continue
        piece = folder / f"piece-{n}.mp3"
        try:
            render._run(["ffmpeg", "-y", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", str(audio), "-ac", "1",
                         "-ar", "16000", "-b:a", "48k", str(piece)], timeout=600)
            words, name = transcribe_chunk(piece, offset=a, language=clip_language(base._config(run)))
        finally:
            piece.unlink(missing_ok=True)
        done[str(n)] = words
        used.add(name)
        run.output["transcribed_with"] = sorted(used)
        base._save(run)
        base.keep_alive(run)
    words = [w for n in range(len(pieces)) for w in done[str(n)]]
    if len(words) < 20:
        raise RuntimeError("We couldn't hear enough speech in this video to find clips.")
    run.output["words"] = words
    run.output.pop("chunk_words", None)
    base._save(run)


def step_find_clips(run) -> None:
    if "moments" in run.output:
        return
    duration = run.output["clip_info"]["duration"]
    length, count, _layout = clip_settings(base._config(run))
    _label, low, high = CLIP_LENGTHS[length]
    sents = sentences(run.output["words"])
    if settings.AGENTS_DRY_RUN:
        raw = _dry_moments(sents, low, high, duration)
    else:
        raw = []
        brand = base._brand_lines(run)
        for window in _windows(sents):
            lines = "\n".join(f"[{i}] ({_clock(sents[i]['start'])}) {sents[i]['text']}" for i in window)
            answer = providers.text(CLIPS_PROMPT.format(low=low, high=high, count=count),
                                    f"{brand}Transcript:\n{lines}", temperature=0.4)
            found = answer.get("clips") if isinstance(answer, dict) else None
            raw += [c for c in found or [] if isinstance(c, dict)]
            base.keep_alive(run)
    moments = dedupe([m for c in raw if (m := _clean_moment(c, sents, low, high, duration))])[:count]
    if not moments:
        raise RuntimeError("We couldn't find a moment that works as a clip in this video.")
    for m in moments:
        m["keep"] = True
    run.output["moments"] = moments
    base._save(run)


def step_review_clips(run) -> None:
    if run.output.get("clips_ok"):
        return
    if not base._checkpoints(run):
        run.output["clips_ok"] = True
        base._save(run)
        return
    raise base.NeedsReview("clips")


def caption_fixes(words: list[dict], first: int, last: int, text: str) -> dict:
    """{word index: new text} that turns words[first..last] into `text`, keeping every word's timing.

    Changed words are replaced; a deleted word becomes "" (not shown); an added word joins the word
    before it; several words rewritten as fewer (or more) go on the first of them.
    """
    old = [w["word"] for w in words[first : last + 1]]
    new = text.split()
    fixes = {}
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        if op == "insert":
            at = max(i1 - 1, 0)
            current = fixes.get(first + at, old[at])
            fixes[first + at] = " ".join([*new[j1:j2], current] if i1 == 0 else [current, *new[j1:j2]])
        elif op == "replace" and i2 - i1 == j2 - j1:
            fixes.update({first + i1 + k: new[j1 + k] for k in range(i2 - i1)})
        else:  # delete, or a different number of words
            fixes[first + i1] = " ".join(new[j1:j2])
            fixes.update({first + k: "" for k in range(i1 + 1, i2)})
    return fixes


def fixed_words(words: list[dict], fixes: dict) -> list[dict]:
    """Words with the user's caption fixes applied (timings unchanged)."""
    return [{**w, "word": fixes[str(i)]} if str(i) in fixes else w for i, w in enumerate(words)]


def clip_words(words: list[dict], start: float, end: float) -> list[dict]:
    """The words inside [start, end], timed from the clip's start."""
    return [{"word": w["word"], "start": round(max(0.0, w["start"] - start), 3), "end": round(w["end"] - start, 3)}
            for w in words if w["start"] >= start - 0.05 and w["end"] <= end + 0.05]


# id -> (label, words per line, font size, UPPERCASE, highlight: "colour" | "box" | None, height from bottom)
CAPTION_STYLES = {
    "classic": ("Classic · white, the spoken word in your brand colour", 3, 78, False, "colour", 0.27),
    "bold": ("Bold · big uppercase, two words at a time", 2, 96, True, "colour", 0.30),
    "boxed": ("Boxed · the spoken word in a brand-colour box", 3, 80, False, "box", 0.27),
    "minimal": ("Minimal · smaller, lower, no highlight", 5, 60, False, None, 0.16),
}


def caption_style(config: dict) -> str:
    style = (config or {}).get("captionStyle")
    return style if style in CAPTION_STYLES else "classic"


def _styled_captions(words: list[dict], duration: float, highlight: str, style: str) -> str:
    """ASS captions in one of the CAPTION_STYLES (classic is the Shorts look from render.build_captions)."""
    width, height = render.WIDTH, render.HEIGHT
    if style == "classic":
        return render.build_captions([{"words": words, "duration": duration}], highlight, (width, height))
    _label, per_line, size, upper, mode, lift = CAPTION_STYLES[style]
    head = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
        "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Cap,DejaVu Sans,{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,"
        f"100,100,0,0,1,{8 if upper else 6},2,2,60,60,{round(height * lift)},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    color = render._ass_color(highlight)
    words = [w for w in words if w.get("word")]
    lines = []
    for i in range(0, len(words), per_line):
        group = words[i : i + per_line]
        texts = [render._ass_text(w["word"].upper() if upper else w["word"]) for w in group]
        for k, current in enumerate(group):
            end = group[k + 1]["start"] if k + 1 < len(group) else current["end"]
            if mode == "colour":
                shown = [f"{{\\c{color}}}{t}{{\\c&H00FFFFFF&}}" if j == k else t for j, t in enumerate(texts)]
            elif mode == "box":  # a thick outline in the brand colour reads as a box behind the word
                shown = [f"{{\\3c{color}&\\bord14}}{t}{{\\3c&H00000000&\\bord6}}" if j == k else t
                         for j, t in enumerate(texts)]
            else:
                shown = texts
            lines.append(f"Dialogue: 0,{render._ass_time(current['start'])},"
                         f"{render._ass_time(max(end, current['start'] + 0.05))},Cap,,0,0,0,,{' '.join(shown)}")
    return head + "\n".join(lines) + "\n"


def clip_ass(words: list[dict], hook: str, duration: float, highlight: str, style: str = "classic") -> str:
    """Captions in the chosen style, plus the hook in a box at the top for the first seconds."""
    ass = _styled_captions(words, duration, highlight, style)
    if not hook:
        return ass
    hook_style = (f"Style: Hook,DejaVu Sans,66,&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,"
                  f"100,100,0,0,3,18,0,8,90,90,{round(render.HEIGHT * 0.11)},1")
    ass = ass.replace("\n\n[Events]", "\n" + hook_style + "\n\n[Events]", 1)
    end = render._ass_time(min(HOOK_SECONDS, duration))
    return ass + f"Dialogue: 1,0:00:00.00,{end},Hook,,0,0,0,,{render._ass_text(hook)}\n"


def _burn(captions: Path) -> str:
    return f"ass='{captions}':fontsdir='{Path(settings.AGENTS_CAPTION_FONT).parent}'"


def _video_filter(layout: str, captions: Path) -> str:
    w, h = render.WIDTH, render.HEIGHT
    if layout == "fit":
        picture = (f"split[a][b];[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
                   f"boxblur=24:2,eq=brightness=-0.12[bg];[b]scale={w}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    else:
        ratio = w / h
        picture = (f"crop='if(gt(iw/ih,{ratio:.5f}),ih*{ratio:.5f},iw)':'if(gt(iw/ih,{ratio:.5f}),ih,iw/{ratio:.5f})',"
                   f"scale={w}:{h}")
    return f"[0:v]fps={render.FPS},{picture},setsar=1,{_burn(captions)}[v]"


TIGHT_PAUSE = 0.6  # with "tighten", pauses between words longer than this are cut (keeping 0.2 s each side)


def tight_cuts(words: list[dict], length: float) -> list[dict]:
    """Long pauses between words and um/uh inside a clip (clip-relative words)."""
    cuts = [{"start": a["end"] + video_edit.PAD, "end": b["start"] - video_edit.PAD, "reasons": ["pause"]}
            for a, b in zip(words, words[1:]) if b["start"] - a["end"] > TIGHT_PAUSE]
    cuts += video_edit.filler_cuts(words, "normal", length)
    return video_edit.merge_cuts(cuts, length) if cuts else []


def map_time(t: float, segments: list[tuple]) -> float:
    """A time on the clip → the same moment on the tightened clip (inside a cut: where the cut is)."""
    offset = 0.0
    for a, b in segments:
        if t < a:
            return round(offset, 3)
        if t <= b:
            return round(offset + t - a, 3)
        offset += b - a
    return round(offset, 3)


def _encode(source: Path, start: float, length: float, graph: str, out: Path) -> None:
    render._run([
        "ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(source),
        "-filter_complex", graph, "-map", "[v]", "-map", "0:a:0",
        "-af", "aresample=44100,loudnorm=I=-14:TP=-1.5:LRA=11", "-r", str(render.FPS),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", str(out),
    ], timeout=1800)


def _cut(full: Path, segments: list[tuple], captions: Path, out: Path) -> None:
    """Second pass for "tighten": keep only `segments` of the framed clip, then burn the captions."""
    fps = render.FPS
    select = "+".join(f"between(t,{a:.4f},{b - 0.5 / fps:.4f})" for a, b in segments)
    graph = [f"[0:v]select='{select}',setpts=N/{fps}/TB,{_burn(captions)}[v]",
             f"[0:a]asplit={len(segments)}" + "".join(f"[s{i}]" for i in range(len(segments)))]
    for i, (a, b) in enumerate(segments):
        fade = min(0.03, (b - a) / 3)
        graph.append(f"[s{i}]atrim={a:.4f}:{b:.4f},asetpts=PTS-STARTPTS,afade=t=in:d={fade:.3f},"
                     f"afade=t=out:st={b - a - fade:.4f}:d={fade:.3f}[p{i}]")
    graph.append("".join(f"[p{i}]" for i in range(len(segments))) + f"concat=n={len(segments)}:v=0:a=1[a]")
    render._run([
        "ffmpeg", "-y", "-i", str(full), "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]",
        "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", str(out),
    ], timeout=1800)


def render_clip(source: Path, moment: dict, words: list[dict], layout: str, highlight: str, out: Path,
                workdir: Path, style: str = "classic", tighten: bool = False) -> float:
    """One vertical clip with captions and hook; returns its length.

    With `tighten`, the framed clip is made first, then pauses and ums are cut and captions retimed.
    """
    length = moment["end"] - moment["start"]
    spoken = clip_words(words, moment["start"], moment["end"])
    hook = moment.get("hook", "")
    segments = video_edit.kept_segments(tight_cuts(spoken, length), length) if tighten else None
    if segments and length - sum(b - a for a, b in segments) < 0.3:
        segments = None  # nothing worth cutting
    captions = workdir / f"{out.stem}.ass"
    graph, seams = None, []
    if layout == "auto":
        info = probe(source)
        if info["width"] / max(info["height"], 1) > render.WIDTH / render.HEIGHT + 0.01:  # wider than vertical
            samples = reframe.analyze(source, moment["start"], length, info["width"], info["height"])
            shots = reframe.plan_shots(samples, info["width"], info["height"], length)
            seams = [(s["start"], s["end"]) for s in shots if s["layout"] == "split"]
            graph = reframe.video_filter(shots, info["width"], info["height"], workdir) + f";[vr]{_burn(captions)}[v]"
    graph = graph or _video_filter("crop" if layout == "auto" else layout, captions)
    if not segments:
        captions.write_text(reframe.seam_captions(clip_ass(spoken, hook, length, highlight, style), seams),
                            encoding="utf-8")
        _encode(source, moment["start"], length, graph, out)
        return length
    captions.write_text(clip_ass([], "", length, highlight, style), encoding="utf-8")  # pass 1: picture only
    full = workdir / f"{out.stem}-full.mp4"
    _encode(source, moment["start"], length, graph, full)
    tight = round(sum(b - a for a, b in segments), 3)
    ass = clip_ass(video_edit.retime(spoken, segments), hook, tight, highlight, style)
    seams = [(map_time(a, segments), map_time(b, segments)) for a, b in seams]
    captions.write_text(reframe.seam_captions(ass, seams), encoding="utf-8")
    _cut(full, segments, captions, out)
    full.unlink(missing_ok=True)
    return tight


def step_render_clips(run) -> None:
    out = run.output
    chosen = [m for m in out.get("moments") or [] if m.get("keep")]
    made = out.setdefault("clips", [])
    if len(made) >= len(chosen):
        return
    folder, rel = base.media_dir(run)
    source = base.media_path(out["clip_source"])
    layout = clip_settings(base._config(run))[2]
    workdir = folder / "work"
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        for n, moment in enumerate(chosen):
            if n < len(made):
                continue  # rendered before a restart
            clip = {key: moment.get(key) for key in ("start", "end", "score", "title", "hook", "reason", "text")}
            video = folder / f"clip-{n + 1}.mp4"
            try:
                render_clip(source, moment, fixed_words(out["words"], out.get("caption_fixes") or {}), layout, base.highlight(run), video, workdir,
                            style=caption_style(base._config(run)), tighten=bool(base._config(run).get("tighten")))
                result = render.check_video(video, expect_sound=not settings.AGENTS_DRY_RUN)
                # The clip's own frame already shows the hook and captions: no second title on top.
                render._run(["ffmpeg", "-y", "-ss", f"{min(1.0, result['duration'] / 2):.2f}", "-i", str(video),
                             "-frames:v", "1", "-q:v", "3", str(folder / f"clip-{n + 1}.jpg")])
                clip.update({"video": f"{rel}/{video.name}", "thumbnail": f"{rel}/clip-{n + 1}.jpg",
                             "duration": result["duration"], "checks": result["checks"]})
            except render.RenderError as exc:  # one bad clip must not sink the others
                logger.warning("Clip %s of run %s failed: %s", n + 1, run.id, exc)
                clip["error"] = str(exc)
            made.append(clip)
            base._save(run)
            base.keep_alive(run)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    if not any(c.get("video") for c in made):
        raise RuntimeError("None of the clips could be made. Please try again.")


def step_finish_clips(run) -> None:
    """Put every finished clip in the project library (once each)."""
    for clip in run.output.get("clips") or []:
        if not clip.get("video") or clip.get("assetId"):
            continue
        asset = LibraryAsset.objects.create(
            project_id=run.project_id,
            user_id=run.user_id,
            media_type="video",
            title=(clip.get("title") or "Clip")[:255],
            status="ready",
            source_url=absolute_media_url(clip["video"]),
            thumbnail_url=absolute_media_url(clip["thumbnail"]),
            prompt=clip.get("text", "")[:2000],
            model=f"agent:{run.deployment.agent_type}",
            capability="agent",
            duration_seconds=round(clip.get("duration") or 0),
            width=render.WIDTH,
            height=render.HEIGHT,
        )
        clip["assetId"] = str(asset.id)
        if not run.library_asset_id:
            run.library_asset = asset
        base._save(run, fields=("output", "library_asset"))


STEPS = {
    "get_video": step_get_video,
    "transcribe_long": step_transcribe_long,
    "find_clips": step_find_clips,
    "review_clips": step_review_clips,
    "render_clips": step_render_clips,
    "finish_clips": step_finish_clips,
}
