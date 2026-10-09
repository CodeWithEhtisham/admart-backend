"""Credit helpers for image/video jobs using decimal Admart credits."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

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
    model-specific Admart pricing is reflected.
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
def reserve_credits(user, amount: Decimal | int | float | str) -> Decimal:
    """Debit ``amount`` now (refunded on failure). Returns how much of it came from
    top-up credits, so a refund can give exactly those back as top-ups."""
    amount = quantize_credits(amount)
    user = type(user).objects.select_for_update().get(pk=user.pk)
    if user.credits_remaining < amount:
        raise InsufficientCredits()
    user.credits_remaining -= amount
    user.credits_used += amount
    # Plan credits are spent first; top-ups only shrink once the rest is gone.
    topup_before = user.topup_credits
    user.topup_credits = min(user.topup_credits, user.credits_remaining)
    user.save(update_fields=["credits_remaining", "credits_used", "topup_credits"])
    return topup_before - user.topup_credits


@transaction.atomic
def refund_credits(user, amount: Decimal | int | float | str, *, topup: Decimal | int = 0) -> None:
    """Return ``amount``; ``topup`` (the part reserve_credits took from top-ups) is
    restored as top-up credits so it still survives plan expiry."""
    amount = quantize_credits(amount)
    if amount <= 0:
        return
    user = type(user).objects.select_for_update().get(pk=user.pk)
    user.credits_remaining += amount
    user.credits_used = max(Decimal("0"), user.credits_used - amount)
    user.topup_credits = min(user.topup_credits + min(Decimal(topup), amount), user.credits_remaining)
    user.save(update_fields=["credits_remaining", "credits_used", "topup_credits"])


OPEN_JOB_STATUSES = ("queued", "running")


def fail_open_job(job, message: str) -> bool:
    """Fail a still-open job and refund its reservation exactly once.

    The status change is a single conditional UPDATE, so of several concurrent
    polls/cancels only one wins; the losers do nothing (no double refund).
    Returns True if this call failed the job. ``job`` is refreshed either way.
    """
    model = type(job)
    with transaction.atomic():
        reserved = (
            model.objects.filter(pk=job.pk, status__in=OPEN_JOB_STATUSES)
            .values("credits_reserved", "topup_credits_reserved")
            .first()
        )
        won = reserved is not None and model.objects.filter(
            pk=job.pk, status__in=OPEN_JOB_STATUSES
        ).update(
            status="failed",
            error=message,
            credits_reserved=0,
            topup_credits_reserved=0,
            updated_at=timezone.now(),
        ) == 1
        if won and reserved["credits_reserved"]:
            refund_credits(job.user, reserved["credits_reserved"], topup=reserved["topup_credits_reserved"])
    job.refresh_from_db()
    return won


def succeed_open_job(job, **fields) -> bool:
    """Mark a still-open job succeeded (charging its reservation) exactly once.

    Returns False if it was already finalized, e.g. cancelled and refunded while
    results were downloading; the result is then discarded. ``job`` is refreshed.
    """
    won = type(job).objects.filter(pk=job.pk, status__in=OPEN_JOB_STATUSES).update(
        status="succeeded",
        credits_used=F("credits_reserved"),
        error=None,
        updated_at=timezone.now(),
        **fields,
    ) == 1
    job.refresh_from_db()
    return won


def mark_open_job(job, status: str) -> None:
    """Move an open job between queued/running without resurrecting a finished one."""
    if job.status != status:
        type(job).objects.filter(pk=job.pk, status__in=OPEN_JOB_STATUSES).update(
            status=status, updated_at=timezone.now()
        )
        job.refresh_from_db()
