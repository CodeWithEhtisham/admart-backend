"""Seed TopupPack rows from the current TOPUP_PACKS constants."""

from decimal import Decimal

from django.db import migrations

SEED_PACKS = [
    {
        "pack_id": "pack_small",
        "name": "Starter Booster",
        "description": "Quick credit boost for extra image or video generations.",
        "credits": Decimal("5"),
        "price_usd": Decimal("6"),
        "price_pkr": 1699,
        "features": [
            "5 Admart credits",
            "Never expires",
            "Keeps your current subscription tier",
            "≈30 Nano Banana images or ≈2 Seedance videos",
        ],
        "popular": False,
        "is_public": True,
        "sort_order": 10,
    },
    {
        "pack_id": "pack_medium",
        "name": "Creator Booster",
        "description": "Most popular boost for weekly social campaigns.",
        "credits": Decimal("15"),
        "price_usd": Decimal("15"),
        "price_pkr": 4199,
        "features": [
            "15 Admart credits",
            "Never expires",
            "Keeps your current subscription tier",
            "≈90 Nano Banana images or ≈6 Seedance videos",
        ],
        "popular": True,
        "is_public": True,
        "sort_order": 20,
    },
    {
        "pack_id": "pack_large",
        "name": "Studio Booster",
        "description": "High-volume generation pack for heavy video production.",
        "credits": Decimal("40"),
        "price_usd": Decimal("35"),
        "price_pkr": 9799,
        "features": [
            "40 Admart credits",
            "Never expires",
            "Keeps your current subscription tier",
            "≈240 Nano Banana images or ≈16 Seedance videos",
        ],
        "popular": False,
        "is_public": True,
        "sort_order": 30,
    },
]


def seed_packs(apps, schema_editor):
    TopupPack = apps.get_model("admin_panel", "TopupPack")
    for pack in SEED_PACKS:
        TopupPack.objects.update_or_create(pack_id=pack["pack_id"], defaults=pack)


def remove_packs(apps, schema_editor):
    TopupPack = apps.get_model("admin_panel", "TopupPack")
    TopupPack.objects.filter(pack_id__in=[p["pack_id"] for p in SEED_PACKS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("admin_panel", "0009_topuppack"),
    ]

    operations = [
        migrations.RunPython(seed_packs, remove_packs),
    ]
