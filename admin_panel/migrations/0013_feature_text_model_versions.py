"""Name the model versions in the usage estimates seeded by 0008 (plans) and 0010 (packs).

"≈47 Nano Banana images" becomes "≈47 Nano Banana 2 images" and "Seedance videos" becomes
"Seedance 2.0 videos": the estimates were computed for those models. Only lines that still
equal the seeded text are changed, so feature lines an admin has written are left alone.
"""

import importlib

from django.db import migrations

_PLAN_LINES = [line for lines in importlib.import_module(
    "admin_panel.migrations.0008_plan_usage_estimates").ADDED_FEATURES.values() for line in lines]
_PACK_LINES = [pack["features"][-1] for pack in importlib.import_module(
    "admin_panel.migrations.0010_seed_topup_packs").SEED_PACKS]


def _renamed(line: str) -> str:
    return line.replace(" Nano Banana images", " Nano Banana 2 images").replace(
        " Seedance videos", " Seedance 2.0 videos")


RENAMES = {line: _renamed(line) for line in _PLAN_LINES + _PACK_LINES}


def _apply(apps, mapping: dict) -> None:
    for model_name in ("PlanDefinition", "TopupPack"):
        for row in apps.get_model("admin_panel", model_name).objects.all():
            features = [mapping.get(line, line) for line in row.features or []]
            if features != row.features:
                row.features = features
                row.save(update_fields=["features"])


def rename_models(apps, schema_editor):
    _apply(apps, RENAMES)


def restore_names(apps, schema_editor):
    _apply(apps, {new: old for old, new in RENAMES.items()})


class Migration(migrations.Migration):
    dependencies = [
        ("admin_panel", "0012_payment_survives_account_deletion"),
    ]

    operations = [
        migrations.RunPython(rename_models, restore_names),
    ]
