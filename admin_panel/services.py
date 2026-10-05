"""Aggregations powering the superadmin overview/stats endpoints."""

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

from admin_panel.models import AdminSetting, CreditAdjustment, Payment, Subscription
from content.models import ImageJob, VideoJob
from projects.models import Project, SocialAccount
from users.models import User
from users.plans import _plans_dict, get_plan

ACTIVE_DAYS = 30
CHART_DAYS = 30

PAID_PLANS = ("basic", "plus", "pro")

ZERO = Decimal("0")

DEFAULT_SETTINGS = {
    "default_free_credits": "0",
    "maintenance_banner": "",
    "easypaisa_number": "03XX-XXXXXXX",
    "easypaisa_name": "Admart Support",
}


def all_settings() -> dict:
    """Stored admin settings merged over seeded defaults."""
    stored = dict(AdminSetting.objects.values_list("key", "value"))
    merged = dict(DEFAULT_SETTINGS)
    merged.update(stored)
    return merged


def get_setting(key: str, default: str | None = None):
    return all_settings().get(key, default)


def free_signup_credits() -> Decimal:
    """Credits granted to a new Free-plan account (admin-editable setting)."""
    return Decimal(get_setting("default_free_credits", "0"))


def expire_subscription_if_due(user):
    """Downgrade a lapsed paid user to Free and forfeit unused plan credits.

    Runs on every authenticated request; the fast path is a field comparison.
    Top-up credits (``topup_credits``) are kept; everything else is forfeited.
    """
    if user.plan == "free" or not user.credits_reset_at or user.credits_reset_at > timezone.now():
        return user
    with transaction.atomic():
        user = User.objects.select_for_update().get(pk=user.pk)
        if user.plan == "free" or not user.credits_reset_at or user.credits_reset_at > timezone.now():
            return user
        plan = get_plan(user.plan)
        forfeit = max(ZERO, user.credits_remaining - user.topup_credits)
        user.plan = "free"
        user.credits_remaining -= forfeit
        user.credits_total -= forfeit
        user.credits_reset_at = None
        user.save(
            update_fields=["plan", "credits_remaining", "credits_total", "credits_reset_at", "updated_at"]
        )
        Subscription.objects.filter(user=user, status__in=["active", "trialing"]).update(
            status="expired", updated_at=timezone.now()
        )
        CreditAdjustment.objects.create(
            user=user,
            amount=-forfeit,
            reason="plan_change",
            notes=f"{plan['name']} subscription expired; unused plan credits forfeited",
        )
    return user


def _sum_by_currency(payments) -> dict:
    """Paid amounts per currency, e.g. {"PKR": 7999.0, "USD": 9.0}; never mixed."""
    return {
        currency: float(total)
        for currency, total in payments.values_list("currency").annotate(total=Sum("amount"))
    }


def _days_ago(days: int):
    return timezone.now() - timedelta(days=days)


def _day_series():
    start = (_days_ago(CHART_DAYS - 1)).date()
    return [start + timedelta(days=i) for i in range(CHART_DAYS)]


def _bucketed_daily(rows):
    """Turn (datetime, value) rows into a zero-filled daily series."""
    series = [d.isoformat() for d in _day_series()]
    buckets = {d: 0.0 for d in series}
    for dt, value in rows:
        key = dt.date().isoformat()
        if key in buckets:
            buckets[key] += float(value or 0)
    return [{"date": d, "value": round(buckets[d], 4)} for d in series]


def _job_series(qs):
    """Daily counts of jobs created in the chart window: total/succeeded/failed."""
    start = _days_ago(CHART_DAYS - 1)
    rows = qs.filter(created_at__gte=start).values_list("created_at", "status")
    series = [d.isoformat() for d in _day_series()]
    total = {d: 0 for d in series}
    succeeded = {d: 0 for d in series}
    failed = {d: 0 for d in series}
    for dt, status in rows:
        key = dt.date().isoformat()
        if key in total:
            total[key] += 1
            if status == "succeeded":
                succeeded[key] += 1
            elif status == "failed":
                failed[key] += 1
    return [
        {"date": d, "total": total[d], "succeeded": succeeded[d], "failed": failed[d]}
        for d in series
    ]


def build_stats() -> dict:
    """Everything the Overview tab needs in one payload (polled every ~10s)."""
    now = timezone.now()
    since_active = _days_ago(ACTIVE_DAYS)
    since_week = _days_ago(7)
    since_chart = _days_ago(CHART_DAYS - 1)

    users = User.objects.all()

    plan_counts = dict(users.values_list("plan").annotate(c=Count("id")))
    paid_count = sum(plan_counts.get(p, 0) for p in PAID_PLANS)

    credits = users.aggregate(
        total=Sum("credits_total"), used=Sum("credits_used"), remaining=Sum("credits_remaining")
    )

    image_jobs = ImageJob.objects.all()
    video_jobs = VideoJob.objects.all()
    job_totals = _count_jobs(image_jobs, video_jobs)

    social_by_platform = dict(
        SocialAccount.objects.filter(connected=True)
        .values_list("platform")
        .annotate(c=Count("id"))
    )

    active_subs = Subscription.objects.filter(status="active")
    plan_defs = _plans_dict()
    mrr_usd = ZERO
    mrr_pkr = 0
    for plan_id in active_subs.values_list("plan", flat=True):
        plan = plan_defs.get(plan_id)
        if plan:
            mrr_usd += Decimal(str(plan["price_usd"]))
            mrr_pkr += plan.get("price_pkr", 0)

    payments_month = Payment.objects.filter(status="paid", created_at__gte=since_active)
    failed_payments = Payment.objects.filter(
        created_at__gte=since_active, status__in=["failed", "pending"]
    ).count()

    return {
        "generatedAt": now,
        "totals": {
            "totalCustomers": users.count(),
            "activeLast30": users.filter(is_active=True, last_active_at__gte=since_active).count(),
            "disabled": users.filter(is_active=False).count(),
            "newThisWeek": users.filter(created_at__gte=since_week).count(),
            "newThisMonth": users.filter(created_at__gte=since_active).count(),
        },
        "plans": {
            "distribution": plan_counts,
            "paidCustomers": paid_count,
            "freeCustomers": plan_counts.get("free", 0),
        },
        "credits": {
            "issued": credits["total"] or 0,
            "used": credits["used"] or 0,
            "remaining": credits["remaining"] or 0,
        },
        "jobs": job_totals,
        "projects": {
            "total": Project.objects.count(),
            "activeLast30": Project.objects.filter(last_accessed_at__gte=since_active).count(),
        },
        "social": {
            "byPlatform": social_by_platform,
            "total": sum(social_by_platform.values()),
        },
        "revenue": {
            "mrrUsd": float(mrr_usd),
            "mrrPkr": mrr_pkr,
            "revenueThisMonth": _sum_by_currency(payments_month),
            "paymentsThisMonth": payments_month.count(),
            "failedPayments": failed_payments,
        },
        "charts": {
            "signups": _bucketed_daily(
                ((dt, 1) for dt in users.filter(created_at__gte=since_chart).values_list("created_at", flat=True))
            ),
            # ponytail: chart is PKR-only (EasyPaisa); per-currency series if USD sales grow
            "revenue": _bucketed_daily(
                Payment.objects.filter(
                    status="paid", currency="PKR", created_at__gte=since_chart
                ).values_list(
                    "created_at", "amount"
                )
            ),
            "creditsConsumed": _credits_consumed_daily(image_jobs, video_jobs),
            "jobs": {
                "image": _job_series(image_jobs),
                "video": _job_series(video_jobs),
            },
        },
        "recent": {
            "users": _recent_users(since_active),
            "payments": _recent_payments(),
        },
    }


def _count_jobs(image_qs, video_qs) -> dict:
    """Total/succeeded/failed counts for image and video jobs combined."""

    def totals(qs):
        rows = qs.aggregate(
            total=Count("id"),
            succeeded=Count("id", filter=Q(status="succeeded")),
            failed=Count("id", filter=Q(status="failed")),
            running=Count("id", filter=Q(status="running")),
            queued=Count("id", filter=Q(status="queued")),
        )
        return rows

    img = totals(image_qs)
    vid = totals(video_qs)
    combined = {
        "total": img["total"] + vid["total"],
        "succeeded": img["succeeded"] + vid["succeeded"],
        "failed": img["failed"] + vid["failed"],
        "running": img["running"] + vid["running"],
        "queued": img["queued"] + vid["queued"],
    }
    combined["successRate"] = (
        round(combined["succeeded"] / combined["total"] * 100, 1) if combined["total"] else 0
    )
    return {"image": img, "video": vid, "combined": combined}


def _credits_consumed_daily(image_qs, video_qs):
    """Daily Admart credits consumed by jobs (used if set, else reserved)."""
    start = _days_ago(CHART_DAYS - 1)
    rows = []
    for qs in (image_qs, video_qs):
        for dt, used, reserved in qs.filter(created_at__gte=start).values_list(
            "created_at", "credits_used", "credits_reserved"
        ):
            amount = used if used is not None else reserved
            rows.append((dt, amount if amount is not None else 0))
    return _bucketed_daily(rows)


def _recent_users(since_active):
    """A small list of recently active/new customers for the Overview feed."""
    qs = (
        User.objects.order_by("-last_active_at", "-created_at")[:8]
        if User.objects.filter(last_active_at__isnull=False).exists()
        else User.objects.order_by("-created_at")[:8]
    )
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "firstName": u.first_name,
            "lastName": u.last_name,
            "avatarUrl": u.avatar_url,
            "plan": u.plan,
            "isActive": u.is_active,
            "lastActiveAt": u.last_active_at,
            "createdAt": u.created_at,
        }
        for u in qs
    ]


def _recent_payments():
    return [
        {
            "id": str(p.id),
            "email": p.user.email,
            "amount": float(p.amount),
            "currency": p.currency,
            "method": p.method,
            "status": p.status,
            "createdAt": p.created_at,
        }
        for p in Payment.objects.select_related("user").order_by("-created_at")[:8]
    ]


def build_usage() -> dict:
    """Detailed usage breakdown for the Usage & Credits tab.

    Returns both Admart credit totals and raw fal.ai API cost totals.
    """
    image_jobs = ImageJob.objects.all()
    video_jobs = VideoJob.objects.all()

    def status_counts(qs):
        return {
            "total": qs.count(),
            "succeeded": qs.filter(status="succeeded").count(),
            "failed": qs.filter(status="failed").count(),
            "running": qs.filter(status="running").count(),
            "queued": qs.filter(status="queued").count(),
        }

    def capability_counts(qs):
        return dict(qs.values_list("capability").annotate(c=Count("id")))

    def admart_credits_by_cap(qs):
        return dict(
            qs.exclude(credits_used__isnull=True)
            .values_list("capability")
            .annotate(total=Sum("credits_used"))
        )

    def fal_cost_by_model(qs):
        return dict(
            qs.exclude(fal_cost_usd=0)
            .values_list("model")
            .annotate(total=Sum("fal_cost_usd"))
        )

    def fal_cost_by_cap(qs):
        return dict(
            qs.exclude(fal_cost_usd=0)
            .values_list("capability")
            .annotate(total=Sum("fal_cost_usd"))
        )

    # Admart credits totals
    img_credits_used = image_jobs.filter(
        credits_used__isnull=False
    ).aggregate(total=Sum("credits_used"))["total"] or 0
    vid_credits_used = video_jobs.filter(
        credits_used__isnull=False
    ).aggregate(total=Sum("credits_used"))["total"] or 0

    # fal.ai raw API costs
    img_fal_cost = image_jobs.aggregate(total=Sum("fal_cost_usd"))["total"] or 0
    vid_fal_cost = video_jobs.aggregate(total=Sum("fal_cost_usd"))["total"] or 0

    top_users = (
        User.objects.select_related()
        .prefetch_related("image_jobs", "video_jobs")
        .order_by("-credits_used")[:10]
    )

    return {
        "admart": {
            "totalCreditsUsed": float(img_credits_used + vid_credits_used),
            "byCapability": {
                **{k: float(v) for k, v in admart_credits_by_cap(image_jobs).items()},
                **{k: float(v) for k, v in admart_credits_by_cap(video_jobs).items()},
            },
        },
        "falAi": {
            "totalCostUsd": float(img_fal_cost + vid_fal_cost),
            "byCapability": {
                **{k: float(v) for k, v in fal_cost_by_cap(image_jobs).items()},
                **{k: float(v) for k, v in fal_cost_by_cap(video_jobs).items()},
            },
            "byModel": {
                **{k: float(v) for k, v in fal_cost_by_model(image_jobs).items()},
                **{k: float(v) for k, v in fal_cost_by_model(video_jobs).items()},
            },
        },
        "image": {
            "byStatus": status_counts(image_jobs),
            "byCapability": capability_counts(image_jobs),
        },
        "video": {
            "byStatus": status_counts(video_jobs),
            "byCapability": capability_counts(video_jobs),
        },
        "topConsumers": [
            {
                "id": str(u.id),
                "email": u.email,
                "firstName": u.first_name,
                "lastName": u.last_name,
                "plan": u.plan,
                "creditsUsed": float(u.credits_used or 0),
                "jobs": u.image_jobs.count() + u.video_jobs.count(),
            }
            for u in top_users
        ],
    }


def build_revenue() -> dict:
    """Revenue summary for the Payments/Plans tabs."""
    since_active = _days_ago(ACTIVE_DAYS)

    payments = Payment.objects.all()
    by_status = dict(payments.values_list("status").annotate(c=Count("id")))
    by_method = dict(payments.values_list("method").annotate(c=Count("id")))

    plan_revenue = (
        payments.filter(status="paid", payment_type="subscription")
        .exclude(plan="")
        .values_list("plan", "currency")
        .annotate(total=Sum("amount"))
    )
    per_plan_by_key = {}
    for plan_id, currency, total in plan_revenue:
        item = per_plan_by_key.setdefault(plan_id, {"plan": plan_id, "totals": {}, "count": 0})
        item["totals"][currency] = float(total)
    per_plan = list(per_plan_by_key.values())

    active_subs = Subscription.objects.filter(status="active").values_list("plan")
    sub_counts = {}
    for (plan_id,) in active_subs:
        sub_counts[plan_id] = sub_counts.get(plan_id, 0) + 1
    for plan_id in sub_counts:
        if plan_id in per_plan_by_key:
            per_plan_by_key[plan_id]["count"] = sub_counts[plan_id]


    return {
        "totalRevenue": _sum_by_currency(payments.filter(status="paid")),
        "thisMonth": _sum_by_currency(payments.filter(status="paid", created_at__gte=since_active)),
        "byStatus": by_status,
        "byMethod": by_method,
        "byPlan": per_plan,
        "subscriptionCounts": sub_counts,
    }


@transaction.atomic
def review_payment(payment_id, decision: str, admin, reason: str = "") -> Payment:
    """Approve or reject a pending manual payment.

    Approve: marks paid, upgrades the user's plan, adds the plan's monthly
    credits on top of the current balance, extends the subscription 30 days
    (from the current period end when renewing the same active plan),
    and writes an audited CreditAdjustment. Reject: marks failed and stores
    the reason for the client; no credit/plan changes.

    Raises ValidationError when the payment is not pending (guards against
    double-approve) or the decision is unknown.
    """
    payment = (
        Payment.objects.select_for_update()
        .select_related("user")
        .filter(pk=payment_id)
        .first()
    )
    if payment is None:
        raise ValidationError({"paymentId": "Payment not found."})
    if payment.status != "pending":
        raise ValidationError(
            {"paymentId": f"Payment already reviewed ({payment.status})."}
        )
    if decision not in ("approve", "reject"):
        raise ValidationError({"decision": "Decision must be approve or reject."})

    payment.reviewed_by = admin
    payment.reviewed_at = timezone.now()

    if decision == "reject":
        payment.status = "failed"
        reason = (reason or "").strip()
        if reason:
            payment.notes = reason
        payment.save(
            update_fields=["status", "reviewed_by", "reviewed_at", "notes", "updated_at"]
        )
        return payment

    if getattr(payment, "payment_type", "subscription") == "topup":
        from users.packs import get_topup_pack

        pack = get_topup_pack(payment.pack or None)
        if not pack:
            raise ValidationError({"pack": f"Unknown top-up pack: {payment.pack}."})
        added_credits = pack["credits"]
        user = payment.user

        payment.status = "paid"
        user.credits_total += added_credits
        user.credits_remaining += added_credits
        user.topup_credits += added_credits
        user.save(
            update_fields=[
                "credits_total",
                "credits_remaining",
                "topup_credits",
                "updated_at",
            ]
        )

        CreditAdjustment.objects.create(
            user=user,
            performed_by=payment.reviewed_by,
            amount=added_credits,
            reason="topup",
            notes=f"{pack['name']} purchased via {payment.method}",
        )

        payment.save(
            update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"]
        )
        return payment

    plan = get_plan(payment.plan or None)
    monthly_credits = plan["monthly_credits"]
    user = payment.user

    # Renewing the same active plan extends from the current end (no lost days);
    # a new or switched plan starts now. Credits stack: leftovers stay until expiry.
    now = timezone.now()
    renewing = user.plan == plan["id"] and user.credits_reset_at and user.credits_reset_at > now
    period_end = (user.credits_reset_at if renewing else now) + timedelta(days=30)

    payment.status = "paid"
    user.plan = plan["id"]
    user.credits_total += monthly_credits
    user.credits_remaining += monthly_credits
    user.credits_reset_at = period_end
    user.save(
        update_fields=[
            "plan",
            "credits_total",
            "credits_remaining",
            "credits_reset_at",
            "updated_at",
        ]
    )

    sub = Subscription.objects.filter(user=user).order_by("-created_at").first()
    if sub is None:
        Subscription.objects.create(
            user=user,
            plan=plan["id"],
            status="active",
            auto_renew=True,
            current_period_end=period_end,
        )
    else:
        sub.plan = plan["id"]
        sub.status = "active"
        sub.auto_renew = True
        sub.current_period_end = period_end
        sub.save(update_fields=["plan", "status", "auto_renew", "current_period_end", "updated_at"])

    CreditAdjustment.objects.create(
        user=user,
        performed_by=payment.reviewed_by,
        amount=monthly_credits,
        reason="payment",
        notes=f"{plan['name']} purchased via {payment.method}",
    )

    payment.save(
        update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"]
    )
    return payment
