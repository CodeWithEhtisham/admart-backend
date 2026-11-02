from django.db import migrations

# Frozen copy of the built-in agents at the time recipes were introduced.
BUILTIN = [
    {
        "slug": "youtube-shorts",
        "name": "YouTube Shorts Creator",
        "kind": "large",
        "description": "Writes, illustrates, voices and edits a vertical Short from a topic. "
        "You approve it before anything is posted.",
        "steps": ["research", "concepts", "pick_concept", "script", "review_script",
                  "voice", "captions", "visuals", "review_storyboard", "render", "finish"],
        "needs": ["youtube"],
        "input_kind": "topic",
        "input_hint": "e.g. 3 surprising facts about coffee",
        "review": True,
        "uses": ["script-writer", "voiceover"],
        "sort_order": 10,
    },
    {
        "slug": "script-writer",
        "name": "Script Writer",
        "kind": "small",
        "description": "Turns a topic into a Short script: hook, scenes with narration and image ideas, "
        "plus title, description and tags.",
        "steps": ["script"],
        "input_kind": "topic",
        "input_hint": "e.g. why cats knock things off tables",
        "sort_order": 20,
    },
    {
        "slug": "voiceover",
        "name": "Voiceover",
        "kind": "small",
        "description": "Turns your text into a natural voice recording (MP3) you can download.",
        "steps": ["voice"],
        "input_kind": "text",
        "input_hint": "Paste up to 3,000 characters",
        "sort_order": 30,
    },
]


def seed(apps, schema_editor):
    AgentRecipe = apps.get_model("agents", "AgentRecipe")
    for row in BUILTIN:
        AgentRecipe.objects.get_or_create(slug=row["slug"], defaults=row)


class Migration(migrations.Migration):
    dependencies = [("agents", "0002_agent_recipe")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
