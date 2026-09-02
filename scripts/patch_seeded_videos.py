"""One-off patch: give the seeded video templates real playable media.

Matches templates by title and sets template_config.videoUrl to the local
MP4 placed in the frontend's public/template-media folder.

Run with the project virtualenv:
    env\\Scripts\\python.exe scripts\\patch_seeded_videos.py
"""

import json
import sqlite3
import sys
import os

# title -> video asset
UPDATES = {
    "Product Launch Reel": "launch-reel.mp4",
    "Food Deal Motion": "food-deal-motion.mp4",
    "Course Intro Reel": "course-intro.mp4",
    "Countdown Teaser Video": "countdown-video.mp4",
    "Person Dance Video": "dance-video-template.mp4",
    "Cinematic Cafe Sequence": "cinematic-cafe.mp4",
    "Clothing Try-On Spin": "clothing-tryon.mp4",
    "Before After Reveal": "before-after.mp4",
    "Product Unboxing Reel": "product-unboxing.mp4",
    "Event Invitation Story": "event-invitation.mp4",
}

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db.sqlite3")
MEDIA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "Admart-frontend",
    "public",
    "template-media",
)


def main() -> int:
    if not os.path.exists(DB_PATH):
        print(f"DB not found: {DB_PATH}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    for title, video_asset in UPDATES.items():
        video_path = os.path.join(MEDIA_DIR, video_asset)
        if not os.path.exists(video_path):
            print(f"SKIP (video not downloaded yet): {title} -> {video_asset}")
            continue

        rows = cur.execute(
            "select id, template_config from content_template where title = ? and is_video = 1",
            (title,),
        ).fetchall()
        if len(rows) != 1:
            print(f"SKIP (expected 1 row, found {len(rows)}): {title}")
            continue

        row = rows[0]
        config = row["template_config"] or {}
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except json.JSONDecodeError:
                config = {}
        if not isinstance(config, dict):
            config = {}

        config["videoUrl"] = f"/template-media/{video_asset}"
        cur.execute(
            "update content_template set template_config = ? where id = ?",
            (json.dumps(config), row["id"]),
        )
        print(f"OK: {title} -> videoUrl={config['videoUrl']}")

    conn.commit()
    conn.close()
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())