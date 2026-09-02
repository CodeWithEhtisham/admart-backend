"""Seed PlanDefinition rows from the current PLAN_TIERS constants."""

from django.db import migrations


SEED_PLANS = [
    {
        "plan_id": "free",
        "name": "Free",
        "description": "Account access without a paid monthly generation budget.",
        "price_usd": "0",
        "price_pkr": 0,
        "monthly_credits": "0",
        "features": [
            "Create projects and brand kit",
            "Connect social accounts for setup",
            "Upgrade before generating",
        ],
        "limits": {
            "max_projects": 1,
            "max_brand_workspaces": 1,
            "max_social_connections_per_project": 1,
            "can_schedule_publishing": False,
            "can_auto_publish": False,
            "has_analytics": False,
            "has_priority_queue": False,
        },
        "is_public": False,
        "sort_order": 0,
    },
    {
        "plan_id": "basic",
        "name": "Basic",
        "description": "For creators and small pages starting with AI content.",
        "price_usd": "9",
        "price_pkr": 2499,
        "monthly_credits": "8",
        "features": [
            "8 Admart credits monthly",
            "Image generation: text-to-image, image-to-image",
            "Video generation: text-to-video, image-to-video",
            "Prompt enhancement",
            "2 brand workspaces",
            "2 social media connections per project",
            "Manual publishing",
            "All templates",
        ],
        "limits": {
            "max_projects": 2,
            "max_brand_workspaces": 2,
            "max_social_connections_per_project": 2,
            "can_schedule_publishing": False,
            "can_auto_publish": False,
            "has_analytics": False,
            "has_priority_queue": False,
        },
        "is_public": True,
        "sort_order": 10,
    },
    {
        "plan_id": "plus",
        "name": "Plus",
        "description": "For active brands publishing every week.",
        "price_usd": "29",
        "price_pkr": 7999,
        "monthly_credits": "35",
        "features": [
            "35 Admart credits monthly",
            "All Basic features",
            "Image, video, and image-to-video generation",
            "Prompt enhancement and editable templates",
            "4 brand workspaces",
            "5 social media connections per project",
            "Scheduled and manual publishing",
            "Email support",
        ],
        "limits": {
            "max_projects": 4,
            "max_brand_workspaces": 4,
            "max_social_connections_per_project": 5,
            "can_schedule_publishing": True,
            "can_auto_publish": False,
            "has_analytics": False,
            "has_priority_queue": False,
        },
        "is_public": True,
        "sort_order": 20,
    },
    {
        "plan_id": "pro",
        "name": "Pro",
        "description": "For agencies and teams running campaign workflows. Coming soon.",
        "price_usd": "79",
        "price_pkr": 21999,
        "monthly_credits": "120",
        "features": [
            "120 Admart credits monthly",
            "All Plus features",
            "Publish content analytics",
            "More social media connections",
            "Unlimited brand workspaces",
            "Auto-publishing workflows",
            "Advanced analytics dashboard",
            "Team-ready campaign workflow",
            "Priority support",
            "Priority generation queue",
        ],
        "limits": {
            "max_projects": 10,
            "max_brand_workspaces": -1,
            "max_social_connections_per_project": 10,
            "can_schedule_publishing": True,
            "can_auto_publish": True,
            "has_analytics": True,
            "has_priority_queue": True,
        },
        "is_public": True,
        "sort_order": 30,
    },
]


def seed_plans(apps, schema_editor):
    PlanDefinition = apps.get_model("admin_panel", "PlanDefinition")
    for plan in SEED_PLANS:
        PlanDefinition.objects.update_or_create(
            plan_id=plan["plan_id"],
            defaults=plan,
        )


def remove_plans(apps, schema_editor):
    PlanDefinition = apps.get_model("admin_panel", "PlanDefinition")
    PlanDefinition.objects.filter(plan_id__in=[p["plan_id"] for p in SEED_PLANS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("admin_panel", "0003_plandefinition"),
    ]

    operations = [
        migrations.RunPython(seed_plans, remove_plans),
    ]
