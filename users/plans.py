"""Business plan definitions for Admart subscriptions.

Plans are stored in the PlanDefinition model and managed via the admin panel.
This module provides helpers that read from the database, falling back to the
static PLAN_TIERS constant when the DB is not yet migrated or empty.
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
        "limits": {
            "max_projects": 1,
            "max_brand_workspaces": 1,
            "max_social_connections_per_project": 1,
            "can_schedule_publishing": False,
            "can_auto_publish": False,
            "has_analytics": False,
            "has_priority_queue": False,
        },
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
        "sort": 20,
        "public": True,
    },
    "pro": {
        "id": "pro",
        "name": "Pro",
        "description": "For agencies and teams running campaign workflows. Coming soon.",
        "price_usd": Decimal("79"),
        "price_pkr": 21999,
        "monthly_credits": Decimal("120"),
        "billing_interval": "month",
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
            "max_brand_workspaces": -1,  # -1 means unlimited
            "max_social_connections_per_project": 10,
            "can_schedule_publishing": True,
            "can_auto_publish": True,
            "has_analytics": True,
            "has_priority_queue": True,
        },
        "sort": 30,
        "public": True,
    },
}

PUBLIC_PLAN_IDS = tuple(
    plan_id
    for plan_id, plan in sorted(PLAN_TIERS.items(), key=lambda item: item[1]["sort"])
    if plan.get("public")
)


def _load_db_plans() -> dict[str, dict[str, Any]] | None:
    """Try to load plans from the database. Returns None if table doesn't exist yet."""
    try:
        from admin_panel.models import PlanDefinition
    except Exception:
        return None
    try:
        rows = PlanDefinition.objects.all()
    except Exception:
        return None
    plans = {}
    for row in rows:
        plans[row.plan_id] = {
            "id": row.plan_id,
            "name": row.name,
            "description": row.description,
            "price_usd": Decimal(str(row.price_usd)),
            "price_pkr": row.price_pkr,
            "monthly_credits": Decimal(str(row.monthly_credits)),
            "billing_interval": "month",
            "features": list(row.features) if row.features else [],
            "limits": row.limits if row.limits else {},
            "sort": row.sort_order,
            "public": row.is_public,
        }
    return plans


def _plans_dict() -> dict[str, dict[str, Any]]:
    """Return DB plans if available, otherwise the static fallback."""
    db = _load_db_plans()
    if db:
        return db
    return PLAN_TIERS


def get_plan(plan_id: str | None) -> dict[str, Any]:
    """Return a copy of a plan definition, falling back to Free."""
    key = (plan_id or "free").lower()
    plans = _plans_dict()
    return deepcopy(plans.get(key, plans.get("free", PLAN_TIERS["free"])))


def get_public_plan_ids() -> tuple[str, ...]:
    """Return ordered tuple of public plan IDs."""
    plans = _plans_dict()
    return tuple(
        pid for pid, p in sorted(plans.items(), key=lambda x: x[1]["sort"])
        if p.get("public")
    )


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
        "limits": plan.get("limits", {}),
    }
    if include_internal:
        payload["includedAdmartCredits"] = serialize_decimal(monthly_credits)
        payload["pricingNote"] = "Admart credits are user-facing credits with markup over fal cost basis."
    return payload
