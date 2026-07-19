"""Credits API for the frontend (balance, costs, recent spend)."""

from __future__ import annotations

from itertools import chain

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from content.catalog import CAPABILITIES, CREDIT_COSTS, credit_cost
from content.models import ImageJob, VideoJob
from content.video_catalog import VIDEO_CAPABILITIES, VIDEO_CREDIT_COSTS, video_credit_cost


class CreditsBalanceView(APIView):
    """GET /api/credits — current balance for the authenticated user."""

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
            }
        )


class CreditsCostsView(APIView):
    """GET /api/credits/costs — credit price per image/video capability."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        items = []
        for capability in CAPABILITIES:
            cost = int(credit_cost(capability, 1))
            items.append(
                {
                    "capability": capability,
                    "credits": cost,
                    "perImage": capability == "textToImage",
                    "notes": (
                        "Cost × numImages"
                        if capability == "textToImage"
                        else "Flat cost per job"
                    ),
                }
            )
        for capability in VIDEO_CAPABILITIES:
            cost = int(video_credit_cost(capability))
            items.append(
                {
                    "capability": capability,
                    "credits": cost,
                    "perImage": False,
                    "notes": "Flat cost per video job",
                }
            )
        by_capability = {c: int(CREDIT_COSTS[c]) for c in CAPABILITIES}
        by_capability.update({c: int(VIDEO_CREDIT_COSTS[c]) for c in VIDEO_CAPABILITIES})
        return Response(
            {
                "currency": "credits",
                "items": items,
                "byCapability": by_capability,
            }
        )


class CreditsHistoryView(APIView):
    """GET /api/credits/history — recent credit spends from image + video jobs."""

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
                    "prompt": (job.prompt or "")[:120] or None,
                    "createdAt": job.created_at,
                }
            )
        return Response({"items": items})
