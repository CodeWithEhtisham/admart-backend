"""Download working meigen demo videos for the seeded video templates.

The seeded video templates shipped without any playable media. This script
pulls demo MP4 clips from the meigen.ai library URLs already present in the
database (numeric /videos/<id>/video.mp4 style, which are reachable with a
browser user-agent) and stores them in the frontend's
public/template-media folder under template-matching names, so every seeded
video template has a real, playable local video.

Run with the project virtualenv:
    env\\Scripts\\python.exe scripts\\download_template_videos.py
"""

import json
import os
import re
import sqlite3
import sys
import time
import uuid

import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(PROJECT_ROOT, "admart-backend", "db.sqlite3")
TEMPLATE_MEDIA_DIR = os.path.join(PROJECT_ROOT, "Admart-frontend", "public", "template-media")

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Referer": "https://www.meigen.ai/"}

# Meigen "videos/<numeric-id>/video.mp4" style URLs are reachable from this
# network with a browser UA; the "generations/community_*.mp4" ones are not.
NUMERIC_RE = re.compile(r"^https://images\.meigen\.ai/videos/\d+/video\.mp4$")

# target filename -> source template title (logging only)
TARGETS = {
    "launch-reel.mp4": "Product Launch Reel",
    "food-deal-motion.mp4": "Food Deal Motion",
    "course-intro.mp4": "Course Intro Reel",
    "countdown-video.mp4": "Countdown Teaser Video",
    "dance-video-template.mp4": "Person Dance Video",
    "cinematic-cafe.mp4": "Cinematic Cafe Sequence",
    "clothing-tryon.mp4": "Clothing Try-On Spin",
    "before-after.mp4": "Before After Reveal",
    "product-unboxing.mp4": "Product Unboxing Reel",
    "event-invitation.mp4": "Event Invitation Story",
}


def candidate_urls() -> list[str]:
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            "select template_config from content_template where is_video = 1"
        ).fetchall()
    finally:
        conn.close()
    seen = set()
    urls = []
    for (config,) in rows:
        if not config:
            continue
        try:
            cfg = json.loads(config) if isinstance(config, str) else config
        except json.JSONDecodeError:
            continue
        url = str((cfg or {}).get("videoUrl") or "").strip()
        if NUMERIC_RE.match(url) and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def download(url: str, path: str) -> bool:
    tmp = f"{path}.{uuid.uuid4().hex[:8]}.part"
    try:
        with requests.get(url, headers=HEADERS, stream=True, timeout=(15, 180)) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=65536):
                    fh.write(chunk)
        os.replace(tmp, path)
        return True
    except (requests.RequestException, OSError) as exc:
        if os.path.exists(tmp):
            os.remove(tmp)
        print(f"    failed: {exc}")
        return False


def looks_like_mp4(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            head = fh.read(12)
        return len(head) == 12 and head[4:8] == b"ftyp"
    except OSError:
        return False


def main() -> int:
    os.makedirs(TEMPLATE_MEDIA_DIR, exist_ok=True)
    candidates = candidate_urls()
    print(f"found {len(candidates)} numeric /videos/.../video.mp4 URLs in DB")

    index = 0

    def next_candidate() -> str | None:
        nonlocal index
        if index >= len(candidates):
            return None
        url = candidates[index]
        index += 1
        return url

    failures = 0
    for target, title in TARGETS.items():
        path = os.path.join(TEMPLATE_MEDIA_DIR, target)
        if os.path.exists(path) and looks_like_mp4(path) and os.path.getsize(path) > 300_000:
            print(f"skip (exists): {target}")
            continue

        ok = False
        for attempt in range(4):
            url = next_candidate()
            if not url:
                break
            if url == path:
                continue
            print(f"download {target} ({title}) <- {url}")
            if download(url, path) and looks_like_mp4(path):
                print(f"  -> {path} ({os.path.getsize(path) // 1024} KB)")
                ok = True
                break
            time.sleep(2)  # avoid bursting the remote host

        if not ok:
            failures += 1
            print(f"FAIL: {target}")

    print(f"done ({failures} failed)")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())