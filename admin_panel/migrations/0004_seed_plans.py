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
            "Image generation and starter video generation",
            "Prompt enhancement",
            "1 brand workspace",
            "2 connected social accounts",
            "Manual publishing",
            "Basic templates",
        ],
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
            "Image, video, and image-to-video generation",
            "Prompt enhancement and editable templates",
            "Brand kit and content calendar",
            "5 connected social accounts",
            "Scheduled/manual publishing",
            "Email support",
        ],
        "is_public": True,
        "sort_order": 20,
    },
    {
        "plan_id": "pro",
        "name": "Pro",
        "description": "For agencies and teams running campaign workflows.",
        "price_usd": "79",
        "price_pkr": 21999,
        "monthly_credits": "120",
        "features": [
            "120 Admart credits monthly",
            "Priority generation queue",
            "Multi-brand workspaces",
            "Auto-publishing workflows",
            "Advanced analytics dashboard",
            "Team-ready campaign workflow",
            "Priority support",
        ],
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
