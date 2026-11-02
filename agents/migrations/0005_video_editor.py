from django.db import migrations, models

VIDEO_EDITOR = {
    "slug": "video-editor",
    "name": "Video Editor",
    "kind": "large",
    "description": "Upload your video: it cuts pauses, ums and restarts, cleans the audio, fixes caption "
    "spelling and reframes it for each platform. You approve it before anything is posted.",
    "steps": ["prepare", "transcribe", "clean_audio", "plan_edit", "review_edit", "render_edit", "package", "finish"],
    "input_kind": "video",
    "input_hint": "A video up to 3 minutes",
    "review": True,
    "sort_order": 15,
}


def seed(apps, schema_editor):
    apps.get_model("agents", "AgentRecipe").objects.get_or_create(slug=VIDEO_EDITOR["slug"], defaults=VIDEO_EDITOR)


def unseed(apps, schema_editor):
    apps.get_model("agents", "AgentRecipe").objects.filter(slug=VIDEO_EDITOR["slug"]).delete()


class Migration(migrations.Migration):
    dependencies = [("agents", "0004_autopilot")]
    operations = [
        migrations.AlterField(
            model_name="agentrecipe",
            name="input_kind",
            field=models.CharField(
                choices=[("topic", "Topic"), ("text", "Text"), ("video", "Video")], default="topic", max_length=8
            ),
        ),
        migrations.RunPython(seed, unseed),
    ]
