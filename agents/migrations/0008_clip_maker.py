from django.db import migrations

CLIP_MAKER = {
    "slug": "clip-maker",
    "name": "Clip Maker",
    "kind": "large",
    "description": "Paste a YouTube link or upload a long video: it finds the best moments, scores them "
    "and turns them into vertical clips with captions for TikTok, Reels and Shorts.",
    "steps": ["get_video", "transcribe_long", "find_clips", "review_clips", "render_clips", "finish_clips"],
    "input_kind": "video",
    "input_hint": "A YouTube link or a video up to 2 hours",
    "review": False,
    "sort_order": 17,
}


def seed(apps, schema_editor):
    apps.get_model("agents", "AgentRecipe").objects.get_or_create(slug=CLIP_MAKER["slug"], defaults=CLIP_MAKER)


def unseed(apps, schema_editor):
    apps.get_model("agents", "AgentRecipe").objects.filter(slug=CLIP_MAKER["slug"]).delete()


class Migration(migrations.Migration):
    dependencies = [("agents", "0007_trend_finder")]
    operations = [migrations.RunPython(seed, unseed)]
