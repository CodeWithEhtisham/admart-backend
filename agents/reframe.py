"""Face-tracked vertical framing for the Clip Maker (CPU only).

analyze → plan_shots → video_filter

A clip is sampled 10 times a second at 640 px. Faces come from OpenCV's YuNet detector, camera cuts
from a colour-histogram change. Each shot (between cuts) gets one layout:
- track: one speaker (or two standing close). A "still camera" that only moves when the face leaves a
  dead zone, then eases over; it snaps on a camera cut instead of panning across it.
- split: two people too far apart for one vertical crop: one per half, stacked.
- fit: no clear face, a crowd, or a screen: the whole picture over a blurred copy of itself.
Design notes: docs/plans/2026-10-14-clip-maker-agent.md (Phase 2), after OpenShorts' reframe engine.
"""

from __future__ import annotations

import re
import subprocess
from functools import lru_cache
from pathlib import Path
from statistics import median

from agents import render

ANALYSIS_FPS = 10
ANALYSIS_WIDTH = 640
OUT_W, OUT_H = render.WIDTH, render.HEIGHT
HALF_H = OUT_H // 2
MIN_FACE = 0.04  # a face narrower than this share of the frame is too far away to frame on
MIN_SCORE = 0.6
DEAD_ZONE = 0.2  # share of the crop width the face can move before the camera follows
SETTLE = 0.03  # a moving camera stops once this close to the face
EASE = 0.2  # share of the remaining distance covered per sample (~0.5 s to settle)
MIN_SHOT = 0.6  # seconds; shorter shots are merged into the one before
CUT_CORRELATION = 0.6  # histogram correlation below this between samples = camera cut
SEAM_TAG = "{\\an5\\pos(540,960)}"
YUNET = Path(__file__).parent / "data" / "face_detection_yunet_2023mar.onnx"


# ── analysis (OpenCV) ─────────────────────────────────────────────────────


def is_cut(previous, frame) -> bool:
    """A camera cut between two frames: their colour histograms no longer match."""
    import cv2

    hists = []
    for image in (previous, frame):
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
        hists.append(cv2.normalize(hist, hist).flatten())
    return cv2.compareHist(hists[0], hists[1], cv2.HISTCMP_CORREL) < CUT_CORRELATION


@lru_cache(maxsize=4)
def _detector(width: int, height: int):
    import cv2

    return cv2.FaceDetectorYN.create(str(YUNET), "", (width, height), MIN_SCORE)


def analyze(source: Path, start: float, length: float, width: int, height: int) -> list[dict]:
    """Samples [{t, faces: [[x, y, w, h, score]] in source pixels, cut}] for source[start:start+length]."""
    import numpy

    aw = ANALYSIS_WIDTH
    ah = max(2, round(aw * height / width / 2) * 2)
    scale = width / aw
    process = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(source),
         "-vf", f"fps={ANALYSIS_FPS},scale={aw}:{ah}", "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    detector, size = _detector(aw, ah), aw * ah * 3
    samples, previous = [], None
    try:
        while len(raw := process.stdout.read(size)) == size:
            frame = numpy.frombuffer(raw, numpy.uint8).reshape(ah, aw, 3)
            _, found = detector.detect(frame)
            faces = [[float(v) * scale for v in f[:4]] + [float(f[-1])] for f in (found if found is not None else [])]
            samples.append({"t": round(len(samples) / ANALYSIS_FPS, 3), "faces": faces,
                            "cut": previous is not None and is_cut(previous, frame)})
            previous = frame
    finally:
        process.stdout.close()
        process.wait(timeout=60)
    return samples


# ── planning (pure) ───────────────────────────────────────────────────────


def _center(face) -> float:
    return face[0] + face[2] / 2


def camera_path(times: list[float], targets: list[float], crop_w: int, frame_w: int) -> list[tuple]:
    """Left edge of the crop at each sample: a still camera that follows only big moves, smoothly."""
    if not times:
        return []
    lo, hi = crop_w / 2, frame_w - crop_w / 2
    smooth = [median(targets[max(0, i - 2) : i + 3]) for i in range(len(targets))]  # drop one-off misses
    camera = median(targets[:ANALYSIS_FPS])  # start on where the face really is in the first second
    moving, path = False, []
    for t, target in zip(times, smooth):
        gap = target - camera
        if abs(gap) > DEAD_ZONE * crop_w:
            moving = True
        if moving:
            camera += gap * EASE
            if abs(target - camera) < SETTLE * crop_w:
                moving = False
        center = min(max(camera, lo), hi)
        path.append((t, int(round(center - crop_w / 2))))
    return path


def _crop_width(width: int, height: int) -> int:
    return min(width, int(round(height * OUT_W / OUT_H / 2) * 2))


def _split_region(face, width: int, height: int) -> tuple:
    """A head-and-shoulders box around one face, shaped like half the vertical frame."""
    ratio = OUT_W / HALF_H
    h = min(height, max(face[3] * 3.0, height * 0.45))
    w = min(width, h * ratio)
    h = w / ratio
    x = min(max(_center(face) - w / 2, 0), width - w)
    y = min(max(face[1] + face[3] / 2 - h * 0.4, 0), height - h)
    return int(x), int(y), int(w) // 2 * 2, int(h) // 2 * 2


def _layout(samples: list[dict], width: int, height: int) -> dict:
    """The layout for one shot from its samples' faces."""
    crop_w = _crop_width(width, height)
    big = [sorted((f for f in s["faces"] if f[2] >= MIN_FACE * width and f[4] >= MIN_SCORE), key=lambda f: -f[2])
           for s in samples]
    counts = [len(f) for f in big]
    n = len(counts)
    if sum(c == 0 for c in counts) >= 0.6 * n or sum(c >= 3 for c in counts) >= 0.5 * n:
        return {"layout": "fit"}
    pairs = [sorted(f[:2], key=_center) for f in big if len(f) == 2]
    if len(pairs) >= 0.5 * n:
        left = [median(p[0][i] for p in pairs) for i in range(4)]
        right = [median(p[1][i] for p in pairs) for i in range(4)]
        if right[0] + right[2] - left[0] > crop_w * 0.9:
            return {"layout": "split", "regions": [_split_region(left, width, height), _split_region(right, width, height)]}
    # Track one target: the pair's middle when two fit together, else the face nearest the last one.
    targets, last = [], None
    for faces in big:
        if len(faces) >= 2 and abs(_center(faces[0]) - _center(faces[1])) < crop_w * 0.6:
            last = (_center(faces[0]) + _center(faces[1])) / 2
        elif faces:
            last = _center(faces[0]) if last is None else min((_center(f) for f in faces), key=lambda c: abs(c - last))
        targets.append(last)
    first = next(t for t in targets if t is not None)
    targets = [first if t is None else t for t in targets]
    times = [s["t"] for s in samples]
    return {"layout": "track", "path": camera_path([t - times[0] for t in times], targets, crop_w, width)}


def plan_shots(samples: list[dict], width: int, height: int, length: float) -> list[dict]:
    """Shots between camera cuts, each with its layout. Times are seconds from the clip start."""
    if not samples:
        return [{"start": 0, "end": length, "layout": "fit"}]
    step = 1 / ANALYSIS_FPS
    groups = [[samples[0]]]
    for s in samples[1:]:
        if s["cut"]:
            groups.append([])
        groups[-1].append(s)
    bounds = [0.0] + [round(g[0]["t"] - step / 2, 3) for g in groups[1:]] + [length]
    merged = []  # (start, end, samples)
    for i, group in enumerate(groups):
        start, end = bounds[i], bounds[i + 1]
        if merged and end - start < MIN_SHOT:
            merged[-1] = (merged[-1][0], end, merged[-1][2] + group)
        else:
            merged.append((start, end, group))
    if len(merged) > 1 and merged[0][1] - merged[0][0] < MIN_SHOT:  # a sliver at the very start
        merged[1] = (merged[0][0], merged[1][1], merged[0][2] + merged[1][2])
        merged.pop(0)
    return [{"start": start, "end": end, **_layout(group, width, height)} for start, end, group in merged]


# ── rendering ─────────────────────────────────────────────────────────────


def _commands(path: list[tuple], name: str) -> str:
    """sendcmd lines moving the crop every output frame, interpolated between samples; only changes."""
    lines, last = [], None
    end = path[-1][0]
    for frame in range(int(end * render.FPS) + 1):
        t = frame / render.FPS
        i = max(k for k, (pt, _x) in enumerate(path) if pt <= t + 1e-9)
        if i + 1 < len(path):
            (t0, x0), (t1, x1) = path[i], path[i + 1]
            x = round(x0 + (x1 - x0) * (t - t0) / (t1 - t0))
        else:
            x = path[i][1]
        if x != last:
            lines.append(f"{t:.3f} {name} x {x};")
            last = x
    return "\n".join(lines) + "\n"


def video_filter(shots: list[dict], width: int, height: int, workdir: Path) -> str:
    """filter_complex for [0:v] → [vr]: every shot trimmed, framed in its layout, joined."""
    crop_w = _crop_width(width, height)
    parts = [f"[0:v]fps={render.FPS},setsar=1,split={len(shots)}" + "".join(f"[s{i}]" for i in range(len(shots)))]
    for i, shot in enumerate(shots):
        cut = f"[s{i}]trim=start={shot['start']:.3f}" + (f":end={shot['end']:.3f}" if i + 1 < len(shots) else "")
        cut += ",setpts=PTS-STARTPTS"
        if shot["layout"] == "track":
            commands = workdir / f"crop-{i}.txt"
            commands.write_text(_commands(shot["path"], f"crop@c{i}"), encoding="utf-8")
            parts.append(f"{cut},sendcmd=f='{commands}',crop@c{i}=w={crop_w}:h={height}:x={shot['path'][0][1]}:y=0,"
                         f"scale={OUT_W}:{OUT_H},setsar=1[v{i}]")
        elif shot["layout"] == "split":
            (x1, y1, w1, h1), (x2, y2, w2, h2) = shot["regions"]
            parts.append(f"{cut},split[t{i}][b{i}]")
            parts.append(f"[t{i}]crop={w1}:{h1}:{x1}:{y1},scale={OUT_W}:{HALF_H},setsar=1[tp{i}]")
            parts.append(f"[b{i}]crop={w2}:{h2}:{x2}:{y2},scale={OUT_W}:{OUT_H - HALF_H},setsar=1[bt{i}]")
            parts.append(f"[tp{i}][bt{i}]vstack[v{i}]")
        else:
            parts.append(f"{cut},split[f{i}][g{i}]")
            parts.append(f"[f{i}]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,crop={OUT_W}:{OUT_H},"
                         f"boxblur=24:2,eq=brightness=-0.12[bg{i}]")
            parts.append(f"[g{i}]scale={OUT_W}:-2[fg{i}]")
            parts.append(f"[bg{i}][fg{i}]overlay=(W-w)/2:(H-h)/2,setsar=1[v{i}]")
    parts.append("".join(f"[v{i}]" for i in range(len(shots))) + f"concat=n={len(shots)}:v=1:a=0[vr]")
    return ";".join(parts)


def _seconds(stamp: str) -> float:
    h, m, s = stamp.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def seam_captions(ass: str, ranges: list[tuple]) -> str:
    """Captions that start during a split screen move to the seam between the two people."""
    def move(match):
        start = _seconds(match.group(2))
        inside = any(a <= start < b for a, b in ranges)
        return match.group(1) + (SEAM_TAG if inside else "")

    return re.sub(r"^(Dialogue: \d+,([\d:.]+),[^,]*,Cap,(?:[^,]*,){5})", move, ass, flags=re.M)
