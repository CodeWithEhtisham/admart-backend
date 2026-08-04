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
        "description": "For solo creators testing AI content workflows.",
        "price_usd": Decimal("9"),
        "price_pkr": 2499,
        "monthly_credits": Decimal("3"),
        "billing_interval": "month",
        "features": [
            "3 Admart credits monthly",
            "Image and video generation",
            "Manual social publishing",
            "2 connected social accounts",
            "Standard support",
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
        "monthly_credits": Decimal("10"),
        "billing_interval": "month",
        "features": [
            "10 Admart credits monthly",
            "Image, video, and image-to-video",
            "Prompt enhancement",
            "5 connected social accounts",
            "Content calendar",
            "Email support",
        ],
        "sort": 20,
        "public": True,
    },
    "pro": {
        "id": "pro",
        "name": "Pro",
        "description": "For agencies and teams running higher-volume campaigns.",
        "price_usd": Decimal("79"),
        "price_pkr": 21999,
        "monthly_credits": Decimal("30"),
        "billing_interval": "month",
        "features": [
            "30 Admart credits monthly",
            "Priority generation queue",
            "Multi-brand workspaces",
            "Auto-publishing workflows",
            "Analytics dashboard",
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
        payload["falBudgetUsd"] = serialize_decimal(monthly_credits)
        payload["estimatedGrossProfitUsd"] = serialize_decimal(price_usd - monthly_credits)
    return payload

