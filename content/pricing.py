"""Admart credit pricing with fal cost basis.

The backend fetches current fal unit prices where possible, falls back to the
last known prices for this catalog, estimates the billable quantity from user
settings, then applies Admart's markup formula to the raw fal cost.
"""

from __future__ import annotations

import time
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import requests
from django.conf import settings

from content.catalog import DEFAULT_MODELS, MODEL_CATALOG
from content.video_catalog import DEFAULT_VIDEO_MODELS, VIDEO_MODEL_CATALOG

PRICING_URL = "https://api.fal.ai/v1/models/pricing"
PRICING_TTL_SECONDS = 30 * 60
CREDIT_QUANT = Decimal("0.0001")
ADMART_CREDIT_CURRENCY = "Admart credits"
FAL_COST_BASIS_CURRENCY = "fal credits"
MIN_MARKUP = Decimal("0.25")
MARKUP_CURVE_NUMERATOR = Decimal("1.2")

# Last known values from fal's /v1/models/pricing endpoint for the current
# supported catalog. Used only when FAL_KEY/network is unavailable.
FALLBACK_PRICES: dict[str, dict[str, str]] = {
    "fal-ai/flux/dev": {"unit_price": "0.025", "unit": "megapixels", "currency": "USD"},
    "fal-ai/flux/schnell": {"unit_price": "0.003", "unit": "megapixels", "currency": "USD"},
    "fal-ai/nano-banana-2": {"unit_price": "0.08", "unit": "images", "currency": "USD"},
    "fal-ai/nano-banana-pro": {"unit_price": "0.15", "unit": "images", "currency": "USD"},
    "fal-ai/ideogram/v3": {"unit_price": "0.03", "unit": "images", "currency": "USD"},
    "openai/gpt-image-2": {"unit_price": "1", "unit": "units", "currency": "USD"},
    "fal-ai/nano-banana-2/edit": {"unit_price": "0.08", "unit": "images", "currency": "USD"},
    "fal-ai/nano-banana-pro/edit": {"unit_price": "0.15", "unit": "images", "currency": "USD"},
    "fal-ai/flux-pro/kontext": {"unit_price": "0.04", "unit": "images", "currency": "USD"},
    "openai/gpt-image-2/edit": {"unit_price": "1", "unit": "units", "currency": "USD"},
    "wan/v2.6/image-to-image": {"unit_price": "0.00007", "unit": "compute seconds", "currency": "USD"},
    "fal-ai/esrgan": {"unit_price": "0.00111", "unit": "compute seconds", "currency": "USD"},
    "fal-ai/seedvr/upscale/image": {"unit_price": "0.001", "unit": "megapixels", "currency": "USD"},
    "fal-ai/topaz/upscale/image": {"unit_price": "0.01", "unit": "megapixels", "currency": "USD"},
    "fal-ai/recraft/upscale/crisp": {"unit_price": "0.004", "unit": "images", "currency": "USD"},
    "fal-ai/ideogram/upscale": {"unit_price": "0.06", "unit": "images", "currency": "USD"},
    "fal-ai/birefnet/v2": {"unit_price": "0.0008", "unit": "compute seconds", "currency": "USD"},
    "fal-ai/birefnet": {"unit_price": "0.0008", "unit": "compute seconds", "currency": "USD"},
    "fal-ai/bria/background/remove": {"unit_price": "0.018", "unit": "generations", "currency": "USD"},
    "fal-ai/veo3.1": {"unit_price": "0.4", "unit": "seconds", "currency": "USD"},
    "bytedance/seedance-2.0/text-to-video": {"unit_price": "0.014", "unit": "units", "currency": "USD"},
    "fal-ai/kling-video/v2.5-turbo/pro/text-to-video": {"unit_price": "0.07", "unit": "seconds", "currency": "USD"},
    "fal-ai/kling-video/v2.1/master/text-to-video": {"unit_price": "0.28", "unit": "seconds", "currency": "USD"},
    "fal-ai/minimax/hailuo-02/standard/text-to-video": {"unit_price": "0.045", "unit": "seconds", "currency": "USD"},
    "wan/v2.6/text-to-video": {"unit_price": "0.1", "unit": "seconds", "currency": "USD"},
    "fal-ai/pixverse/v5/text-to-video": {"unit_price": "0.05", "unit": "video segments", "currency": "USD"},
    "fal-ai/ltx-video-13b-distilled": {"unit_price": "0.04", "unit": "videos", "currency": "USD"},
    "fal-ai/veo3.1/image-to-video": {"unit_price": "0.4", "unit": "seconds", "currency": "USD"},
    "bytedance/seedance-2.0/image-to-video": {"unit_price": "0.014", "unit": "units", "currency": "USD"},
    "fal-ai/kling-video/v2.5-turbo/pro/image-to-video": {"unit_price": "0.07", "unit": "seconds", "currency": "USD"},
    "fal-ai/kling-video/v2.1/master/image-to-video": {"unit_price": "0.28", "unit": "seconds", "currency": "USD"},
    "fal-ai/minimax/hailuo-02/standard/image-to-video": {"unit_price": "0.045", "unit": "seconds", "currency": "USD"},
    "wan/v2.6/image-to-video": {"unit_price": "0.1", "unit": "seconds", "currency": "USD"},
    "fal-ai/pixverse/v5/image-to-video": {"unit_price": "0.05", "unit": "video segments", "currency": "USD"},
    "fal-ai/veo3.1/first-last-frame-to-video": {"unit_price": "0.4", "unit": "seconds", "currency": "USD"},
    "fal-ai/veo3.1/fast/first-last-frame-to-video": {"unit_price": "0.15", "unit": "seconds", "currency": "USD"},
}

_CACHE: dict[str, Any] = {"expires_at": 0.0, "prices": None}


def quantize_credits(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(CREDIT_QUANT, rounding=ROUND_HALF_UP)


def serialize_decimal(value: Decimal | int | float | str) -> str:
    text = f"{quantize_credits(value):f}"
    if "." not in text:
        return text
    return text.rstrip("0").rstrip(".") or "0"


def admart_markup_multiplier(fal_cost: Decimal | int | float | str) -> Decimal:
    """Return the Admart price multiplier for a raw fal job cost.

    Formula: price = cost * (1 + max(0.25, 1.2 / (cost + 1))).
    """
    cost = quantize_credits(fal_cost)
    markup = max(MIN_MARKUP, MARKUP_CURVE_NUMERATOR / (cost + Decimal("1")))
    return Decimal("1") + markup


def all_priced_endpoint_ids() -> list[str]:
    ids: list[str] = []
    for models in MODEL_CATALOG.values():
        ids.extend(m["id"] for m in models)
    for models in VIDEO_MODEL_CATALOG.values():
        ids.extend(m["id"] for m in models)
    return list(dict.fromkeys(ids))


def get_fal_prices(endpoint_ids: list[str] | None = None) -> dict[str, dict[str, str]]:
    ids = endpoint_ids or all_priced_endpoint_ids()
    now = time.monotonic()
    cached = _CACHE.get("prices")
    if cached is not None and now < float(_CACHE.get("expires_at", 0)):
        return {mid: cached[mid] for mid in ids if mid in cached}

    prices = dict(FALLBACK_PRICES)
    key = getattr(settings, "FAL_KEY", "")
    if key:
        try:
            response = requests.get(
                PRICING_URL,
                headers={"Authorization": f"Key {key}"},
                params=[("endpoint_id", mid) for mid in ids],
                timeout=20,
            )
            response.raise_for_status()
            for row in response.json().get("prices", []):
                model_id = row.get("endpoint_id")
                if not model_id:
                    continue
                prices[model_id] = {
                    "unit_price": str(row.get("unit_price", "0")),
                    "unit": str(row.get("unit", "units")),
                    "currency": str(row.get("currency", "USD")),
                }
        except requests.RequestException:
            # Keep the test flow working offline; the UI still marks these as estimates.
            pass

    _CACHE["prices"] = prices
    _CACHE["expires_at"] = now + PRICING_TTL_SECONDS
    return {mid: prices[mid] for mid in ids if mid in prices}


def quote_image_job(capability: str, model: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or {}
    return _quote(
        capability=capability,
        model=model or DEFAULT_MODELS[capability],
        data=data,
        quantity=_image_quantity(capability, model or DEFAULT_MODELS[capability], data),
    )


def quote_video_job(capability: str, model: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or {}
    return _quote(
        capability=capability,
        model=model or DEFAULT_VIDEO_MODELS[capability],
        data=data,
        quantity=_video_quantity(capability, model or DEFAULT_VIDEO_MODELS[capability], data),
    )


def attach_image_pricing(catalog: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    return _attach_pricing(catalog)


def attach_video_pricing(catalog: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    return _attach_pricing(catalog)


def base_model_costs() -> dict[str, dict[str, str]]:
    costs: dict[str, dict[str, str]] = {}
    for capability, models in MODEL_CATALOG.items():
        for entry in models:
            quote = quote_image_job(capability, entry["id"], {"numImages": 1})
            costs[entry["id"]] = _public_quote(quote)
    for capability, models in VIDEO_MODEL_CATALOG.items():
        for entry in models:
            settings_for_quote: dict[str, Any] = {}
            fields = entry.get("fields") or {}
            if fields.get("duration"):
                settings_for_quote["duration"] = fields["duration"][0]
            if fields.get("resolution"):
                settings_for_quote["resolution"] = fields["resolution"][0]
            quote = quote_video_job(capability, entry["id"], settings_for_quote)
            costs[entry["id"]] = _public_quote(quote)
    return costs


def quote_response(quote: dict[str, Any], *, credits_remaining: Decimal | None = None) -> dict[str, Any]:
    payload = _public_quote(quote)
    if credits_remaining is not None:
        remaining = quantize_credits(credits_remaining)
        after = remaining - quote["credits_decimal"]
        payload["creditsRemaining"] = serialize_decimal(remaining)
        payload["creditsAfter"] = serialize_decimal(after)
        payload["canAfford"] = remaining >= quote["credits_decimal"]
    return payload


def _attach_pricing(catalog: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    prices = get_fal_prices()
    out = deepcopy(catalog)
    for models in out.values():
        for entry in models:
            row = prices.get(entry["id"])
            if row:
                raw_unit_price = Decimal(str(row.get("unit_price", "0")))
                multiplier = admart_markup_multiplier(raw_unit_price)
                entry["pricing"] = {
                    "unitPrice": serialize_decimal(raw_unit_price),
                    "unit": row.get("unit", "units"),
                    "currency": row.get("currency", "USD"),
                    "source": "fal.ai",
                    "admartUnitPrice": serialize_decimal(raw_unit_price * multiplier),
                    "admartCurrency": ADMART_CREDIT_CURRENCY,
                    "markupMultiplier": serialize_decimal(multiplier),
                }
    return out


def _quote(*, capability: str, model: str, data: dict[str, Any], quantity: Decimal) -> dict[str, Any]:
    row = get_fal_prices([model]).get(model) or FALLBACK_PRICES.get(model)
    if not row:
        row = {"unit_price": "0", "unit": "units", "currency": "USD"}

    unit_price = Decimal(str(row.get("unit_price", "0")))
    unit = str(row.get("unit", "units"))
    quantity = _quantity_for_unit(unit, quantity, data)
    fal_cost = quantize_credits(unit_price * quantity)
    multiplier = admart_markup_multiplier(fal_cost)
    credits = quantize_credits(fal_cost * multiplier)
    return {
        "capability": capability,
        "model": model,
        "unit_price_decimal": unit_price,
        "unit": unit,
        "currency": str(row.get("currency", "USD")),
        "quantity_decimal": quantity,
        "fal_cost_decimal": fal_cost,
        "markup_multiplier_decimal": multiplier,
        "credits_decimal": credits,
        "source": "fal.ai",
    }


def _public_quote(quote: dict[str, Any]) -> dict[str, str]:
    return {
        "capability": quote["capability"],
        "model": quote["model"],
        "credits": serialize_decimal(quote["credits_decimal"]),
        "falCost": serialize_decimal(quote["fal_cost_decimal"]),
        "markupMultiplier": serialize_decimal(quote["markup_multiplier_decimal"]),
        "unitPrice": serialize_decimal(quote["unit_price_decimal"]),
        "unit": quote["unit"],
        "quantity": serialize_decimal(quote["quantity_decimal"]),
        "currency": ADMART_CREDIT_CURRENCY,
        "costBasisCurrency": FAL_COST_BASIS_CURRENCY,
        "source": quote["source"],
    }


def _quantity_for_unit(unit: str, estimated_quantity: Decimal, data: dict[str, Any]) -> Decimal:
    normalized = unit.lower()
    if normalized in {"seconds", "compute seconds", "units"} and data.get("duration"):
        return Decimal(_parse_duration_seconds(data.get("duration")) or 5)
    return max(Decimal("1"), estimated_quantity)


def _image_quantity(capability: str, model: str, data: dict[str, Any]) -> Decimal:
    if capability in {"upscale"}:
        scale = Decimal(str(data.get("scale") or 2))
        return max(Decimal("1"), scale * scale)
    if capability == "removeBackground":
        return Decimal("1")

    count = Decimal(max(1, int(data.get("numImages") or 1)))
    row = get_fal_prices([model]).get(model) or FALLBACK_PRICES.get(model) or {}
    unit = str(row.get("unit", "")).lower()
    if unit == "megapixels":
        return _image_megapixels(data) * count
    return count


def _video_quantity(capability: str, model: str, data: dict[str, Any]) -> Decimal:
    row = get_fal_prices([model]).get(model) or FALLBACK_PRICES.get(model) or {}
    unit = str(row.get("unit", "")).lower()
    if unit in {"seconds", "compute seconds", "units"}:
        return Decimal(_parse_duration_seconds(data.get("duration")) or 5)
    return Decimal("1")


def _image_megapixels(data: dict[str, Any]) -> Decimal:
    image_size = data.get("imageSize")
    if isinstance(image_size, dict):
        width = image_size.get("width") or image_size.get("w")
        height = image_size.get("height") or image_size.get("h")
        try:
            return max(Decimal("1"), (Decimal(str(width)) * Decimal(str(height))) / Decimal("1000000"))
        except Exception:
            pass

    resolution = str(data.get("resolution") or "").lower()
    if resolution == "0.5k":
        return Decimal("0.25")
    if resolution == "2k":
        return Decimal("4")
    if resolution == "4k":
        return Decimal("16")
    return Decimal("1")


def _parse_duration_seconds(raw: Any) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return max(0, int(raw))
    text = str(raw).strip().lower().rstrip("s")
    if text == "auto":
        return 5
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None
