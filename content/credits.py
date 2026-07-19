"""Credit helpers for image jobs (uses User.credits_* integers)."""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

from django.db import transaction

from content.catalog import credit_cost as image_credit_cost
from content.video_catalog import VIDEO_CREDIT_COSTS, video_credit_cost


class InsufficientCredits(Exception):
    pass


def cost_for(capability: str, num_images: int = 1) -> int:
    """Whole-credit cost (ceil of Decimal table for integer User fields)."""
    if capability in VIDEO_CREDIT_COSTS:
        value = video_credit_cost(capability)
    else:
        value = image_credit_cost(capability, num_images)
    return int(value.to_integral_value(rounding=ROUND_CEILING))


@transaction.atomic
def reserve_credits(user, amount: int) -> None:
    user = type(user).objects.select_for_update().get(pk=user.pk)
    if user.credits_remaining < amount:
        raise InsufficientCredits()
    # Reserve by debiting immediately; refund on failure.
    user.credits_remaining -= amount
    user.credits_used += amount
    user.save(update_fields=["credits_remaining", "credits_used"])


@transaction.atomic
def refund_credits(user, amount: int) -> None:
    if amount <= 0:
        return
    user = type(user).objects.select_for_update().get(pk=user.pk)
    user.credits_remaining += amount
    user.credits_used = max(0, user.credits_used - amount)
    user.save(update_fields=["credits_remaining", "credits_used"])
