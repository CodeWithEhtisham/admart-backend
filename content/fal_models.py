"""Provider model-catalog helpers.

This uses the provider's official model-listing API. The returned model list
is discovery data; Admart generation still requires a curated mapper before
an endpoint is enabled for users.
"""

from __future__ import annotations

import time
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
MERGE_TTL_SECONDS = 10 * 60

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

# Utility models that surface in shared provider categories but don't fit the
# capability (e.g. background removers listed under image-to-image).
_DISCOVERY_EXCLUDE_PATTERNS = {
    "edit": ("birefnet", "background", "upscale", "segmentation", "seedvr"),
    "multiEdit": ("birefnet", "background", "upscale", "segmentation", "seedvr"),
    "imageToVideo": ("lipsync", "audio-to-video", "reference-to-video"),
    "firstLastFrame": ("lipsync", "audio-to-video", "reference-to-video"),
}

_CACHE: dict[str, Any] = {}


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
# Live provider catalog merge (curated + discovered)
# ---------------------------------------------------------------------------
# Discovered models are exposed for visibility ("coming soon") while curated
# catalogs stay authoritative for generation. Discovery entries carry live provider
# pricing and are disabled unless a model has been curated/enabled.

# Model-specific overrides so labels/strengths read naturally in the UI instead
# of falling back to id-derived ones.
_DISCOVERY_OVERRIDES: dict[str, dict[str, str]] = {
    "fal-ai/flux-2-pro": {
        "label": "Flux 2 Pro",
        "strength": "Latest FLUX.2 — sharp text & editing",
        "family": "flux",
    },
    "openai/gpt-image-2.5/flare/text-to-image": {
        "label": "GPT Image 2.5 Flare",
        "strength": "OpenAI's fast, high-quality default",
        "family": "openai",
    },
    "openai/gpt-image-2.5/sunburst/text-to-image": {
        "label": "GPT Image 2.5 Sunburst",
        "strength": "OpenAI's creative-oriented variant",
        "family": "openai",
    },
}


def _discovery_entry_from_model(model: dict[str, Any]) -> dict[str, Any]:
    """Build a UI catalog entry (same shape as curated entries) from a
    normalized provider search item (as returned by ``search_fal_models``)."""
    endpoint_id = model.get("id") or ""
    overrides = _DISCOVERY_OVERRIDES.get(endpoint_id, {})
    label = overrides.get("label") or model.get("label") or _label_from_id(endpoint_id)
    family = overrides.get("family") or model.get("family") or _family_from_id(endpoint_id)

    entry: dict[str, Any] = {
        "id": endpoint_id,
        "label": label,
        "family": family,
        "default": False,
        "enabled": False,
        "source": "provider",
        "strength": overrides.get("strength")
        or (model.get("description") or "")[:120],
    }

    pricing = model.get("pricing")
    if pricing:
        entry["pricing"] = pricing
    return entry


def _merged_discovery(
    *,
    capability_categories: dict[str, tuple[str, ...]],
    enabled_catalog: dict[str, list[dict[str, Any]]],
    cache_key: str,
    limit_per_capability: int,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch the provider's live catalog grouped per capability (cached)."""
    cached = _CACHE.get(cache_key)
    now = time.monotonic()
    if cached and now < cached["expires_at"]:
        return cached["data"]

    enabled_ids = _catalog_ids(enabled_catalog)
    merged: dict[str, list[dict[str, Any]]] = {}
    attempted = 0
    succeeded = 0
    for capability, categories in capability_categories.items():
        exclude = _DISCOVERY_EXCLUDE_PATTERNS.get(capability)
        seen: dict[str, dict[str, Any]] = {}
        for category in categories:
            attempted += 1
            try:
                result = search_fal_models(
                    category=category,
                    status=DEFAULT_STATUS,
                    limit=limit_per_capability,
                    include_pricing=True,
                )
            except FalModelSearchError:
                continue
            succeeded += 1
            for item in result["items"]:
                if item["id"] in enabled_ids or item["id"] in seen:
                    continue
                if exclude and any(pat in item["id"] for pat in exclude):
                    continue
                seen[item["id"]] = _discovery_entry_from_model(item)
        merged[capability] = list(seen.values())[:limit_per_capability]

    if attempted and not succeeded:
        raise FalModelSearchError("provider model discovery failed for all categories")

    _CACHE[cache_key] = {
        "expires_at": now + MERGE_TTL_SECONDS,
        "data": merged,
    }
    return merged

def merged_image_catalog(
    *, include_discovery: bool = True, limit_per_capability: int = 12
) -> dict[str, list[dict[str, Any]]]:
    """Curated image catalog plus live provider models grouped per capability."""

    payload = {cap: list(models) for cap, models in MODEL_CATALOG.items()}
    if not include_discovery:
        return payload

    merged = _merged_discovery(
        capability_categories=IMAGE_CAPABILITY_CATEGORIES,
        enabled_catalog=MODEL_CATALOG,
        cache_key="merged_image",
        limit_per_capability=limit_per_capability,
    )
    for capability, discovered in merged.items():
        payload[capability] = payload.get(capability, []) + discovered
    return payload


def merged_video_catalog(
    *, include_discovery: bool = True, limit_per_capability: int = 12
) -> dict[str, list[dict[str, Any]]]:
    """Curated video catalog plus live provider models grouped per capability."""

    payload = {cap: list(models) for cap, models in VIDEO_MODEL_CATALOG.items()}
    if not include_discovery:
        return payload

    merged = _merged_discovery(
        capability_categories=VIDEO_CAPABILITY_CATEGORIES,
        enabled_catalog=VIDEO_MODEL_CATALOG,
        cache_key="merged_video",
        limit_per_capability=limit_per_capability,
    )
    for capability, discovered in merged.items():
        payload[capability] = payload.get(capability, []) + discovered
    return payload