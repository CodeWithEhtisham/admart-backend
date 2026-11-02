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


STARTER_AGENTS = ["youtube-shorts", "script-writer", "voiceover", "trend-finder"]
BASIC_AGENTS = STARTER_AGENTS + ["cross-poster", "clip-maker", "video-editor"]
ALL_AGENTS = BASIC_AGENTS + ["growth-report"]

# Limits every plan has (an admin-made plan without one of these gets Starter's value):
# agents: agent types it may use; max_scheduled_agents: agents on a schedule at once;
# max_runs_per_week: per scheduled agent (1 = weekly or monthly, 7 = daily);
# clip_max_minutes: longest Clip Maker video; video_model_tier: 1 fast models, 2 + Veo Fast /
# Kling 3 Std / Seedance 2.0, 3 all; video_max_resolution / image_max_resolution: quality cap;
# storage_gb: room for the account's files (content.storage_quota).
PLAN_TIERS: dict[str, dict[str, Any]] = {
    "free": {
        "id": "free",
        "name": "Starter",
        "description": "Try Admart free: make images, videos and Shorts, and publish them automatically.",
        "price_usd": Decimal("0"),
        "price_pkr": 0,
        "monthly_credits": Decimal("0"),
        "billing_interval": "month",
        "features": [
            "5 free credits to try Admart (one-time)",
            "1 project",
            "2 social media connections",
            "Manual and automatic publishing",
            "AI images up to 2K",
            "AI videos up to 720p with fast models",
            "Agents: YouTube Shorts Creator, Script Writer, Voiceover, Trend Finder",
            "Prompt enhancement",
            "2 GB storage",
        ],
        "limits": {
            "max_projects": 1,
            "max_brand_workspaces": 1,
            "max_social_connections_per_project": 2,
            "can_schedule_publishing": False,
            "can_auto_publish": True,
            "has_analytics": False,
            "has_priority_queue": False,
            "agents": STARTER_AGENTS,
            "max_scheduled_agents": 0,
            "max_runs_per_week": 0,
            "clip_max_minutes": 0,
            "video_model_tier": 1,
            "video_max_resolution": "720p",
            "image_max_resolution": "2k",
            "storage_gb": 2,
        },
        "sort": 0,
        "public": True,
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
            "2 projects",
            "3 social media connections per project",
            "Scheduled and automatic publishing",
            "More video models: Veo 3.1 Fast, Kling 3 Standard, Seedance 2.0",
            "AI videos up to 720p, images up to 2K",
            "Agents: + Clip Maker (videos up to 60 min), Video Editor, Cross-poster",
            "1 agent on a weekly schedule",
            "15 GB storage",
        ],
        "limits": {
            "max_projects": 2,
            "max_brand_workspaces": 2,
            "max_social_connections_per_project": 3,
            "can_schedule_publishing": True,
            "can_auto_publish": True,
            "has_analytics": False,
            "has_priority_queue": False,
            "agents": BASIC_AGENTS,
            "max_scheduled_agents": 1,
            "max_runs_per_week": 1,
            "clip_max_minutes": 60,
            "video_model_tier": 2,
            "video_max_resolution": "720p",
            "image_max_resolution": "2k",
            "storage_gb": 15,
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
            "4 projects",
            "5 social media connections per project",
            "All video models (Veo 3.1, Kling 3 Pro, Kling O3, Seedance 2.5) up to 1080p",
            "All agents, including Growth Report",
            "3 agents on a daily schedule",
            "Clip Maker videos up to 2 hours",
            "Publishing analytics",
            "Email support",
            "75 GB storage",
        ],
        "limits": {
            "max_projects": 4,
            "max_brand_workspaces": 4,
            "max_social_connections_per_project": 5,
            "can_schedule_publishing": True,
            "can_auto_publish": True,
            "has_analytics": True,
            "has_priority_queue": False,
            "agents": ALL_AGENTS,
            "max_scheduled_agents": 3,
            "max_runs_per_week": 7,
            "clip_max_minutes": 120,
            "video_model_tier": 3,
            "video_max_resolution": "1080p",
            "image_max_resolution": "2k",
            "storage_gb": 75,
        },
        "sort": 20,
        "public": True,
    },
    "pro": {
        "id": "pro",
        "name": "Pro",
        "description": "For agencies and teams running content at scale.",
        "price_usd": Decimal("79"),
        "price_pkr": 21999,
        "monthly_credits": Decimal("120"),
        "billing_interval": "month",
        "features": [
            "120 Admart credits monthly",
            "10 projects",
            "10 social media connections per project",
            "4K images and videos",
            "All agents",
            "10 agents on a daily schedule",
            "Agent runs go first in the queue",
            "Advanced analytics",
            "Priority support",
            "250 GB storage",
        ],
        "limits": {
            "max_projects": 10,
            "max_brand_workspaces": -1,  # -1 means unlimited
            "max_social_connections_per_project": 10,
            "can_schedule_publishing": True,
            "can_auto_publish": True,
            "has_analytics": True,
            "has_priority_queue": True,
            "agents": ALL_AGENTS,
            "max_scheduled_agents": 10,
            "max_runs_per_week": 7,
            "clip_max_minutes": 120,
            "video_model_tier": 3,
            "video_max_resolution": "4k",
            "image_max_resolution": "4k",
            "storage_gb": 250,
        },
        "sort": 30,
        "public": True,
    },
}

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
    usage = plan_usage(plan)
    payload["usage"] = usage
    payload["features"] = plan["features"] + [line["text"] for line in usage]
    if include_internal:
        payload["includedAdmartCredits"] = serialize_decimal(monthly_credits)
        payload["pricingNote"] = "Admart credits are user-facing credits with markup over fal cost basis."
    return payload


# What a plan's credits buy, priced live (so the numbers follow fal's prices). The video line is the first
# model the plan may use. Each line is "or", not "and": the credits buy that many of one thing.
USAGE_VIDEOS = (
    ("bytedance/seedance-2.0/text-to-video", {"duration": "5", "resolution": "720p"}, "Seedance 2.0 videos (5s, 720p)"),
    ("fal-ai/minimax/hailuo-02/standard/text-to-video", {"duration": "6"}, "Hailuo 02 videos (6s)"),
)


def plan_usage(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """[{"label", "count", "text"}] for the images, videos and Shorts the plan's credits buy."""
    from content.pricing import quote_image_job, quote_video_job
    from users.entitlements import VIDEO_MODEL_TIERS

    trial = plan["id"] == "free"
    if trial:
        from admin_panel.services import free_signup_credits

        credits = free_signup_credits()
    else:
        credits = Decimal(str(plan["monthly_credits"]))
    if credits <= 0:
        return []
    limits = {**PLAN_TIERS["free"]["limits"], **(plan.get("limits") or {})}
    items = [("Nano Banana 2 images", quote_image_job("textToImage", "fal-ai/nano-banana-2", {"resolution": "1K"}))]
    for model, data, label in USAGE_VIDEOS:
        if VIDEO_MODEL_TIERS.get(model, 3) <= limits.get("video_model_tier", 1):
            items.append((label, quote_video_job("textToVideo", model, data)))
            break
    if "youtube-shorts" in (limits.get("agents") or []):
        from agents.registry import estimate_credits, get_agent

        spec = get_agent("youtube-shorts")
        if spec:
            items.append(("YouTube Shorts", {"credits_decimal": estimate_credits(spec, {"topic": "x"}, {})}))
    suffix = "with the trial credits" if trial else "per month"
    usage = []
    for label, quote in items:
        cost = quote["credits_decimal"]
        if cost > 0:
            count = int(credits // cost)
            usage.append({"label": label, "count": count, "text": f"\u2248{count:,} {label} {suffix}"})
    return usage
