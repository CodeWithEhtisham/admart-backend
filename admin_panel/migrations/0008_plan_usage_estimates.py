"""Append per-plan usage estimates to plan features seeded by 0004.

Only rows whose features still equal the original seed are touched, so plans an
admin has edited in the admin panel are left alone.
"""

import importlib

from django.db import migrations

SEED_FEATURES = {
    p["plan_id"]: p["features"]
    for p in importlib.import_module("admin_panel.migrations.0004_seed_plans").SEED_PLANS
}

ADDED_FEATURES = {
    "basic": ["≈47 Nano Banana images per month", "≈3 Seedance videos (5s, 720p) per month"],
    "plus": ["≈207 Nano Banana images per month", "≈13 Seedance videos (5s, 720p) per month"],
    "pro": ["≈710 Nano Banana images per month", "≈47 Seedance videos (5s, 720p) per month"],
}


def add_estimates(apps, schema_editor):
    PlanDefinition = apps.get_model("admin_panel", "PlanDefinition")
    for plan in PlanDefinition.objects.filter(plan_id__in=ADDED_FEATURES):
        if plan.features == SEED_FEATURES[plan.plan_id]:
            plan.features = plan.features + ADDED_FEATURES[plan.plan_id]
            plan.save(update_fields=["features"])


def remove_estimates(apps, schema_editor):
    PlanDefinition = apps.get_model("admin_panel", "PlanDefinition")
    for plan in PlanDefinition.objects.filter(plan_id__in=ADDED_FEATURES):
        if plan.features == SEED_FEATURES[plan.plan_id] + ADDED_FEATURES[plan.plan_id]:
            plan.features = SEED_FEATURES[plan.plan_id]
            plan.save(update_fields=["features"])


class Migration(migrations.Migration):
    dependencies = [
        ("admin_panel", "0007_payment_status_default_pending"),
    ]

    operations = [
        migrations.RunPython(add_estimates, remove_estimates),
    ]
