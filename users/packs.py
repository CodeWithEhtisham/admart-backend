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

def _load_db_packs() -> dict[str, dict[str, Any]] | None:
    """Try to load packs from the database. Returns None if the table doesn't exist yet."""
    try:
        from admin_panel.models import TopupPack

        rows = list(TopupPack.objects.all())
    except Exception:
        return None
    return {
        row.pack_id: {
            "id": row.pack_id,
            "name": row.name,
            "description": row.description,
            "credits": Decimal(str(row.credits)),
            "price_usd": Decimal(str(row.price_usd)),
            "price_pkr": row.price_pkr,
            "features": list(row.features) if row.features else [],
            "sort": row.sort_order,
            "popular": row.popular,
            "public": row.is_public,
        }
        for row in rows
    }


def _packs_dict() -> dict[str, dict[str, Any]]:
    """Return DB packs if available, otherwise the static fallback."""
    return _load_db_packs() or TOPUP_PACKS


def get_topup_pack(pack_id: str | None) -> dict[str, Any] | None:
    """Return a copy of a pack definition (hidden packs included), or None if not found."""
    if not pack_id:
        return None
    pack = _packs_dict().get(str(pack_id).lower())
    return deepcopy(pack) if pack else None


def get_public_pack_ids() -> tuple[str, ...]:
    """Return ordered tuple of pack IDs customers can buy."""
    packs = _packs_dict()
    return tuple(
        pid for pid, p in sorted(packs.items(), key=lambda x: x[1]["sort"])
        if p.get("public", True)
    )


def get_public_topup_packs() -> list[dict[str, Any]]:
    """Return ordered list of public top-up pack definitions."""
    packs = _packs_dict()
    return [serialize_topup_pack(packs[pid]) for pid in get_public_pack_ids()]


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
