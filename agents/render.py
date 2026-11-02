"""FFmpeg rendering for agent videos. CPU only: no GPU is needed anywhere.

A Short is built in three passes:
1. one silent clip per scene (camera move on an image, or a trimmed stock clip),
   each extended by the transition length so crossfades never eat narration;
2. the scene clips crossfaded together, word-highlight captions burned in (ASS),
   narration + optional music (ducked under the voice), loudness-normalised;
3. a title thumbnail, then quality checks before anyone sees the result.
"""

from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

from django.conf import settings

WIDTH, HEIGHT, FPS = 1080, 1920, 30
TRANSITION = 0.4  # seconds of crossfade between scenes
CAPTION_WORDS = 3  # most words per on-screen caption line
CAPTION_CHARS = {"en": 16, "ur": 22}  # most characters per line, so a line fits the screen at the caption size
FONTS_DIR = Path(__file__).resolve().parent / "data" / "fonts"  # Montserrat (SIL OFL, see OFL.txt there)
MAX_SECONDS = 180  # YouTube Shorts limit
# Camera moves cycled across image scenes so stills never feel like a slideshow.
MOVES = (
    ("min(zoom+0.0009,1.18)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),  # push in
    ("if(eq(on,0),1.18,max(zoom-0.0009,1.0))", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),  # pull out
    ("1.15", "(iw-iw/zoom)*on/{frames}", "ih/2-(ih/zoom/2)"),  # pan left to right
    ("1.15", "iw/2-(iw/zoom/2)", "(ih-ih/zoom)*(1-on/{frames})"),  # pan bottom to top
)


class RenderError(RuntimeError):
    """A render or quality-check failure (message is safe to show users)."""


def _run(args: list[str], timeout: int = 900) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=timeout)
    except subprocess.CalledProcessError as exc:
        raise RenderError(f"Video rendering failed ({Path(args[0]).name}): {exc.stderr[-300:].strip()}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RenderError("Video rendering took too long.") from exc


def duration_of(path: Path) -> float:
    out = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)])
    return float(out.stdout.strip() or 0)


def placeholder_image(path: Path, color: str) -> None:
    """Solid-colour 9:16 PNG (dry run)."""
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=768x1344", "-frames:v", "1", str(path)])


def silent_audio(path: Path, seconds: float) -> None:
    """Silent MP3 of the given length (dry run)."""
    _run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", f"{seconds:.2f}", str(path)])


def estimate_word_times(text: str, duration: float) -> list[dict]:
    """Word timings spread by character share — used when real timings aren't available."""
    words = text.split()
    total = sum(len(w) + 1 for w in words) or 1
    out, start = [], 0.0
    for word in words:
        end = start + duration * (len(word) + 1) / total
        out.append({"word": word, "start": round(start, 3), "end": round(end, 3)})
        start = end
    return out


# ── captions ──────────────────────────────────────────────────────────────


def _ass_time(seconds: float) -> str:
    cs = max(0, round(seconds * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _ass_color(hex_color: str) -> str:
    """#RRGGBB -> ASS &H00BBGGRR."""
    h = hex_color.lstrip("#") if re.fullmatch(r"#?[0-9a-fA-F]{6}", hex_color or "") else "FFD400"
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _ass_text(word: str) -> str:
    return re.sub(r"[{}\\]", "", word)


_RTL = re.compile(r"[\u0590-\u08FF\uFB1D-\uFDFF\uFE70-\uFEFF]")


def is_rtl(words: list[str]) -> bool:
    """True when the words are in a right-to-left script (Urdu, Arabic, Persian, Hebrew)."""
    return any(_RTL.search(w) for w in words)


def line_with_highlight(texts: list[str], k: int, on: str, off: str, rtl: bool) -> str:
    """One caption line with texts[k] between the `on` and `off` override tags. libass lays the runs
    between tags out left to right, so right-to-left text goes in as [after][word][before] to read in order."""
    if not rtl:
        return " ".join(f"{on}{t}{off}" if j == k else t for j, t in enumerate(texts))
    return " ".join(part for part in (" ".join(texts[k + 1:]), f"{on}{texts[k]}{off}", " ".join(texts[:k])) if part)


def caption_font(language: str = "en") -> tuple[str, str]:
    """(font family, font file) for captions and the thumbnail: an Urdu font for Urdu, else Montserrat ExtraBold."""
    if language == "ur":
        return "Noto Naskh Arabic", settings.AGENTS_URDU_CAPTION_FONT
    return "Montserrat ExtraBold", str(FONTS_DIR / "Montserrat-ExtraBold.ttf")


def caption_groups(words: list[dict], language: str = "en") -> list[list[dict]]:
    """Words cut into caption lines of at most CAPTION_WORDS words and CAPTION_CHARS characters (a longer word
    gets a line of its own)."""
    limit = CAPTION_CHARS.get(language, CAPTION_CHARS["en"])
    groups: list[list[dict]] = []
    for word in words:
        line = groups[-1] if groups else None
        if line and len(line) < CAPTION_WORDS and len(" ".join(w["word"] for w in line + [word])) <= limit:
            line.append(word)
        else:
            groups.append([word])
    return groups


# Shorts look: heavy white words with a thick outline and a soft shadow; the spoken word in the brand colour,
# popping slightly bigger as it is said. (size, outline, shadow, letter spacing) per language: Urdu script reads
# smaller, and any letter spacing stops Urdu letters joining, so it has none.
CAPTION_LOOK = {"en": (92, 10, 4, 1), "ur": (112, 9, 3, 0)}


def caption_highlight(hex_color: str) -> str:
    """The brand colour for the spoken word, lightened toward white when it is too dark to read on a black outline."""
    h = hex_color.lstrip("#") if re.fullmatch(r"#?[0-9a-fA-F]{6}", hex_color or "") else "FFD400"
    rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    luma = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    if luma >= 150:
        return f"#{h.upper()}"
    mix = (150 - luma) / (255 - luma) + 0.1  # just enough white to reach a readable brightness
    return "#" + "".join(f"{round(c + (255 - c) * min(mix, 1)):02X}" for c in rgb)


def build_captions(scenes: list[dict], highlight_hex: str, size: tuple[int, int] = (WIDTH, HEIGHT),
                   language: str = "en") -> str:
    """ASS subtitles: short lines (upper case in English), the word being spoken highlighted in the brand colour."""
    width, height = size
    family = caption_font(language)[0]
    font_size, outline, shadow, spacing = CAPTION_LOOK["ur" if language == "ur" else "en"]
    bold = -1 if language == "ur" else 0  # Montserrat ExtraBold is already heavy; Naskh uses its bold face
    head = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
        "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Cap,{family},{round(font_size * width / WIDTH)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,{bold},0,0,0,"
        f"100,100,{spacing},0,1,{outline},{shadow},2,70,70,{round(height * 0.30)},1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    color = _ass_color(caption_highlight(highlight_hex))
    on = f"{{\\c{color}&\\fscx100\\fscy100\\t(0,90,\\fscx112\\fscy112)}}"
    off = "{\\c&H00FFFFFF&\\fscx100\\fscy100}"
    lines, offset = [], 0.0
    for scene in scenes:
        words = [w for w in scene["words"] if w.get("word")]
        rtl = is_rtl([w["word"] for w in words])
        for group in caption_groups(words, "ur" if rtl else language):
            texts = [_ass_text(w["word"] if rtl else w["word"].upper()) for w in group]
            for k, current in enumerate(group):
                end = group[k + 1]["start"] if k + 1 < len(group) else current["end"]
                text = line_with_highlight(texts, k, on, off, rtl)
                lines.append(
                    f"Dialogue: 0,{_ass_time(offset + current['start'])},{_ass_time(offset + max(end, current['start'] + 0.05))},"
                    f"Cap,,0,0,0,,{text}"
                )
        offset += scene["duration"]
    return head + "\n".join(lines) + "\n"


# ── passes ────────────────────────────────────────────────────────────────


def _scene_clip(index: int, scene: dict, length: float, workdir: Path) -> Path:
    """Silent 1080x1920 clip of `length` seconds for one scene."""
    frames = max(1, round(length * FPS))
    out = workdir / f"scene-{index}.mp4"
    if scene["kind"] == "clip":
        args = [
            "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(scene["path"]), "-t", f"{length:.3f}",
            "-vf", f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},fps={FPS},setsar=1",
            "-an",
        ]
    else:
        z, x, y = (part.format(frames=frames) for part in MOVES[index % len(MOVES)])
        args = [
            "ffmpeg", "-y", "-i", str(scene["path"]),
            "-vf",
            f"scale={int(WIDTH * 1.25)}:{int(HEIGHT * 1.25)}:force_original_aspect_ratio=increase,"
            f"crop={int(WIDTH * 1.25)}:{int(HEIGHT * 1.25)},"
            f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS},setsar=1",
        ]
    _run([*args, "-frames:v", str(frames), "-c:v", "libx264", "-preset", "ultrafast", "-crf", "18",
          "-pix_fmt", "yuv420p", str(out)])
    return out


def thumbnail(source_clip: Path, title: str, highlight_hex: str, out: Path, workdir: Path, language: str = "en") -> None:
    """Frame from the first scene with the title in a brand-coloured box (scaled to 1080 wide so the text fits)."""
    lines = textwrap.wrap(title, 16)[:4]
    box = highlight_hex if re.fullmatch(r"#[0-9a-fA-F]{6}", highlight_hex or "") else "#FFD400"
    font = caption_font(language)[1]
    if language == "ur":
        # Right-to-left text: one centred drawtext per line (a newline inside shaped Urdu text draws a stray box).
        draws = []
        for i, line in enumerate(lines):
            text_file = workdir / f"thumb-title-{i}.txt"
            text_file.write_text(line, encoding="utf-8")
            draws.append(f"drawtext=fontfile='{font}':textfile='{text_file}':fontsize=104:fontcolor=black:box=1:"
                         f"boxcolor={box}@0.92:boxborderw=30:x=(w-text_w)/2:y=h*0.18+{i * 190}")
        text_filter = ",".join(draws)
    else:
        text_file = workdir / "thumb-title.txt"
        text_file.write_text("\n".join(lines), encoding="utf-8")
        text_filter = (f"drawtext=fontfile='{font}':textfile='{text_file}':fontsize=104:"
                       f"fontcolor=black:line_spacing=18:box=1:boxcolor={box}@0.92:boxborderw=34:"
                       f"x=(w-text_w)/2:y=h*0.18")
    _run([
        "ffmpeg", "-y", "-ss", "1", "-i", str(source_clip), "-frames:v", "1", "-vf",
        f"scale=1080:-2,{text_filter}",
        "-q:v", "3", str(out),
    ])


def render_short(
    scenes: list[dict],
    out_path: Path,
    thumb_path: Path,
    workdir: Path,
    *,
    title: str = "",
    highlight_hex: str = "#FFD400",
    music: Path | None = None,
    expect_sound: bool = True,
    language: str = "en",
    captions: bool = True,
) -> dict:
    """Render scenes into one 9:16 Short + thumbnail; returns quality-check results.

    scenes: [{kind: "image"|"clip", path, audio, duration, words: [{word, start, end}]}]
    """
    workdir.mkdir(parents=True, exist_ok=True)
    count = len(scenes)
    clips = [
        _scene_clip(i, s, s["duration"] + (TRANSITION if i < count - 1 else 0), workdir) for i, s in enumerate(scenes)
    ]
    total = sum(s["duration"] for s in scenes)

    captions_file = workdir / "captions.ass"
    captions_file.write_text(build_captions(scenes, highlight_hex, language=language), encoding="utf-8")

    inputs: list[str] = []
    for clip in clips:
        inputs += ["-i", str(clip)]
    for s in scenes:
        inputs += ["-i", str(s["audio"])]
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music)]

    graph, last, offset = [], "[0:v]", 0.0
    for i in range(1, count):
        offset += scenes[i - 1]["duration"]
        graph.append(f"{last}[{i}:v]xfade=transition=fade:duration={TRANSITION}:offset={offset:.3f}[x{i}]")
        last = f"[x{i}]"
    if captions:
        graph.append(f"{last}ass='{captions_file}':fontsdir='{FONTS_DIR}'[vout]")
    else:
        graph.append(f"{last}null[vout]")

    voices = "".join(f"[{count + i}:a]" for i in range(count))
    graph.append(f"{voices}concat=n={count}:v=0:a=1,aresample=44100,aformat=channel_layouts=mono[voice]")
    if music:
        graph += [
            f"[{2 * count}:a]atrim=0:{total:.3f},aresample=44100,aformat=channel_layouts=mono,volume=0.35[bed]",
            "[voice]asplit=2[vo][key]",
            "[bed][key]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[duck]",
            "[vo][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[aout]",
        ]
    else:
        graph.append("[voice]loudnorm=I=-14:TP=-1.5:LRA=11[aout]")

    _run([
        "ffmpeg", "-y", *inputs, "-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "[aout]",
        "-t", f"{total:.3f}", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-movflags", "+faststart", str(out_path),
    ])
    thumbnail(clips[0], title, highlight_hex, thumb_path, workdir, language)
    return check_video(out_path, expect_sound=expect_sound)


def check_video(path: Path, *, expect_sound: bool, size: tuple[int, int] | None = (WIDTH, HEIGHT)) -> dict:
    """Quality gate before a person sees the video. Raises RenderError on a hard failure.

    `size` is the expected (width, height); None skips the shape check (original shape kept).
    """
    duration = duration_of(path)
    if duration < 1:
        raise RenderError("The rendered video is empty.")
    if duration > MAX_SECONDS + 1:
        raise RenderError("The video came out longer than 3 minutes, which is too long for a Short.")
    probe = _run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height", "-of", "json", str(path)])
    if '"audio"' not in probe.stdout:
        raise RenderError("The rendered video has no audio track.")
    checks = [f"Length {duration:.0f}s"]
    if size:
        if f'"width": {size[0]}' not in probe.stdout or f'"height": {size[1]}' not in probe.stdout:
            raise RenderError(f"The rendered video is not {size[0]}x{size[1]}.")
        checks.append(f"{'Vertical' if size[1] > size[0] else 'Square' if size[0] == size[1] else 'Landscape'} {size[0]}×{size[1]}")
    analysis = _run(["ffmpeg", "-i", str(path), "-vf", "blackdetect=d=1.0:pic_th=0.98", "-af",
                     "silencedetect=noise=-45dB:d=2.5,volumedetect", "-f", "null", "-"]).stderr
    if "black_start" in analysis:
        raise RenderError("The video has a stretch of black frames.")
    checks.append("No black frames")
    if expect_sound:
        peak = re.search(r"max_volume:\s*(-?[\d.]+|-inf) dB", analysis)
        if not peak or peak.group(1) == "-inf" or float(peak.group(1)) < -50:
            raise RenderError("The rendered video is silent.")
        if "silence_start" in analysis:
            raise RenderError("The video has a long silent gap.")
        checks += ["Clear audio, no long gaps", "Loudness levelled for YouTube"]
    return {"duration": round(duration, 2), "checks": checks}
