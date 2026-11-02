"""Storage per plan (2026-10-20): Starter 2 GB, Basic 15 GB, Plus 75 GB, Pro 250 GB.

Adds storage_gb to each plan's limits and a "N GB storage" feature line, unless an admin already set
them. The hidden old $5 "starter" plan gets 5 GB for the subscribers who still have it.
"""

from django.db import migrations

STORAGE_GB = {"free": 2, "starter": 5, "basic": 15, "plus": 75, "pro": 250}


def add_storage(apps, schema_editor):
    PlanDefinition = apps.get_model("admin_panel", "PlanDefinition")
    for plan in PlanDefinition.objects.filter(plan_id__in=STORAGE_GB):
        limits = plan.limits or {}
        if "storage_gb" in limits:
            continue
        gb = STORAGE_GB[plan.plan_id]
        plan.limits = {**limits, "storage_gb": gb}
        features = list(plan.features or [])
        if not any("storage" in str(line).lower() for line in features):
            features.append(f"{gb} GB storage")
        plan.features = features
        plan.save()


class Migration(migrations.Migration):
    dependencies = [
        ("admin_panel", "0014_plan_lineup_2026_10"),
    ]

    operations = [
        migrations.RunPython(add_storage, migrations.RunPython.noop),
    ]
