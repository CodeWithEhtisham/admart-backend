"""Credit helpers for image/video jobs using decimal fal-style credits."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from content.catalog import DEFAULT_MODELS
from content.pricing import quote_image_job, quote_video_job, quantize_credits
from content.video_catalog import DEFAULT_VIDEO_MODELS


class InsufficientCredits(Exception):
    pass


def cost_for(
    capability: str,
    num_images: int = 1,
    *,
    model: str | None = None,
    settings: dict | None = None,
) -> Decimal:
    """Return the current decimal credit estimate for a request.

    Kept for older callers/tests; new job creation should pass model/settings so
    model-specific fal pricing is reflected.
    """
    data = dict(settings or {})
    data.setdefault("numImages", num_images)
    if capability in DEFAULT_VIDEO_MODELS:
        return quote_video_job(capability, model or DEFAULT_VIDEO_MODELS[capability], data)[
            "credits_decimal"
        ]
    return quote_image_job(capability, model or DEFAULT_MODELS[capability], data)[
        "credits_decimal"
    ]


@transaction.atomic
def reserve_credits(user, amount: Decimal | int | float | str) -> None:
    amount = quantize_credits(amount)
    user = type(user).objects.select_for_update().get(pk=user.pk)
    if user.credits_remaining < amount:
        raise InsufficientCredits()
    # Reserve by debiting immediately; refund on failure.
    user.credits_remaining -= amount
    user.credits_used += amount
    user.save(update_fields=["credits_remaining", "credits_used"])


@transaction.atomic
def refund_credits(user, amount: Decimal | int | float | str) -> None:
    amount = quantize_credits(amount)
    if amount <= 0:
        return
    user = type(user).objects.select_for_update().get(pk=user.pk)
    user.credits_remaining += amount
    user.credits_used = max(Decimal("0"), user.credits_used - amount)
    user.save(update_fields=["credits_remaining", "credits_used"])
