"""Plan lineup of 2026-10-20: Starter (free, 5 one-time credits), Basic, Plus, Pro.

Sets each plan's name, description, features and limits from users.plans.PLAN_TIERS (the limits are
merged, so a limit an admin added is kept), hides the old $5 "starter" plan (its subscribers keep it),
and turns on 5 signup credits unless an admin chose another number than the old default 0. The
"≈ N images" lines are no longer stored: users.plans adds them from live prices.
"""

from django.db import migrations

# Frozen copy of users.plans.PLAN_TIERS on 2026-10-20, so later edits there don't change this migration.
STARTER_AGENTS = ["youtube-shorts", "script-writer", "voiceover", "trend-finder"]
BASIC_AGENTS = STARTER_AGENTS + ["cross-poster", "clip-maker", "video-editor"]
ALL_AGENTS = BASIC_AGENTS + ["growth-report"]
LINEUP = {
    "free": {
        "name": "Starter",
        "description": "Try Admart free: make images, videos and Shorts, and publish them automatically.",
        "is_public": True,
        "features": [
            "5 free credits to try Admart (one-time)", "1 project", "2 social media connections",
            "Manual and automatic publishing", "AI images up to 2K", "AI videos up to 720p with fast models",
            "Agents: YouTube Shorts Creator, Script Writer, Voiceover, Trend Finder", "Prompt enhancement",
        ],
        "limits": {
            "max_projects": 1, "max_brand_workspaces": 1, "max_social_connections_per_project": 2,
            "can_schedule_publishing": False, "can_auto_publish": True, "has_analytics": False,
            "has_priority_queue": False, "agents": STARTER_AGENTS, "max_scheduled_agents": 0,
            "max_runs_per_week": 0, "clip_max_minutes": 0, "video_model_tier": 1,
            "video_max_resolution": "720p", "image_max_resolution": "2k",
        },
    },
    "basic": {
        "description": "For creators and small pages starting with AI content.",
        "features": [
            "8 Admart credits monthly", "2 projects", "3 social media connections per project",
            "Scheduled and automatic publishing", "More video models: Veo 3.1 Fast, Kling 3 Standard, Seedance 2.0",
            "AI videos up to 720p, images up to 2K",
            "Agents: + Clip Maker (videos up to 60 min), Video Editor, Cross-poster", "1 agent on a weekly schedule",
        ],
        "limits": {
            "max_projects": 2, "max_brand_workspaces": 2, "max_social_connections_per_project": 3,
            "can_schedule_publishing": True, "can_auto_publish": True, "has_analytics": False,
            "has_priority_queue": False, "agents": BASIC_AGENTS, "max_scheduled_agents": 1,
            "max_runs_per_week": 1, "clip_max_minutes": 60, "video_model_tier": 2,
            "video_max_resolution": "720p", "image_max_resolution": "2k",
        },
    },
    "plus": {
        "description": "For active brands publishing every week.",
        "features": [
            "35 Admart credits monthly", "4 projects", "5 social media connections per project",
            "All video models (Veo 3.1, Kling 3 Pro, Kling O3, Seedance 2.5) up to 1080p",
            "All agents, including Growth Report", "3 agents on a daily schedule", "Clip Maker videos up to 2 hours",
            "Publishing analytics", "Email support",
        ],
        "limits": {
            "max_projects": 4, "max_brand_workspaces": 4, "max_social_connections_per_project": 5,
            "can_schedule_publishing": True, "can_auto_publish": True, "has_analytics": True,
            "has_priority_queue": False, "agents": ALL_AGENTS, "max_scheduled_agents": 3,
            "max_runs_per_week": 7, "clip_max_minutes": 120, "video_model_tier": 3,
            "video_max_resolution": "1080p", "image_max_resolution": "2k",
        },
    },
    "pro": {
        "description": "For agencies and teams running content at scale.",
        "features": [
            "120 Admart credits monthly", "10 projects", "10 social media connections per project",
            "4K images and videos", "All agents", "10 agents on a daily schedule", "Agent runs go first in the queue",
            "Advanced analytics", "Priority support",
        ],
        "limits": {
            "max_projects": 10, "max_brand_workspaces": -1, "max_social_connections_per_project": 10,
            "can_schedule_publishing": True, "can_auto_publish": True, "has_analytics": True,
            "has_priority_queue": True, "agents": ALL_AGENTS, "max_scheduled_agents": 10,
            "max_runs_per_week": 7, "clip_max_minutes": 120, "video_model_tier": 3,
            "video_max_resolution": "4k", "image_max_resolution": "4k",
        },
    },
}


def apply_lineup(apps, schema_editor):
    PlanDefinition = apps.get_model("admin_panel", "PlanDefinition")
    AdminSetting = apps.get_model("admin_panel", "AdminSetting")
    for plan_id, spec in LINEUP.items():
        plan = PlanDefinition.objects.filter(plan_id=plan_id).first()
        if plan is None:
            continue  # no DB row: the built-in PLAN_TIERS (same values) applies
        for field in ("name", "description", "features", "is_public"):
            if field in spec:
                setattr(plan, field, spec[field])
        plan.limits = {**(plan.limits or {}), **spec["limits"]}
        plan.save()
    PlanDefinition.objects.filter(plan_id="starter").update(is_public=False)
    AdminSetting.objects.filter(key="default_free_credits", value__in=("0", "")).update(value="5")


class Migration(migrations.Migration):
    dependencies = [
        ("admin_panel", "0013_feature_text_model_versions"),
    ]

    operations = [
        migrations.RunPython(apply_lineup, migrations.RunPython.noop),
    ]
