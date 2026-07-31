"""Credits API for balance, live quotes, costs, and recent spend."""

from __future__ import annotations

from itertools import chain

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from content.catalog import CAPABILITIES, DEFAULT_MODELS, resolve_model
from content.models import ImageJob, VideoJob
from content.pricing import base_model_costs, quote_image_job, quote_response, quote_video_job
from content.video_catalog import (
    DEFAULT_VIDEO_MODELS,
    VIDEO_CAPABILITIES,
    VIDEO_MODEL_CATALOG,
    resolve_video_model,
)


class CreditsBalanceView(APIView):
    """GET /api/credits - current decimal fal-style balance."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        user.refresh_from_db()
        return Response(
            {
                "plan": user.plan,
                "creditsTotal": user.credits_total,
                "creditsUsed": user.credits_used,
                "creditsRemaining": user.credits_remaining,
                "creditsResetAt": user.credits_reset_at,
                "canGenerate": user.credits_remaining > 0,
                "currency": "fal credits",
            }
        )


class CreditsCostsView(APIView):
    """GET /api/credits/costs - default/base model costs."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        items = []
        for capability in CAPABILITIES:
            default_model = DEFAULT_MODELS[capability]
            quote = quote_image_job(capability, default_model, {"numImages": 1})
            items.append(
                {
                    "capability": capability,
                    "model": default_model,
                    "credits": quote_response(quote)["credits"],
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
            items.append(
                {
                    "capability": capability,
                    "model": default_model,
                    "credits": quote_response(quote)["credits"],
                    "perImage": False,
                    "notes": "Estimated cost per video job",
                }
            )

        return Response(
            {
                "currency": "fal credits",
                "items": items,
                "byCapability": {item["capability"]: item["credits"] for item in items},
                "byModel": base_model_costs(),
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
                    "currency": "fal credits",
                    "prompt": (job.prompt or "")[:120] or None,
                    "createdAt": job.created_at,
                }
            )
        return Response({"items": items})
