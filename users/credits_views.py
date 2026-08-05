"""Credits API for balance, live quotes, costs, and recent spend."""

from __future__ import annotations

from datetime import timedelta
from itertools import chain

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from content.catalog import CAPABILITIES, DEFAULT_MODELS, resolve_model
from content.models import ImageJob, VideoJob
from content.pricing import (
    ADMART_CREDIT_CURRENCY,
    HIGH_COST_MULTIPLIER,
    HIGH_COST_THRESHOLD,
    LOW_COST_MULTIPLIER,
    LOW_COST_THRESHOLD,
    MID_COST_MULTIPLIER,
    base_model_costs,
    quote_image_job,
    quote_response,
    quote_video_job,
    serialize_decimal,
)
from content.video_catalog import (
    DEFAULT_VIDEO_MODELS,
    VIDEO_CAPABILITIES,
    VIDEO_MODEL_CATALOG,
    resolve_video_model,
)
from users.plans import PUBLIC_PLAN_IDS, get_plan, serialize_plan


def balance_payload(user) -> dict:
    """Return the standard credit balance payload for a user."""
    return {
        "plan": user.plan,
        "planDetails": serialize_plan(user.plan),
        "creditsTotal": user.credits_total,
        "creditsUsed": user.credits_used,
        "creditsRemaining": user.credits_remaining,
        "creditsResetAt": user.credits_reset_at,
        "canGenerate": user.credits_remaining > 0,
        "currency": ADMART_CREDIT_CURRENCY,
    }


class CreditsBalanceView(APIView):
    """GET /api/credits - current decimal Admart credit balance."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        user.refresh_from_db()
        return Response(balance_payload(user))


class CreditsPlansView(APIView):
    """GET /api/credits/plans - public Basic/Plus/Pro subscription plans."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "currency": "USD",
                "localCurrency": "PKR",
                "items": [serialize_plan(plan_id) for plan_id in PUBLIC_PLAN_IDS],
                "paymentConnected": False,
            }
        )


class CreditsPlanActivateView(APIView):
    """POST /api/credits/plan - temporary plan activation until payments exist."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        plan_id = str(request.data.get("plan") or request.data.get("planId") or "").lower()
        plan = get_plan(plan_id)
        if plan["id"] not in PUBLIC_PLAN_IDS:
            return Response({"message": "Choose Basic, Plus, or Pro."}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        monthly_credits = plan["monthly_credits"]
        user.plan = plan["id"]
        user.credits_total = monthly_credits
        user.credits_used = 0
        user.credits_remaining = monthly_credits
        user.credits_reset_at = timezone.now() + timedelta(days=30)
        user.save(
            update_fields=[
                "plan",
                "credits_total",
                "credits_used",
                "credits_remaining",
                "credits_reset_at",
                "updated_at",
            ]
        )

        payload = balance_payload(user)
        payload["message"] = f"{plan['name']} plan activated for testing."
        payload["paymentConnected"] = False
        return Response(payload)


class CreditsCostsView(APIView):
    """GET /api/credits/costs - default/base model costs."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        items = []
        for capability in CAPABILITIES:
            default_model = DEFAULT_MODELS[capability]
            quote = quote_image_job(capability, default_model, {"numImages": 1})
            cost = quote_response(quote)
            items.append(
                {
                    **cost,
                    "capability": capability,
                    "model": default_model,
                    "perImage": capability == "textToImage",
                    "notes": (
                        "Estimated cost x numImages"
                        if capability == "textToImage"
                        else "Estimated cost per job"
                    ),
                }
            )

        for capability in VIDEO_CAPABILITIES:
            default_model = DEFAULT_VIDEO_MODELS[capability]
            entry = next(
                (m for m in VIDEO_MODEL_CATALOG[capability] if m["id"] == default_model),
                {},
            )
            settings_for_quote = {}
            fields = entry.get("fields") or {}
            if fields.get("duration"):
                settings_for_quote["duration"] = fields["duration"][0]
            quote = quote_video_job(capability, default_model, settings_for_quote)
            cost = quote_response(quote)
            items.append(
                {
                    **cost,
                    "capability": capability,
                    "model": default_model,
                    "perImage": False,
                    "notes": "Estimated cost per video job",
                }
            )

        return Response(
            {
                "currency": ADMART_CREDIT_CURRENCY,
                "items": items,
                "byCapability": {item["capability"]: item["credits"] for item in items},
                "byModel": base_model_costs(),
                "pricingFormula": [
                    {
                        "falCost": f"< {serialize_decimal(LOW_COST_THRESHOLD)}",
                        "markupMultiplier": serialize_decimal(LOW_COST_MULTIPLIER),
                    },
                    {
                        "falCost": (
                            f"{serialize_decimal(LOW_COST_THRESHOLD)} to "
                            f"{serialize_decimal(HIGH_COST_THRESHOLD)}"
                        ),
                        "markupMultiplier": serialize_decimal(MID_COST_MULTIPLIER),
                    },
                    {
                        "falCost": f"> {serialize_decimal(HIGH_COST_THRESHOLD)}",
                        "markupMultiplier": serialize_decimal(HIGH_COST_MULTIPLIER),
                    },
                ],
            }
        )


class CreditsQuoteView(APIView):
    """POST /api/credits/quote - estimate decimal credits before submit."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data or {}
        kind = (data.get("kind") or data.get("type") or "").strip()
        capability = (data.get("capability") or "").strip()
        model = (data.get("model") or "").strip()
        settings = data.get("settings") or {}
        if not isinstance(settings, dict):
            settings = {}

        try:
            if kind == "video" or capability in VIDEO_CAPABILITIES:
                if capability not in VIDEO_CAPABILITIES:
                    return Response({"message": "Invalid video capability"}, status=400)
                model = resolve_video_model(capability, model)
                quote = quote_video_job(capability, model, settings)
            else:
                if capability not in CAPABILITIES:
                    return Response({"message": "Invalid image capability"}, status=400)
                model = resolve_model(capability, model)
                quote = quote_image_job(capability, model, settings)
        except ValueError as exc:
            return Response({"message": str(exc)}, status=400)

        request.user.refresh_from_db()
        return Response(
            quote_response(quote, credits_remaining=request.user.credits_remaining)
        )


class CreditsHistoryView(APIView):
    """GET /api/credits/history - recent image and video credit spends."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            limit = min(int(request.query_params.get("limit", 20)), 50)
        except (TypeError, ValueError):
            limit = 20

        image_jobs = list(
            ImageJob.objects.filter(user=request.user).order_by("-created_at")[:limit]
        )
        video_jobs = list(
            VideoJob.objects.filter(user=request.user).order_by("-created_at")[:limit]
        )
        combined = sorted(
            chain(image_jobs, video_jobs),
            key=lambda j: j.created_at,
            reverse=True,
        )[:limit]

        items = []
        for job in combined:
            amount = job.credits_used if job.credits_used is not None else job.credits_reserved
            items.append(
                {
                    "id": str(job.id),
                    "projectId": str(job.project_id),
                    "capability": job.capability,
                    "model": job.model,
                    "status": job.status,
                    "credits": float(amount) if amount is not None else 0,
                    "currency": ADMART_CREDIT_CURRENCY,
                    "prompt": (job.prompt or "")[:120] or None,
                    "createdAt": job.created_at,
                }
            )
        return Response({"items": items})
