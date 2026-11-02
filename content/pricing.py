"""Admart credit pricing with fal cost basis.

fal's current unit prices are fetched in batches by a scheduled refresh (Celery Beat, the
agents worker, or lazily in the background when stale) and stored in FalPriceSnapshot so
every process quotes the same prices. A guard falls back to the last known prices
(content.fal_price_tables) when fal returns a placeholder or an implausible value. The
billable quantity and option multipliers (resolution, audio, duration, quality) come from
the user's settings, then Admart's markup formula is applied to the raw fal cost.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from copy import deepcopy
from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import requests
from django.conf import settings

from content.catalog import ASPECT_TO_FLUX_SIZE, DEFAULT_MODELS, MODEL_CATALOG
from content.fal_price_tables import (
    AUTO_DURATION_SECONDS,
    FALLBACK_PRICES,
    GPT_IMAGE_BUCKET_PIXELS,
    GPT_IMAGE_RATES,
    HIGH_THINKING_USD,
    IMAGE_OPTION_RATES,
    INPUT_IMAGE_USD,
    PIXVERSE_DEFAULT_RESOLUTION,
    PIXVERSE_SEGMENTS,
    PRICE_OVERRIDES,
    SEEDREAM_AREA_MODELS,
    SEEDREAM_TIER_PIXELS,
    VIDEO_OPTION_RATES,
    WEB_SEARCH_USD,
)
from content.video_catalog import DEFAULT_VIDEO_MODELS, VIDEO_MODEL_CATALOG

logger = logging.getLogger(__name__)

PRICING_URL = "https://api.fal.ai/v1/models/pricing"
PRICING_BATCH_SIZE = 40  # fal answers HTTP 400 for more than ~50 endpoint_ids in one request
LIVE_TIMEOUT_SECONDS = 8
PRICING_TTL_SECONDS = 5 * 60  # in-process cache of the snapshot
PRICES_REFRESH_EVERY = timedelta(hours=6)  # Celery Beat and the agents worker
PRICES_STALE_AFTER = timedelta(hours=12)  # past this, a quote starts a background refresh
REFRESH_LOCK_KEY = "content:fal-prices:refreshing"
REFRESH_LOCK_SECONDS = 10 * 60
PRICE_CHANGE_ALERT = Decimal("0.20")
# A live price outside [fallback x 0.2, fallback x 5] is treated as implausible.
GUARD_MIN_RATIO = Decimal("0.2")
GUARD_MAX_RATIO = Decimal("5")
COMPUTE_SECONDS_PER_JOB = Decimal("5")  # floor for models billed per GPU second
CREDIT_QUANT = Decimal("0.0001")
ADMART_CREDIT_CURRENCY = "Admart credits"
FAL_COST_BASIS_CURRENCY = "provider credits"
MIN_MARKUP = Decimal("0.25")
MARKUP_CURVE_NUMERATOR = Decimal("1.2")
# Guaranteed gross margin on the cheapest plan (e.g. 0.10 = 10%).
MIN_PLAN_MARGIN = Decimal(str(getattr(settings, "MIN_PLAN_MARGIN", "0.10")))
# 2^20 pixels: what fal counts as one megapixel for FLUX 2 Pro (1024x1024 = 1 MP).
FAL_MEGAPIXEL = 1024 * 1024
FLUX_ENUM_PIXELS = 1024 * 1024  # the largest image_size preset Admart sends (square_hd)

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

    Formula: price = cost * (1 + max(0.25, minimum viable markup, 1.2 / (cost + 1))).
    The minimum viable markup keeps MIN_PLAN_MARGIN on the cheapest credits Admart sells,
    so expensive jobs (e.g. long videos on the Pro plan) never erode margin.
    """
    cost = quantize_credits(fal_cost)
    markup = max(MIN_MARKUP, _minimum_viable_markup(), MARKUP_CURVE_NUMERATOR / (cost + Decimal("1")))
    return Decimal("1") + markup


def cheapest_credit_value() -> Decimal:
    """USD a customer pays per credit on the cheapest offer: any plan or top-up pack that sells credits.

    Hidden plans and packs count too (existing subscribers may still be on them), and a
    plan's limits.discount_percent lowers its effective price.
    """
    try:
        from users.packs import _packs_dict
        from users.plans import _plans_dict

        plans, packs = _plans_dict(), _packs_dict()
    except Exception:
        logger.warning("Plans unavailable; pricing from the built-in plans and packs", exc_info=True)
        from users.packs import TOPUP_PACKS
        from users.plans import PLAN_TIERS

        plans, packs = PLAN_TIERS, TOPUP_PACKS
    offers = [
        (_discounted(plan.get("price_usd"), (plan.get("limits") or {}).get("discount_percent")),
         plan.get("monthly_credits"))
        for plan in plans.values()
    ] + [(pack.get("price_usd"), pack.get("credits")) for pack in packs.values()]
    values = [
        Decimal(str(price)) / Decimal(str(credits))
        for price, credits in offers
        if Decimal(str(price or 0)) > 0 and Decimal(str(credits or 0)) > 0
    ]
    return min(values, default=Decimal("1"))


def _discounted(price: Any, discount_percent: Any) -> Decimal:
    try:
        discount = min(max(Decimal(str(discount_percent or 0)), Decimal("0")), Decimal("100"))
    except InvalidOperation:
        discount = Decimal("0")
    return Decimal(str(price or 0)) * (Decimal("1") - discount / Decimal("100"))


def _minimum_viable_markup() -> Decimal:
    """The smallest markup extra that keeps MIN_PLAN_MARGIN on the cheapest credits.

    A fal job costing ``c`` is billed ``c*m`` credits, worth ``c*m*v`` dollars on the
    cheapest offer (``v`` dollars per credit). Keeping ``c*m*v >= c*(1 + margin)`` needs
    ``m >= (1 + margin) / v``.
    """
    return ((Decimal("1") + MIN_PLAN_MARGIN) / cheapest_credit_value()) - Decimal("1")


def all_priced_endpoint_ids() -> list[str]:
    ids: list[str] = []
    for models in MODEL_CATALOG.values():
        ids.extend(m["id"] for m in models)
    for models in VIDEO_MODEL_CATALOG.values():
        ids.extend(m["id"] for m in models)
    return list(dict.fromkeys(ids))


# ── live prices, snapshot and guard ────────────────────────────────────────


def fetch_live_prices(endpoint_ids: list[str], timeout: float = LIVE_TIMEOUT_SECONDS) -> dict[str, dict[str, str]]:
    """Ask fal for current unit prices, PRICING_BATCH_SIZE endpoints per request.

    A failed batch is logged and skipped, so only its own models fall back.
    """
    key = getattr(settings, "FAL_KEY", "")
    if not key or not endpoint_ids:
        return {}
    prices: dict[str, dict[str, str]] = {}
    for start in range(0, len(endpoint_ids), PRICING_BATCH_SIZE):
        batch = endpoint_ids[start:start + PRICING_BATCH_SIZE]
        try:
            response = requests.get(
                PRICING_URL,
                headers={"Authorization": f"Key {key}"},
                params=[("endpoint_id", mid) for mid in batch],
                timeout=timeout,
            )
            if response.status_code >= 400:
                logger.warning(
                    "fal pricing API returned HTTP %s for %d models (%s, ...): %s",
                    response.status_code, len(batch), batch[0], (response.text or "")[:300],
                )
                continue
            rows = response.json().get("prices") or []
        except (requests.RequestException, ValueError, AttributeError) as exc:
            logger.warning("fal pricing API request failed for %d models (%s, ...): %s", len(batch), batch[0], exc)
            continue
        for row in rows:
            clean = _clean_row(row)
            if clean and row.get("endpoint_id"):
                prices[str(row["endpoint_id"])] = clean
    return prices


def _clean_row(row: dict[str, Any] | None) -> dict[str, str] | None:
    if not row:
        return None
    try:
        price = Decimal(str(row.get("unit_price")))
    except InvalidOperation:
        return None
    if not price.is_finite():
        return None
    return {
        "unit_price": f"{price.normalize():f}",
        "unit": str(row.get("unit") or "units"),
        "currency": str(row.get("currency") or "USD"),
    }


def is_placeholder(row: dict[str, str]) -> bool:
    """fal's stand-in for models it cannot price per unit: "$1 per unit" (or a zero price)."""
    price = Decimal(str(row.get("unit_price", "0")))
    return price <= 0 or (price == 1 and str(row.get("unit", "")).lower() in {"unit", "units"})


def resolve_price(endpoint_id: str, live: dict[str, Any] | None) -> dict[str, str] | None:
    """The unit price to bill with: override, else the live price if plausible, else the fallback.

    The live price is ignored (fallback used) if it is a placeholder or its unit changed,
    because the unit decides how the quantity is computed. If it is more than 5x or less than
    0.2x the fallback, the higher of the two is used: a real price rise is followed at once,
    and a nonsense drop can never bill below the last known cost.
    """
    if endpoint_id in PRICE_OVERRIDES:
        return PRICE_OVERRIDES[endpoint_id]
    fallback = FALLBACK_PRICES.get(endpoint_id)
    row = _clean_row(live)
    if row is None:
        return fallback
    if fallback is None:
        return row  # a discovered (not yet curated) model: shown, never billed
    if is_placeholder(row):
        logger.warning("fal placeholder price for %s (%s per %s); using %s per %s", endpoint_id,
                       row["unit_price"], row["unit"], fallback["unit_price"], fallback["unit"])
        return fallback
    if row["unit"] != fallback["unit"]:
        logger.warning("fal unit for %s changed from %r to %r; using the last known price until the "
                       "fallback is updated", endpoint_id, fallback["unit"], row["unit"])
        return fallback
    ratio = Decimal(row["unit_price"]) / Decimal(fallback["unit_price"])
    if ratio > GUARD_MAX_RATIO or ratio < GUARD_MIN_RATIO:
        safer = row if ratio > 1 else fallback
        logger.warning("fal price for %s is %sx the last known price (%s vs %s per %s); using %s",
                       endpoint_id, ratio.quantize(Decimal("0.01")), row["unit_price"],
                       fallback["unit_price"], row["unit"], safer["unit_price"])
        return safer
    return row


def get_fal_prices(endpoint_ids: list[str] | None = None) -> dict[str, dict[str, str]]:
    """Billing prices by endpoint id: the shared snapshot through the guard, else fallbacks.

    Never waits on fal for catalog models; a stale snapshot is refreshed in the background.
    Ids outside the catalog (provider discovery) are fetched live, as before.
    """
    ids = endpoint_ids or all_priced_endpoint_ids()
    now = time.monotonic()
    prices = _CACHE.get("prices")
    if prices is None or now >= float(_CACHE.get("expires_at", 0)):
        prices = _load_prices()
        _CACHE["prices"] = prices
        _CACHE["expires_at"] = now + PRICING_TTL_SECONDS
    missing = [mid for mid in ids if mid not in prices]
    if missing:
        for mid, row in fetch_live_prices(missing).items():
            resolved = resolve_price(mid, row)
            if resolved:
                prices[mid] = resolved
    return {mid: prices[mid] for mid in ids if mid in prices}


def _load_prices() -> dict[str, dict[str, str]]:
    known = list(dict.fromkeys([*FALLBACK_PRICES, *PRICE_OVERRIDES, *all_priced_endpoint_ids()]))
    prices = {mid: row for mid in known if (row := resolve_price(mid, None))}
    rows = _snapshot_rows()
    for snap in rows:
        resolved = resolve_price(snap.endpoint_id, {
            "unit_price": snap.unit_price, "unit": snap.unit, "currency": snap.currency,
        })
        if resolved:
            prices[snap.endpoint_id] = resolved
    if getattr(settings, "FAL_KEY", ""):
        from django.utils import timezone

        newest = max((snap.fetched_at for snap in rows), default=None)
        if newest is None or newest < timezone.now() - PRICES_STALE_AFTER:
            _start_background_refresh()
    return prices


def _snapshot_rows() -> list:
    try:
        from content.models import FalPriceSnapshot

        return list(FalPriceSnapshot.objects.all())
    except Exception as exc:  # table not migrated yet, or no database access (e.g. SimpleTestCase)
        logger.info("fal price snapshot unavailable (%s); using the built-in prices", exc)
        return []


def _start_background_refresh() -> None:
    """Refresh the snapshot in a daemon thread so no user request waits on fal (one at a time)."""
    from django.core.cache import cache

    from content.apps import _is_running_tests

    if _is_running_tests() or not cache.add(REFRESH_LOCK_KEY, 1, timeout=REFRESH_LOCK_SECONDS):
        return
    threading.Thread(target=_background_refresh, name="fal-price-refresh", daemon=True).start()


def _background_refresh() -> None:
    from django.db import connections

    try:
        refresh_price_snapshot()
    except Exception:
        logger.exception("Background fal price refresh failed; quotes keep the last known prices")
    finally:
        connections.close_all()


def refresh_price_snapshot(timeout: float = LIVE_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Fetch live prices for the catalog, store them, and log moves of more than 20%.

    Models fal did not answer for keep their previous snapshot row.
    """
    from django.utils import timezone

    from content.models import FalPriceSnapshot

    ids = all_priced_endpoint_ids()
    live = fetch_live_prices(ids, timeout=timeout)
    previous = {snap.endpoint_id: snap for snap in FalPriceSnapshot.objects.filter(endpoint_id__in=list(live))}
    fetched_at = timezone.now()
    changed: list[dict[str, str]] = []
    for endpoint_id, row in live.items():
        new_price = Decimal(row["unit_price"])
        old = previous.get(endpoint_id)
        before = (
            {"unit_price": str(old.unit_price), "unit": old.unit} if old else FALLBACK_PRICES.get(endpoint_id)
        )
        if before and _moved(Decimal(str(before["unit_price"])), new_price, before["unit"], row["unit"]):
            changed.append({"endpoint_id": endpoint_id, "from": f"{Decimal(str(before['unit_price'])).normalize():f}",
                            "to": row["unit_price"], "unit": row["unit"]})
        FalPriceSnapshot.objects.update_or_create(
            endpoint_id=endpoint_id,
            defaults={"unit_price": new_price, "unit": row["unit"], "currency": row["currency"],
                      "source": "fal", "fetched_at": fetched_at},
        )
    for change in changed:
        logger.warning("fal price for %s moved from %s to %s per %s",
                       change["endpoint_id"], change["from"], change["to"], change["unit"])
    if len(live) < len(ids):
        logger.warning("fal returned no price for %d of %d catalog models; they keep their last known price",
                       len(ids) - len(live), len(ids))
    _CACHE["prices"] = None
    _CACHE["expires_at"] = 0
    return {"requested": len(ids), "fetched": len(live), "failed": len(ids) - len(live), "changed": changed}


def _moved(old: Decimal, new: Decimal, old_unit: str, new_unit: str) -> bool:
    if old_unit != new_unit or old <= 0:
        return True
    return abs(new - old) / old > PRICE_CHANGE_ALERT


def refresh_prices_if_stale(max_age: timedelta = PRICES_REFRESH_EVERY) -> dict[str, Any] | None:
    """Refresh the snapshot if its newest price is older than ``max_age`` (and a FAL_KEY is set)."""
    if not getattr(settings, "FAL_KEY", ""):
        return None
    from django.db.models import Max
    from django.utils import timezone

    from content.models import FalPriceSnapshot

    newest = FalPriceSnapshot.objects.aggregate(newest=Max("fetched_at"))["newest"]
    if newest is not None and newest > timezone.now() - max_age:
        return None
    return refresh_price_snapshot()


# ── quotes ─────────────────────────────────────────────────────────────────


def quote_image_job(capability: str, model: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or {}
    model = model or DEFAULT_MODELS[capability]
    return _quote(
        capability=capability,
        model=model,
        data=data,
        quantity=_image_quantity(capability, model, data),
        factor=_image_factor(model, data),
        extras=_image_extras_usd(capability, model, data),
    )


def quote_video_job(capability: str, model: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = data or {}
    model = model or DEFAULT_VIDEO_MODELS[capability]
    return _quote(
        capability=capability,
        model=model,
        data=data,
        quantity=_video_quantity(capability, model, data),
        factor=_video_factor(capability, model, data),
        extras=Decimal("0"),
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
                    "source": "provider",
                    "admartUnitPrice": serialize_decimal(raw_unit_price * multiplier),
                    "admartCurrency": ADMART_CREDIT_CURRENCY,
                    "markupMultiplier": serialize_decimal(multiplier),
                }
    return out


def _price_row(model: str) -> dict[str, str]:
    return (
        get_fal_prices([model]).get(model)
        or resolve_price(model, None)
        or {"unit_price": "0", "unit": "units", "currency": "USD"}
    )


def _quote(
    *, capability: str, model: str, data: dict[str, Any], quantity: Decimal, factor: Decimal, extras: Decimal
) -> dict[str, Any]:
    row = _price_row(model)
    unit_price = Decimal(str(row.get("unit_price", "0")))
    unit = str(row.get("unit", "units"))
    quantity = max(Decimal("1"), quantity)
    raw_cost = unit_price * quantity * factor + extras
    fal_cost = quantize_credits(raw_cost)
    multiplier = admart_markup_multiplier(fal_cost)
    # Round the billed credits up from a cost rounded up, so rounding never eats the margin.
    billed_cost = raw_cost.quantize(CREDIT_QUANT, rounding=ROUND_CEILING)
    credits = (billed_cost * multiplier).quantize(CREDIT_QUANT, rounding=ROUND_CEILING)
    return {
        "capability": capability,
        "model": model,
        "unit_price_decimal": unit_price,
        "unit": unit,
        "currency": str(row.get("currency", "USD")),
        "quantity_decimal": quantity,
        "option_factor_decimal": factor,
        "extras_decimal": extras,
        "fal_cost_decimal": fal_cost,
        "markup_multiplier_decimal": multiplier,
        "credits_decimal": credits,
        "source": "provider",
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
        "optionMultiplier": serialize_decimal(quote.get("option_factor_decimal", 1)),
        "extraCost": serialize_decimal(quote.get("extras_decimal", 0)),
        "currency": ADMART_CREDIT_CURRENCY,
        "costBasisCurrency": FAL_COST_BASIS_CURRENCY,
        "source": quote["source"],
    }


# ── image quantity and options ─────────────────────────────────────────────


def _image_quantity(capability: str, model: str, data: dict[str, Any]) -> Decimal:
    unit = str(_price_row(model).get("unit", "")).lower()
    if capability in {"upscale"}:
        scale = Decimal(str(data.get("scale") or 2))
        quantity = max(Decimal("1"), scale * scale)
        return max(quantity, COMPUTE_SECONDS_PER_JOB) if unit == "compute seconds" else quantity
    if capability == "removeBackground":
        return COMPUTE_SECONDS_PER_JOB if unit == "compute seconds" else Decimal("1")

    count = Decimal(max(1, int(data.get("numImages") or 1)))
    if unit == "megapixels":
        return _image_megapixels(data) * count
    if unit == "processed megapixels":
        return _processed_megapixels(data) * count
    return count


def _processed_megapixels(data: dict[str, Any]) -> Decimal:
    """FLUX 2 Pro: the first megapixel at the unit price, each further one (rounded up) at half."""
    pixels = _requested_pixels(data) or FLUX_ENUM_PIXELS
    megapixels = max(1, math.ceil(pixels / FAL_MEGAPIXEL))
    return Decimal("1") + Decimal("0.5") * (megapixels - 1)


def _requested_pixels(data: dict[str, Any]) -> int | None:
    """Output pixels Admart asks fal for, or None when fal chooses the size itself."""
    size = data.get("imageSize")
    if isinstance(size, dict):
        try:
            width = int(size.get("width") or size.get("w"))
            height = int(size.get("height") or size.get("h"))
            return max(1, width * height)
        except (TypeError, ValueError):
            return None
    if isinstance(size, str) and size in ASPECT_TO_FLUX_SIZE.values():
        return FLUX_ENUM_PIXELS
    if data.get("aspectRatio") in ASPECT_TO_FLUX_SIZE:
        return FLUX_ENUM_PIXELS
    return None


def _image_factor(model: str, data: dict[str, Any]) -> Decimal:
    if model in GPT_IMAGE_RATES:
        return _gpt_image_factor(model, data)
    if model in SEEDREAM_AREA_MODELS:
        return _seedream_factor(data)
    rates = IMAGE_OPTION_RATES.get(model)
    if not rates:
        return Decimal("1")
    value = str(data.get(rates["option"]) or rates["default"]).lower()
    table = rates["rates"]
    rate = table.get(value) or max(table.values(), key=Decimal)
    return Decimal(rate) / Decimal(rates["base"])


def _gpt_image_factor(model: str, data: dict[str, Any]) -> Decimal:
    table = GPT_IMAGE_RATES[model]
    quality = str(data.get("quality") or "high").lower()
    if quality not in table:  # "auto" may pick high, fal's default
        quality = "high"
    pixels = _requested_pixels(data) or 0
    bucket = sum(pixels > limit for limit in GPT_IMAGE_BUCKET_PIXELS)
    return Decimal(table[quality][bucket]) / Decimal(table["high"][0])


def _seedream_factor(data: dict[str, Any]) -> Decimal:
    pixels = _requested_pixels(data)
    small, large = SEEDREAM_TIER_PIXELS
    if pixels is not None and pixels <= small:
        return Decimal("1")
    if pixels is None or pixels <= large:
        return Decimal("2")  # fal picks the size when Admart sends none: assume the larger tier
    return Decimal("2") * Decimal(pixels) / Decimal(large)


def _image_extras_usd(capability: str, model: str, data: dict[str, Any]) -> Decimal:
    count = Decimal(max(1, int(data.get("numImages") or 1)))
    extras = Decimal("0")
    if data.get("enableWebSearch") and model in WEB_SEARCH_USD:
        extras += Decimal(WEB_SEARCH_USD[model]) * count
    if str(data.get("thinkingLevel") or "").lower() == "high" and model in HIGH_THINKING_USD:
        extras += Decimal(HIGH_THINKING_USD[model]) * count
    if capability in {"edit", "multiEdit"} and model in INPUT_IMAGE_USD:
        extras += Decimal(INPUT_IMAGE_USD[model]) * max(1, len(data.get("imageUrls") or []))
    return extras


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


# ── video quantity and options ─────────────────────────────────────────────


def _video_entry(capability: str, model: str) -> dict[str, Any]:
    for entry in VIDEO_MODEL_CATALOG.get(capability, []):
        if entry["id"] == model:
            return entry
    for models in VIDEO_MODEL_CATALOG.values():
        for entry in models:
            if entry["id"] == model:
                return entry
    return {}


def _video_seconds(capability: str, model: str, data: dict[str, Any]) -> int:
    """Seconds fal will render: the chosen duration; for "auto" or none, the longest it may render."""
    options = (_video_entry(capability, model).get("fields") or {}).get("duration") or []
    longest = max((s for s in map(_parse_duration_seconds, options) if s), default=5)
    raw = str(data.get("duration") or "").strip().lower()
    if raw == "auto":
        return max(AUTO_DURATION_SECONDS.get(model, longest), longest)
    return _parse_duration_seconds(raw) or longest


def _video_quantity(capability: str, model: str, data: dict[str, Any]) -> Decimal:
    unit = str(_price_row(model).get("unit", "")).lower()
    seconds = _video_seconds(capability, model, data)
    if unit in {"seconds", "compute seconds", "units"}:
        return Decimal(seconds)
    if unit == "1000 tokens":
        # Seedance family: fal bills per 1000 tokens.
        return _seedance_tokens(data, seconds) / Decimal("1000")
    if unit == "video segments":
        resolution = str(data.get("resolution") or PIXVERSE_DEFAULT_RESOLUTION).lower()
        segments = PIXVERSE_SEGMENTS.get(resolution, max(PIXVERSE_SEGMENTS.values()))
        return Decimal(segments * (2 if seconds > 5 else 1))
    return Decimal("1")


def _video_factor(capability: str, model: str, data: dict[str, Any]) -> Decimal:
    rates = VIDEO_OPTION_RATES.get(model)
    if not rates:
        return Decimal("1")
    table = rates["rates"]
    resolution = str(data.get("resolution") or "").lower()
    if resolution not in table:
        resolution = rates["default"] if not resolution else max(table, key=lambda r: Decimal(table[r][0]))
    with_audio, without_audio = table[resolution]
    rate = with_audio if _audio_on(capability, model, data) else without_audio
    return Decimal(rate) / Decimal(rates["base"])


def _audio_on(capability: str, model: str, data: dict[str, Any]) -> bool:
    # Admart only sends generate_audio for models whose catalog entry has the switch; otherwise
    # fal's default applies, and fal generates audio by default.
    fields = _video_entry(capability, model).get("fields") or {}
    return not (fields.get("generateAudio") and data.get("generateAudio") is False)


def _seedance_tokens(data: dict[str, Any], seconds: int) -> Decimal:
    """Estimate Seedance token count: (width * height * duration * 24) / 1024.

    Dimensions are inferred from the output resolution with a 16:9 basis,
    matching fal's published examples (720p = 1280x720, 480p = 864x496).
    """
    resolution = str(data.get("resolution") or "720p").lower()
    dims = {
        "480p": (864, 496),
        "720p": (1280, 720),
        "1080p": (1920, 1080),
        "4k": (3840, 2160),
    }
    width, height = dims.get(resolution, (1280, 720))
    return Decimal(max(1, width * height)) * Decimal(seconds) * Decimal("24") / Decimal("1024")


def _parse_duration_seconds(raw: Any) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return max(0, int(raw))
    text = str(raw).strip().lower().rstrip("s")
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else None
