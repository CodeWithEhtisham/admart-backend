from django.db import migrations

TREND_FINDER = {
    "slug": "trend-finder",
    "name": "Trend Finder",
    "kind": "small",
    "description": "Finds what's rising this week in your niche, with sources and a ready hook. "
    "Make a Short from any of them, or add it to Autopilot.",
    "steps": ["trends"],
    "input_kind": "topic",
    "input_hint": "Your niche, e.g. home coffee brewing",
    "review": False,
    "sort_order": 12,
}


def seed(apps, schema_editor):
    apps.get_model("agents", "AgentRecipe").objects.get_or_create(slug=TREND_FINDER["slug"], defaults=TREND_FINDER)


def unseed(apps, schema_editor):
    apps.get_model("agents", "AgentRecipe").objects.filter(slug=TREND_FINDER["slug"]).delete()


class Migration(migrations.Migration):
    dependencies = [("agents", "0006_cross_poster")]
    operations = [migrations.RunPython(seed, unseed)]
