"""Provider model-catalog helpers.

This uses the provider's official model-listing API. The returned model list
is discovery data; Admart generation still requires a curated mapper before
an endpoint is enabled for users.
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from decimal import Decimal
from typing import Any

import requests
from django.conf import settings
from django.utils import timezone

from content.catalog import ALLOW_LISTS, MODEL_CATALOG
from content.pricing import (
    ADMART_CREDIT_CURRENCY,
    admart_markup_multiplier,
    get_fal_prices,
    serialize_decimal,
)
from content.video_catalog import VIDEO_ALLOW_LISTS, VIDEO_MODEL_CATALOG

FAL_MODELS_URL = "https://api.fal.ai/v1/models"
DEFAULT_STATUS = "active"
DEFAULT_LIMIT = 50
MAX_LIMIT = 100
CACHE_TTL_SECONDS = 15 * 60

IMAGE_CAPABILITY_CATEGORIES = {
    "textToImage": ("text-to-image",),
    "edit": ("image-to-image",),
    "multiEdit": ("image-to-image",),
    # The provider's category taxonomy has no upscaling / background-removal buckets
    # (empty results live); those capabilities stay curated-only.
}

VIDEO_CAPABILITY_CATEGORIES = {
    "textToVideo": ("text-to-video",),
    "imageToVideo": ("image-to-video",),
    "firstLastFrame": ("image-to-video",),
}

_CACHE: dict[str, Any] = {}

logger = logging.getLogger(__name__)


class FalModelSearchError(RuntimeError):
    pass


def search_fal_models(
    *,
    q: str = "",
    category: str = "",
    capability: str = "",
    status: str = DEFAULT_STATUS,
    limit: int = DEFAULT_LIMIT,
    cursor: str = "",
    expand: str = "",
    include_pricing: bool = True,
) -> dict[str, Any]:
    """Search the provider's current model catalog and normalize the response."""

    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    categories = _categories_for(capability, category)
    responses: list[dict[str, Any]] = []

    if categories and len(categories) > 1 and cursor:
        # A cursor only belongs to a single list response. Keep multi-category
        # discovery simple and deterministic.
        categories = categories[:1]

    if categories:
        for cat in categories:
            responses.append(
                _request_models(q=q, category=cat, status=status, limit=limit, cursor=cursor, expand=expand)
            )
    else:
        responses.append(
            _request_models(q=q, category=category, status=status, limit=limit, cursor=cursor, expand=expand)
        )

    raw_models = _dedupe_models(
        model for response in responses for model in response.get("models", [])
    )
    prices = _prices_for(raw_models) if include_pricing else {}
    models = [_normalize_model(model, prices=prices) for model in raw_models]

    return {
        "items": models,
        "nextCursor": responses[0].get("next_cursor") if len(responses) == 1 else None,
        "hasMore": bool(responses[0].get("has_more")) if len(responses) == 1 else False,
        "source": "provider",
        "syncedAt": timezone.now().isoformat(),
        "filters": {
            "q": q,
            "category": category,
            "capability": capability,
            "status": status,
            "limit": limit,
            "expand": expand,
        },
    }


def catalog_discovery_payload(kind: str) -> dict[str, Any]:
    """Return provider models grouped by Admart capability, excluding enabled IDs."""

    kind = "video" if kind == "video" else "image"
    capability_categories = (
        VIDEO_CAPABILITY_CATEGORIES if kind == "video" else IMAGE_CAPABILITY_CATEGORIES
    )
    enabled_ids = _catalog_ids(VIDEO_MODEL_CATALOG if kind == "video" else MODEL_CATALOG)
    grouped: dict[str, list[dict[str, Any]]] = {}

    for capability, categories in capability_categories.items():
        models_by_id: dict[str, dict[str, Any]] = {}
        for category in categories:
            try:
                result = search_fal_models(
                    category=category,
                    status=DEFAULT_STATUS,
                    limit=30,
                    include_pricing=True,
                )
            except FalModelSearchError:
                continue
            for item in result["items"]:
                if item["id"] in enabled_ids:
                    continue
                models_by_id.setdefault(item["id"], item)
        grouped[capability] = list(models_by_id.values())[:30]

    return {
        "source": "provider",
        "syncedAt": timezone.now().isoformat(),
        "enabledIds": sorted(enabled_ids),
        "discoverable": grouped,
        "note": "These models are current provider listings. Add a mapper before enabling generation.",
    }


def _request_models(
    *,
    q: str,
    category: str,
    status: str,
    limit: int,
    cursor: str,
    expand: str,
) -> dict[str, Any]:
    cache_key = "|".join([q, category, status, str(limit), cursor, expand])
    cached = _CACHE.get(cache_key)
    now = time.monotonic()
    if cached and now < cached["expires_at"]:
        return cached["data"]

    params: dict[str, Any] = {"limit": limit}
    if q:
        params["q"] = q
    if category:
        params["category"] = category
    if status:
        params["status"] = status
    if cursor:
        params["cursor"] = cursor
    if expand:
        params["expand"] = expand

    headers = {}
    if settings.FAL_KEY:
        headers["Authorization"] = f"Key {settings.FAL_KEY}"

    try:
        response = requests.get(FAL_MODELS_URL, headers=headers, params=params, timeout=25)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise FalModelSearchError("Could not fetch provider model catalog") from exc

    data = response.json()
    _CACHE[cache_key] = {"expires_at": now + CACHE_TTL_SECONDS, "data": data}
    return data


def _normalize_model(model: dict[str, Any], *, prices: dict[str, dict[str, str]]) -> dict[str, Any]:
    endpoint_id = str(model.get("endpoint_id") or model.get("id") or "").strip()
    metadata = model.get("metadata") or {}
    supported_capabilities = _supported_capabilities(endpoint_id)
    price = prices.get(endpoint_id)

    payload = {
        "id": endpoint_id,
        "label": metadata.get("display_name") or _label_from_id(endpoint_id),
        "category": metadata.get("category") or "",
        "description": metadata.get("description") or "",
        "status": metadata.get("status") or "",
        "tags": metadata.get("tags") or [],
        "thumbnailUrl": metadata.get("thumbnail_url") or "",
        "modelUrl": metadata.get("model_url") or "",
        "updatedAt": metadata.get("updated_at") or metadata.get("date") or None,
        "family": _family_from_id(endpoint_id),
        "enabled": bool(supported_capabilities),
        "supportedCapabilities": supported_capabilities,
        "source": "provider",
    }
    if price:
        unit_price = Decimal(str(price.get("unit_price", "0")))
        multiplier = admart_markup_multiplier(unit_price)
        payload["pricing"] = {
            "unitPrice": serialize_decimal(unit_price),
            "unit": price.get("unit", "units"),
            "currency": price.get("currency", "USD"),
            "source": "provider",
            "admartUnitPrice": serialize_decimal(unit_price * multiplier),
            "admartCurrency": ADMART_CREDIT_CURRENCY,
            "markupMultiplier": serialize_decimal(multiplier),
        }
    return payload


def _prices_for(models: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    ids = [m.get("endpoint_id") for m in models if m.get("endpoint_id")]
    if not ids:
        return {}
    return get_fal_prices(list(dict.fromkeys(ids)))


def _dedupe_models(models) -> list[dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for model in models:
        endpoint_id = model.get("endpoint_id")
        if endpoint_id:
            out.setdefault(endpoint_id, model)
    return list(out.values())


def _categories_for(capability: str, category: str) -> tuple[str, ...]:
    if category:
        return (category,)
    if capability in IMAGE_CAPABILITY_CATEGORIES:
        return IMAGE_CAPABILITY_CATEGORIES[capability]
    if capability in VIDEO_CAPABILITY_CATEGORIES:
        return VIDEO_CAPABILITY_CATEGORIES[capability]
    return ()


def _supported_capabilities(endpoint_id: str) -> list[str]:
    supported: list[str] = []
    for capability, ids in ALLOW_LISTS.items():
        if endpoint_id in ids:
            supported.append(capability)
    for capability, ids in VIDEO_ALLOW_LISTS.items():
        if endpoint_id in ids:
            supported.append(capability)
    return supported


def _catalog_ids(catalog: dict[str, list[dict[str, Any]]]) -> set[str]:
    return {entry["id"] for models in catalog.values() for entry in models}


def _family_from_id(endpoint_id: str) -> str:
    text = endpoint_id.lower()
    for family in (
        "flux",
        "nano",
        "ideogram",
        "openai",
        "wan",
        "veo",
        "seedance",
        "kling",
        "minimax",
        "pixverse",
        "ltx",
        "birefnet",
        "bria",
        "topaz",
        "recraft",
        "seedvr",
    ):
        if family in text:
            return family
    return text.split("/")[0] if text else "provider"


def _label_from_id(endpoint_id: str) -> str:
    tail = endpoint_id.strip("/").split("/")[-1] if endpoint_id else "Model"
    return tail.replace("-", " ").replace("_", " ").title()


# ---------------------------------------------------------------------------
# New-model discovery for staff (never shown to users)
# ---------------------------------------------------------------------------

DISCOVERY_CATEGORIES = ("text-to-image", "image-to-image", "text-to-video", "image-to-video")
DISCOVERY_PAGES = 3  # up to 300 models per category, newest and most used first
DISCOVER_EVERY = timedelta(days=1)


def discover_new_models() -> list[str]:
    """List fal's image/video models that Admart doesn't offer yet in FalModelListing.

    Returns the endpoint ids seen for the first time. Staff review them in the Django admin;
    curated ids are skipped, and a listed model that has since been curated is marked "added".
    """
    from content.models import FalModelListing

    curated = _catalog_ids(MODEL_CATALOG) | _catalog_ids(VIDEO_MODEL_CATALOG)
    found: dict[str, dict[str, Any]] = {}
    for category in DISCOVERY_CATEGORIES:
        cursor = ""
        for _ in range(DISCOVERY_PAGES):
            try:
                data = _request_models(q="", category=category, status=DEFAULT_STATUS, limit=MAX_LIMIT,
                                       cursor=cursor, expand="")
            except FalModelSearchError as exc:
                logger.warning("fal model list unavailable for %s: %s", category, exc.__cause__ or exc)
                break
            for model in data.get("models") or []:
                endpoint_id = str(model.get("endpoint_id") or "").strip()
                if endpoint_id:
                    found.setdefault(endpoint_id, {**model, "category": category})
            cursor = data.get("next_cursor") or ""
            if not data.get("has_more") or not cursor:
                break

    FalModelListing.objects.filter(endpoint_id__in=curated).exclude(status="added").update(status="added")
    candidates = {mid: model for mid, model in found.items() if mid not in curated}
    prices = get_fal_prices(list(candidates)) if candidates else {}
    now = timezone.now()
    existing = set(FalModelListing.objects.filter(endpoint_id__in=candidates).values_list("endpoint_id", flat=True))
    new_ids: list[str] = []
    for endpoint_id, model in candidates.items():
        metadata = model.get("metadata") or {}
        price = prices.get(endpoint_id) or {}
        fields = {
            "label": (metadata.get("display_name") or _label_from_id(endpoint_id))[:200],
            "category": metadata.get("category") or model["category"],
            "description": metadata.get("description") or "",
            "model_url": (metadata.get("model_url") or "")[:300],
            "unit_price": Decimal(str(price["unit_price"])) if price.get("unit_price") is not None else None,
            "unit": str(price.get("unit") or ""),
            "last_seen": now,
        }
        if endpoint_id in existing:
            FalModelListing.objects.filter(endpoint_id=endpoint_id).update(**fields)
        else:
            FalModelListing.objects.create(endpoint_id=endpoint_id, first_seen=now, **fields)
            new_ids.append(endpoint_id)
    if new_ids:
        logger.info("New fal models to review: %s", ", ".join(new_ids))
    return new_ids


def discover_if_stale(max_age: timedelta = DISCOVER_EVERY) -> list[str] | None:
    """Run discovery when the newest listing is older than ``max_age`` (and a FAL_KEY is set)."""
    if not getattr(settings, "FAL_KEY", ""):
        return None
    from django.db.models import Max

    from content.models import FalModelListing

    newest = FalModelListing.objects.aggregate(newest=Max("last_seen"))["newest"]
    if newest is not None and newest > timezone.now() - max_age:
        return None
    return discover_new_models()
