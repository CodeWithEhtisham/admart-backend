"""Top-up credit pack definitions for Admart on-demand credits."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

from content.pricing import serialize_decimal


TOPUP_PACKS: dict[str, dict[str, Any]] = {
    "pack_small": {
        "id": "pack_small",
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
        "sort": 10,
        "popular": False,
    },
    "pack_medium": {
        "id": "pack_medium",
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
        "sort": 20,
        "popular": True,
    },
    "pack_large": {
        "id": "pack_large",
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
        "sort": 30,
        "popular": False,
    },
}

PUBLIC_PACK_IDS = tuple(
    pack_id
    for pack_id, pack in sorted(TOPUP_PACKS.items(), key=lambda item: item[1]["sort"])
)


def get_topup_pack(pack_id: str | None) -> dict[str, Any] | None:
    """Return a copy of a top-up pack definition, or None if not found."""
    if not pack_id:
        return None
    key = str(pack_id).lower()
    pack = TOPUP_PACKS.get(key)
    return deepcopy(pack) if pack else None


def get_public_topup_packs() -> list[dict[str, Any]]:
    """Return ordered list of public top-up pack definitions."""
    return [
        serialize_topup_pack(pack_id)
        for pack_id in PUBLIC_PACK_IDS
    ]


def serialize_topup_pack(pack_or_id: str | dict[str, Any]) -> dict[str, Any]:
    """Return JSON-serializable public representation of a top-up pack."""
    if isinstance(pack_or_id, str):
        pack = get_topup_pack(pack_or_id)
        if not pack:
            return {}
    else:
        pack = pack_or_id

    return {
        "id": pack["id"],
        "name": pack["name"],
        "description": pack["description"],
        "credits": serialize_decimal(pack["credits"]),
        "priceUsd": serialize_decimal(pack["price_usd"]),
        "pricePkr": pack["price_pkr"],
        "features": pack.get("features", []),
        "popular": pack.get("popular", False),
    }
