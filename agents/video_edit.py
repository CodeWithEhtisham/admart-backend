"""Video Editor agent: clean up a user's own video.

prepare → transcribe → clean_audio → plan_edit → review_edit → render_edit → package (→ finish)

Cuts are planned on the source timeline as [{start, end, reasons, keep}]; the user can keep any of
them at the review check-in. Rendering keeps everything else, snapped to the 30 fps frame grid so
picture and sound stay in sync across many cuts. Plan: docs/plans/2026-10-13-video-editor-agent.md
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings

from agents import hooks, providers, render
from agents import steps as base
from agents.registry import AUDIO_LEVELS, CUT_STYLES, FORMATS, MAX_VIDEO_SECONDS, video_settings
from content.models import LibraryAsset
from content.url_resolve import fetch_media, media_file

logger = logging.getLogger(__name__)

FPS = render.FPS
PAD = 0.2  # seconds of pause kept on each side of a cut pause
MIN_SEGMENT = 0.3  # never keep a sliver shorter than this
FILLERS = {"um", "uh", "erm", "er", "ah", "hmm", "umm", "uhm", "mm"}
TIGHT_FILLERS = FILLERS | {"like"}
RETAKE_SHARE = {"gentle": 0.1, "normal": 0.15, "tight": 0.3}  # most of the video retake cuts may remove
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".m4v"}

EDIT_PROMPT = """You edit short talking videos. You get the transcript as numbered words ("index:word").
Find:
1. retakes: where the speaker stops and restarts a sentence, or says the same phrase twice. Return the
   word range of the abandoned attempt (inclusive). Keep the last complete attempt.
2. fixes: caption spelling mistakes only (names, brands, technical terms, wrong homophones). Keep the
   speaker's words and meaning; do not rephrase or fix grammar.
Return JSON only: {"retakes": [{"from": int, "to": int}], "fixes": [{"index": int, "word": string}]}
Return empty lists when there is nothing to change."""

PACKAGE_PROMPT = f"""You package a short social video from its transcript.
Return JSON only: {{"title": string, "thumbnail_text": string, "description": string, "tags": [string]}}
- title: {base.TITLE_RULES}.
- thumbnail_text: 2-4 punchy words that add to the title; never repeat its words.
- description: 2-3 sentences that make people want to watch, using only what is said in the video.
- tags: up to 12 short tags without the # sign.
Never invent facts, numbers or claims that are not in the transcript. Write in the brand tone if given."""


# ── helpers ───────────────────────────────────────────────────────────────


def asset_file(asset: LibraryAsset) -> Path | None:
    """The uploaded video on our disk, or None if it isn't stored locally."""
    try:
        return media_file(asset.source_url or "")
    except ValueError:
        return None


def probe(path: Path) -> dict:
    """Duration, display size (rotation applied) and whether there is sound. Raises RuntimeError."""
    try:
        out = render._run([
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,width,height:stream_tags=rotate:stream_side_data=rotation",
            "-of", "json", str(path),
        ])
        data = json.loads(out.stdout or "{}")
    except (render.RenderError, ValueError) as exc:
        raise RuntimeError("We couldn't read this video file. Try exporting it as MP4.") from exc
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video:
        raise RuntimeError("This file has no picture. Upload a video file.")
    width, height = int(video.get("width") or 0), int(video.get("height") or 0)
    rotation = (video.get("tags") or {}).get("rotate") or next(
        (d.get("rotation") for d in video.get("side_data_list") or [] if "rotation" in d), 0
    )
    if abs(int(float(rotation or 0))) % 180 == 90:  # phones store portrait video sideways
        width, height = height, width
    return {
        "duration": round(float((data.get("format") or {}).get("duration") or 0), 3),
        "width": width,
        "height": height,
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def _norm(word: str) -> str:
    return re.sub(r"[^a-z']", "", word.lower())


def _frame(t: float) -> float:
    return round(round(t * FPS) / FPS, 4)


def _neighbours(words: list[dict], i: int, duration: float) -> tuple[float, float]:
    """Where word i may be cut from/to without clipping the words around it."""
    prev_end = words[i - 1]["end"] if i > 0 else 0.0
    next_start = words[i + 1]["start"] if i + 1 < len(words) else duration
    return prev_end, next_start


def pause_cuts(audio: Path, min_gap: float, duration: float) -> list[dict]:
    """Pauses longer than min_gap, shortened to PAD on each side."""
    log = render._run(["ffmpeg", "-i", str(audio), "-af", f"silencedetect=noise=-35dB:d={min_gap}", "-f", "null", "-"]).stderr
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    cuts = []
    for i, start in enumerate(starts):
        end = ends[i] if i < len(ends) else duration
        a = 0.0 if start <= 0.05 else start + PAD  # leading/trailing silence goes completely
        b = duration if end >= duration - 0.05 else end - PAD
        if b - a > 0.05:
            cuts.append({"start": a, "end": b, "reasons": ["pause"]})
    return cuts


def filler_cuts(words: list[dict], cut: str, duration: float) -> list[dict]:
    fillers = TIGHT_FILLERS if cut == "tight" else FILLERS
    cuts = []
    for i, w in enumerate(words):
        if _norm(w["word"]) in fillers:
            prev_end, next_start = _neighbours(words, i, duration)
            cuts.append({"start": max(prev_end, w["start"] - 0.04), "end": min(next_start, w["end"] + 0.04),
                         "reasons": ["filler"]})
    return cuts


def frame_cuts(source: Path, words: list[dict]) -> list[dict]:
    """Black or frozen stretches where nothing is said (a frozen slide with narration stays)."""
    log = render._run([
        "ffmpeg", "-i", str(source), "-an", "-vf",
        "scale=320:-2,blackdetect=d=0.3:pic_th=0.98,freezedetect=n=-60dB:d=1.5", "-f", "null", "-",
    ]).stderr
    spans = [(float(a), float(b), "black frames") for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", log)]
    f_starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", log)]
    f_ends = [float(x) for x in re.findall(r"freeze_end: ([\d.]+)", log)]
    spans += [(a, b, "frozen frames") for a, b in zip(f_starts, f_ends)]
    return [
        {"start": a, "end": b, "reasons": [reason]}
        for a, b, reason in spans
        if not any(w["start"] < b and w["end"] > a for w in words)
    ]


def ai_review(run, words: list[dict], cut: str, duration: float) -> tuple[list[dict], list[dict]]:
    """Retake cuts and caption spelling fixes from one AI call."""
    listing = " ".join(f"{i}:{w['word']}" for i, w in enumerate(words))[:20000]
    raw = providers.text(EDIT_PROMPT, f"{base._brand_lines(run)}Words:\n{listing}", temperature=0.2)
    budget = duration * RETAKE_SHARE.get(cut, 0.15)
    cuts = []
    for item in raw.get("retakes") or []:
        try:
            a, b = int(item["from"]), int(item["to"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (0 <= a <= b < len(words)) or b - a > 40:
            continue
        start = max(_neighbours(words, a, duration)[0], words[a]["start"] - 0.04)
        end = min(_neighbours(words, b, duration)[1], words[b]["end"] + 0.04)
        if end - start <= budget:
            budget -= end - start
            cuts.append({"start": start, "end": end, "reasons": ["retake"]})
    fixes = []
    for item in raw.get("fixes") or []:
        try:
            i, word = int(item["index"]), " ".join(str(item["word"]).split())[:40]
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= i < len(words) and word and word != words[i]["word"]:
            fixes.append({"index": i, "from": words[i]["word"], "to": word})
    return cuts, fixes


def merge_cuts(cuts: list[dict], duration: float) -> list[dict]:
    """Clamp, sort and merge overlapping cuts; absorb kept slivers shorter than MIN_SEGMENT."""
    spans = sorted(
        ({"start": max(0.0, c["start"]), "end": min(duration, c["end"]), "reasons": list(c["reasons"])} for c in cuts),
        key=lambda c: c["start"],
    )
    merged: list[dict] = []
    for c in spans:
        if c["end"] - c["start"] < 0.05:
            continue
        gap_to_last = c["start"] - merged[-1]["end"] if merged else c["start"]
        if merged and gap_to_last < MIN_SEGMENT:
            last = merged[-1]
            last["end"] = max(last["end"], c["end"])
            last["reasons"] = sorted(set(last["reasons"]) | set(c["reasons"]))
            continue
        if not merged and gap_to_last < MIN_SEGMENT:
            c["start"] = 0.0
        merged.append(c)
    if merged and duration - merged[-1]["end"] < MIN_SEGMENT:
        merged[-1]["end"] = duration
    return [{"start": round(c["start"], 3), "end": round(c["end"], 3), "reasons": c["reasons"], "keep": False}
            for c in merged]


def kept_segments(cuts: list[dict], duration: float) -> list[tuple[float, float]]:
    """The parts of the source that stay, snapped to the frame grid."""
    segments, pos = [], 0.0
    for c in sorted((c for c in cuts if not c.get("keep")), key=lambda c: c["start"]):
        if c["start"] > pos:
            segments.append((pos, c["start"]))
        pos = max(pos, c["end"])
    if pos < duration:
        segments.append((pos, duration))
    snapped = [(_frame(a), _frame(b)) for a, b in segments]
    return [(a, b) for a, b in snapped if b - a >= 1 / FPS]


def retime(words: list[dict], segments: list[tuple[float, float]]) -> list[dict]:
    """Words that survive the cuts, on the edited timeline."""
    out, offset = [], 0.0
    for a, b in segments:
        for w in words:
            if a <= w["start"] < b:
                out.append({"word": w["word"], "start": round(offset + w["start"] - a, 3),
                            "end": round(offset + min(w["end"], b) - a, 3)})
        offset += b - a
    return out


def _output_size(fmt: str, info: dict) -> tuple[int, int]:
    size = FORMATS[fmt][1]
    if size:
        return size
    w, h = info["width"] or 1080, info["height"] or 1920
    scale = min(1.0, 1920 / max(w, h))
    return max(2, round(w * scale / 2) * 2), max(2, round(h * scale / 2) * 2)


# ── steps ─────────────────────────────────────────────────────────────────


def step_prepare(run) -> None:
    if run.output.get("source"):
        return
    asset = LibraryAsset.objects.filter(
        id=run.input.get("assetId"), project_id=run.project_id, media_type="video"
    ).first()
    if asset is None:
        raise RuntimeError("The video is no longer in your library.")
    folder, rel = base.media_dir(run)
    suffix = Path(urlparse(asset.source_url or "").path).suffix.lower()
    target = folder / f"source{suffix if suffix in VIDEO_SUFFIXES else '.mp4'}"
    local = asset_file(asset)
    if local:
        shutil.copyfile(local, target)
    else:
        target.write_bytes(fetch_media(asset.source_url, timeout=300)[0])
    info = probe(target)
    if not info["has_audio"]:
        raise RuntimeError("This video has no sound, so there is nothing to clean up or caption.")
    if info["duration"] > MAX_VIDEO_SECONDS + 1:
        raise RuntimeError("The Video Editor takes videos up to 3 minutes.")
    if info["duration"] < 2:
        raise RuntimeError("This video is too short to edit.")
    render._run(["ffmpeg", "-y", "-i", str(target), "-vn", "-ac", "1", "-ar", "44100", "-b:a", "160k",
                 str(folder / "audio.mp3")])
    run.output.update({"source": f"{rel}/{target.name}", "source_info": info, "audio": f"{rel}/audio.mp3",
                       "source_title": asset.title})
    base._save(run)


def step_transcribe(run) -> None:
    if "words" in run.output:
        return
    duration = run.output["source_info"]["duration"]
    if settings.AGENTS_DRY_RUN:
        words = render.estimate_word_times(
            "Um so this is a dry run of the video editor. This line this line repeats and then it ends.", duration
        )
    else:
        words = providers.word_times(base.media_path(run.output["audio"])) or []
    run.output["words"] = words
    base._save(run)


def step_clean_audio(run) -> None:
    if run.output.get("audio_clean"):
        return
    folder, rel = base.media_dir(run)
    source = base.media_path(run.output["audio"])
    out = folder / "audio-clean.mp3"
    level = video_settings(base._config(run))[2]
    model, used = AUDIO_LEVELS[level][1], "basic"
    fallback = False
    if model and not settings.AGENTS_DRY_RUN:
        fallback = True  # until the paid service gives a usable track
        try:
            out.write_bytes(providers.clean_audio(source, model))
            # The cleaned track must line up with the picture; anything else falls back.
            if abs(render.duration_of(out) - render.duration_of(source)) <= 0.25:
                used, fallback = level, False
            else:
                logger.warning("Cleaned audio length changed; using the basic filter instead")
        except RuntimeError:
            logger.warning("Audio cleanup service failed; using the basic filter instead", exc_info=True)
    if used == "basic":
        render._run(["ffmpeg", "-y", "-i", str(source), "-af", "highpass=f=80,afftdn=nf=-25", "-ac", "1",
                     "-ar", "44100", "-b:a", "160k", str(out)])
    run.output.update({"audio_clean": f"{rel}/audio-clean.mp3", "audio_level": level, "audio_level_used": used,
                       "audio_fallback": fallback})
    base._save(run)


def step_plan_edit(run) -> None:
    if "cuts" in run.output:
        return
    duration = run.output["source_info"]["duration"]
    words = run.output.get("words") or []
    cut = video_settings(base._config(run))[1]
    cuts = pause_cuts(base.media_path(run.output["audio_clean"]), CUT_STYLES[cut][1], duration)
    cuts += filler_cuts(words, cut, duration)
    cuts += frame_cuts(base.media_path(run.output["source"]), words)
    fixes = []
    if words and not settings.AGENTS_DRY_RUN:
        retakes, fixes = ai_review(run, words, cut, duration)
        cuts += retakes
    captions = [dict(w) for w in words]
    for fix in fixes:
        captions[fix["index"]]["word"] = fix["to"]
    run.output.update({"cuts": merge_cuts(cuts, duration), "captions": captions, "caption_fixes": fixes})
    base._save(run)


def step_review_edit(run) -> None:
    if run.output.get("edit_ok"):
        return
    if not base._checkpoints(run):
        run.output["edit_ok"] = True
        base._save(run)
        return
    raise base.NeedsReview("edit")


def step_render_edit(run) -> None:
    if run.output.get("video"):
        return
    folder, rel = base.media_dir(run)
    info = run.output["source_info"]
    segments = kept_segments(run.output["cuts"], info["duration"])
    if sum(b - a for a, b in segments) < 1:
        raise RuntimeError("The edit would remove almost everything. Keep some of the cuts and try again.")
    config = base._config(run)
    fmt = video_settings(config)[0]
    width, height = _output_size(fmt, info)
    words = retime(run.output.get("captions") or [], segments) if config.get("captions", True) else []
    music = base._music_track(run) if config.get("music", False) else None
    workdir = folder / "work"
    workdir.mkdir(parents=True, exist_ok=True)
    total = round(sum(b - a for a, b in segments), 3)
    try:
        select = "+".join(f"between(t,{a:.4f},{b - 0.5 / FPS:.4f})" for a, b in segments)
        ratio = width / height
        video = (f"[0:v]fps={FPS},select='{select}',setpts=N/{FPS}/TB,"
                 f"crop='if(gt(iw/ih,{ratio:.5f}),ih*{ratio:.5f},iw)':'if(gt(iw/ih,{ratio:.5f}),ih,iw/{ratio:.5f})',"
                 f"scale={width}:{height},setsar=1")
        if words:
            captions = workdir / "captions.ass"
            captions.write_text(render.build_captions([{"words": words, "duration": total}], base.highlight(run),
                                                      (width, height)), encoding="utf-8")
            video += f",ass='{captions}':fontsdir='{Path(settings.AGENTS_CAPTION_FONT).parent}'"
        graph = [video + "[vout]", f"[1:a]asplit={len(segments)}" + "".join(f"[s{i}]" for i in range(len(segments)))]
        for i, (a, b) in enumerate(segments):
            fade = min(0.03, (b - a) / 3)
            graph.append(f"[s{i}]atrim={a:.4f}:{b:.4f},asetpts=PTS-STARTPTS,afade=t=in:d={fade:.3f},"
                         f"afade=t=out:st={b - a - fade:.4f}:d={fade:.3f}[p{i}]")
        graph.append("".join(f"[p{i}]" for i in range(len(segments))) + f"concat=n={len(segments)}:v=0:a=1[voice]")
        inputs = ["-i", str(base.media_path(run.output["source"])), "-i", str(base.media_path(run.output["audio_clean"]))]
        if music:
            inputs += ["-stream_loop", "-1", "-i", str(music)]
            graph += [
                f"[2:a]atrim=0:{total:.3f},aresample=44100,aformat=channel_layouts=mono,volume=0.25[bed]",
                "[voice]asplit=2[vo][key]",
                "[bed][key]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[duck]",
                "[vo][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[aout]",
            ]
        else:
            graph.append("[voice]loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
        out = folder / "edited.mp4"
        render._run([
            "ffmpeg", "-y", *inputs, "-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "[aout]",
            "-t", f"{total:.3f}", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", str(out),
        ], timeout=1800)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    result = render.check_video(out, expect_sound=not settings.AGENTS_DRY_RUN, size=(width, height))
    run.output.update({
        "video": f"{rel}/edited.mp4", "duration": result["duration"], "checks": result["checks"],
        "width": width, "height": height, "music": music.name if music else None,
        "removed_seconds": round(info["duration"] - total, 1),
    })
    base._save(run)


def step_package(run) -> None:
    if run.output.get("thumbnail"):
        return
    folder, rel = base.media_dir(run)
    transcript = " ".join(w["word"] for w in run.output.get("captions") or [])
    if settings.AGENTS_DRY_RUN or not transcript:
        name = run.output.get("source_title") or "My video"
        raw = {"title": name, "thumbnail_text": "", "description": f"{name}. #Shorts", "tags": []}
    else:
        raw = providers.text(PACKAGE_PROMPT, f"{base._brand_lines(run)}Transcript:\n{transcript[:12000]}")
    title = (str(raw.get("title") or "").strip() or run.output.get("source_title") or "My video")[:90]
    thumb = " ".join(str(raw.get("thumbnail_text") or "").split()[:4])[:40]
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = tags.split(",")
    workdir = folder / "work"
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        render.thumbnail(base.media_path(run.output["video"]), thumb or title, base.highlight(run),
                         folder / "thumb.jpg", workdir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    run.output.update({
        "title": title,
        "thumbnail_text": thumb,
        "title_check": hooks.lint_title(title, thumb),
        "description": str(raw.get("description") or "").strip()[:4900],
        "tags": [str(t).strip().lstrip("#")[:60] for t in tags if str(t).strip()][:12],
        "thumbnail": f"{rel}/thumb.jpg",
    })
    base._save(run)


STEPS = {
    "prepare": step_prepare,
    "transcribe": step_transcribe,
    "clean_audio": step_clean_audio,
    "plan_edit": step_plan_edit,
    "review_edit": step_review_edit,
    "render_edit": step_render_edit,
    "package": step_package,
}
