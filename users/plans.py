"""Business plan definitions for Admart subscriptions.

Payment is not connected yet, so these values are the source of truth for the
temporary plan activation flow and the billing UI.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

from content.pricing import serialize_decimal


PLAN_TIERS: dict[str, dict[str, Any]] = {
    "free": {
        "id": "free",
        "name": "Free",
        "description": "Account access without a paid monthly generation budget.",
        "price_usd": Decimal("0"),
        "price_pkr": 0,
        "monthly_credits": Decimal("0"),
        "billing_interval": "month",
        "features": [
            "Create projects and brand kit",
            "Connect social accounts for setup",
            "Upgrade before generating",
        ],
        "sort": 0,
        "public": False,
    },
    "basic": {
        "id": "basic",
        "name": "Basic",
        "description": "For creators and small pages starting with AI content.",
        "price_usd": Decimal("9"),
        "price_pkr": 2499,
        "monthly_credits": Decimal("8"),
        "billing_interval": "month",
        "features": [
            "8 Admart credits monthly",
            "Image generation and starter video generation",
            "Prompt enhancement",
            "1 brand workspace",
            "2 connected social accounts",
            "Manual publishing",
            "Basic templates",
        ],
        "sort": 10,
        "public": True,
    },
    "plus": {
        "id": "plus",
        "name": "Plus",
        "description": "For active brands publishing every week.",
        "price_usd": Decimal("29"),
        "price_pkr": 7999,
        "monthly_credits": Decimal("35"),
        "billing_interval": "month",
        "features": [
            "35 Admart credits monthly",
            "Image, video, and image-to-video generation",
            "Prompt enhancement and editable templates",
            "Brand kit and content calendar",
            "5 connected social accounts",
            "Scheduled/manual publishing",
            "Email support",
        ],
        "sort": 20,
        "public": True,
    },
    "pro": {
        "id": "pro",
        "name": "Pro",
        "description": "For agencies and teams running campaign workflows.",
        "price_usd": Decimal("79"),
        "price_pkr": 21999,
        "monthly_credits": Decimal("120"),
        "billing_interval": "month",
        "features": [
            "120 Admart credits monthly",
            "Priority generation queue",
            "Multi-brand workspaces",
            "Auto-publishing workflows",
            "Advanced analytics dashboard",
            "Team-ready campaign workflow",
            "Priority support",
        ],
        "sort": 30,
        "public": True,
    },
}

PUBLIC_PLAN_IDS = tuple(
    plan_id
    for plan_id, plan in sorted(PLAN_TIERS.items(), key=lambda item: item[1]["sort"])
    if plan.get("public")
)


def get_plan(plan_id: str | None) -> dict[str, Any]:
    """Return a copy of a plan definition, falling back to Free."""
    key = (plan_id or "free").lower()
    return deepcopy(PLAN_TIERS.get(key, PLAN_TIERS["free"]))


def serialize_plan(plan_id: str | None, *, include_internal: bool = False) -> dict[str, Any]:
    """Return a JSON-friendly public representation of a plan."""
    plan = get_plan(plan_id)
    price_usd = plan["price_usd"]
    monthly_credits = plan["monthly_credits"]
    payload = {
        "id": plan["id"],
        "name": plan["name"],
        "description": plan["description"],
        "priceUsd": serialize_decimal(price_usd),
        "pricePkr": plan["price_pkr"],
        "monthlyCredits": serialize_decimal(monthly_credits),
        "billingInterval": plan["billing_interval"],
        "features": plan["features"],
    }
    if include_internal:
        payload["includedAdmartCredits"] = serialize_decimal(monthly_credits)
        payload["pricingNote"] = "Admart credits are user-facing credits with markup over fal cost basis."
    return payload
