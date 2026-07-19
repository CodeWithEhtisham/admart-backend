"""Credits API for the frontend (balance, costs, recent spend)."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from content.catalog import CAPABILITIES, CREDIT_COSTS, credit_cost
from content.models import ImageJob


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
                # Convenience for FE badges / disable Generate
                "canGenerate": user.credits_remaining > 0,
            }
        )


class CreditsCostsView(APIView):
    """GET /api/credits/costs — credit price per image capability."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        items = []
        for capability in CAPABILITIES:
            cost = int(credit_cost(capability, 1))
            items.append(
                {
                    "capability": capability,
                    "credits": cost,
                    # textToImage scales with numImages; others are flat for now
                    "perImage": capability == "textToImage",
                    "notes": (
                        "Cost × numImages"
                        if capability == "textToImage"
                        else "Flat cost per job"
                    ),
                }
            )
        return Response(
            {
                "currency": "credits",
                "items": items,
                # Raw map for quick lookups: { textToImage: 1, edit: 1, ... }
                "byCapability": {c: int(CREDIT_COSTS[c]) for c in CAPABILITIES},
            }
        )


class CreditsHistoryView(APIView):
    """GET /api/credits/history — recent credit spends from image jobs."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            limit = min(int(request.query_params.get("limit", 20)), 50)
        except (TypeError, ValueError):
            limit = 20

        jobs = (
            ImageJob.objects.filter(user=request.user)
            .order_by("-created_at")[:limit]
        )
        items = []
        for job in jobs:
            # Show reserved amount for open jobs; finalized amount when set
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
