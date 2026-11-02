from django.db import migrations

CROSS_POSTER = {
    "slug": "cross-poster",
    "name": "Cross-poster",
    "kind": "large",
    "description": "Pick a video from your Library: it writes a post for YouTube, Instagram and Facebook "
    "from what is said in it. You check them, then it posts now or at the time you pick.",
    "steps": ["fetch", "listen", "write_post", "review_post", "wait", "post"],
    "needs": ["youtube", "instagram", "facebook"],
    "input_kind": "video",
    "input_hint": "Any video in your Library",
    "review": False,
    "sort_order": 16,
}


def seed(apps, schema_editor):
    apps.get_model("agents", "AgentRecipe").objects.get_or_create(slug=CROSS_POSTER["slug"], defaults=CROSS_POSTER)


def unseed(apps, schema_editor):
    apps.get_model("agents", "AgentRecipe").objects.filter(slug=CROSS_POSTER["slug"]).delete()


class Migration(migrations.Migration):
    dependencies = [("agents", "0005_video_editor")]
    operations = [migrations.RunPython(seed, unseed)]
