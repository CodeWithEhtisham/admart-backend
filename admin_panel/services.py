"""Aggregations powering the superadmin overview/stats endpoints."""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from admin_panel.models import AdminSetting, Payment, Subscription
from content.models import ImageJob, VideoJob
from projects.models import Project, SocialAccount
from users.models import User
from users.plans import _plans_dict

ACTIVE_DAYS = 30
CHART_DAYS = 30

PAID_PLANS = ("basic", "plus", "pro")

ZERO = Decimal("0")

DEFAULT_SETTINGS = {
    "default_free_credits": "50",
    "maintenance_banner": "",
}


def all_settings() -> dict:
    """Stored admin settings merged over seeded defaults."""
    stored = dict(AdminSetting.objects.values_list("key", "value"))
    merged = dict(DEFAULT_SETTINGS)
    merged.update(stored)
    return merged


def get_setting(key: str, default: str | None = None):
    return all_settings().get(key, default)


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
    revenue_month = payments_month.aggregate(total=Sum("amount"))["total"] or 0
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
            "revenueThisMonthUsd": float(revenue_month),
            "paymentsThisMonth": payments_month.count(),
            "failedPayments": failed_payments,
        },
        "charts": {
            "signups": _bucketed_daily(
                ((dt, 1) for dt in users.filter(created_at__gte=since_chart).values_list("created_at", flat=True))
            ),
            "revenue": _bucketed_daily(
                Payment.objects.filter(status="paid", created_at__gte=since_chart).values_list(
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
        payments.filter(status="paid")
        .values_list("user__plan")
        .annotate(total=Sum("amount"))
    )
    per_plan = [
        {"plan": plan_id, "totalUsd": float(total), "count": 0}
        for plan_id, total in plan_revenue
    ]
    per_plan_by_key = {item["plan"]: item for item in per_plan}

    active_subs = Subscription.objects.filter(status="active").values_list("plan")
    sub_counts = {}
    for (plan_id,) in active_subs:
        sub_counts[plan_id] = sub_counts.get(plan_id, 0) + 1
    for plan_id in sub_counts:
        if plan_id in per_plan_by_key:
            per_plan_by_key[plan_id]["count"] = sub_counts[plan_id]

    total_revenue = payments.filter(status="paid").aggregate(total=Sum("amount"))["total"] or 0
    month_revenue = (
        payments.filter(status="paid", created_at__gte=since_active).aggregate(total=Sum("amount"))["total"]
        or 0
    )

    return {
        "totalRevenueUsd": float(total_revenue),
        "thisMonthUsd": float(month_revenue),
        "byStatus": by_status,
        "byMethod": by_method,
        "byPlan": per_plan,
        "subscriptionCounts": sub_counts,
    }
