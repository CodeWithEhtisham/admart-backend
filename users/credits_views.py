"""Credits API for balance, live quotes, costs, and recent spend."""

from __future__ import annotations

from itertools import chain

from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admin_panel.models import Payment
from admin_panel.services import get_setting
from content.catalog import CAPABILITIES, DEFAULT_MODELS, resolve_model
from content.models import ImageJob, VideoJob
from content.pricing import (
    ADMART_CREDIT_CURRENCY,
    MARKUP_CURVE_NUMERATOR,
    MIN_MARKUP,
    admart_markup_multiplier,
    base_model_costs,
    quote_image_job,
    quote_response,
    quote_video_job,
    serialize_decimal,
)
from content.storage_utils import absolute_media_url
from content.video_catalog import (
    DEFAULT_VIDEO_MODELS,
    VIDEO_CAPABILITIES,
    VIDEO_MODEL_CATALOG,
    resolve_video_model,
)
from users.plans import PUBLIC_PLAN_IDS, get_plan, serialize_plan
from users.serializers import PaymentSubmitSerializer


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

    permission_classes = [AllowAny]

    def get(self, request):
        return Response(
            {
                "currency": "USD",
                "localCurrency": "PKR",
                "items": [serialize_plan(plan_id) for plan_id in PUBLIC_PLAN_IDS],
                "paymentConnected": True,
            }
        )


class CreditsTopupsView(APIView):
    """GET /api/credits/topups - public on-demand credit top-up packs."""

    permission_classes = [AllowAny]

    def get(self, request):
        from users.packs import get_public_topup_packs

        return Response(
            {
                "currency": "USD",
                "localCurrency": "PKR",
                "items": get_public_topup_packs(),
            }
        )


def _serialize_payment(payment: Payment, *, request) -> dict:
    """Client-facing manual payment representation."""
    from users.packs import get_topup_pack

    is_topup = getattr(payment, "payment_type", "subscription") == "topup"
    plan = get_plan(payment.plan or None) if not is_topup else None
    pack = get_topup_pack(payment.pack or None) if is_topup else None

    if is_topup and pack:
        display_name = pack["name"]
    elif plan:
        display_name = plan["name"]
    else:
        display_name = payment.plan or payment.pack or "Payment"

    return {
        "id": str(payment.id),
        "paymentType": getattr(payment, "payment_type", "subscription"),
        "plan": payment.plan,
        "pack": getattr(payment, "pack", ""),
        "planName": display_name,
        "amount": payment.amount,
        "currency": payment.currency,
        "method": payment.method,
        "status": payment.status,
        "transactionId": payment.provider_ref,
        "note": payment.notes,
        "message": payment.notes if payment.status == "failed" else "",
        "screenshotUrl": (
            absolute_media_url(payment.screenshot.name, request=request)
            if payment.screenshot
            else None
        ),
        "createdAt": payment.created_at,
        "reviewedAt": payment.reviewed_at,
    }


class CreditsPaymentMethodsView(APIView):
    """GET /api/credits/payments/methods - manual payment instructions."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "methods": [
                    {
                        "id": "easypaisa",
                        "label": "EasyPaisa",
                        "accountNumber": get_setting("easypaisa_number", ""),
                        "accountName": get_setting("easypaisa_name", ""),
                    }
                ]
            }
        )


class CreditsPaymentSubmitView(APIView):
    """POST /api/credits/payments/submit - upload EasyPaisa payment proof."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        serializer = PaymentSubmitSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        payment_type = data.get("paymentType", "subscription")

        if payment_type == "topup":
            from users.packs import get_topup_pack

            pack = get_topup_pack(data["pack"])
            payment = Payment(
                user=request.user,
                payment_type="topup",
                pack=pack["id"],
                amount=pack["price_pkr"],
                currency="PKR",
                method="easypaisa",
                status="pending",
                provider_ref=data["transactionId"],
                notes=data["note"],
            )
        else:
            plan = get_plan(data["plan"])
            payment = Payment(
                user=request.user,
                payment_type="subscription",
                plan=plan["id"],
                amount=plan["price_pkr"],
                currency="PKR",
                method="easypaisa",
                status="pending",
                provider_ref=data["transactionId"],
                notes=data["note"],
            )
        payment.screenshot.save(data["screenshot"].name, data["screenshot"], save=True)
        return Response(
            _serialize_payment(payment, request=request),
            status=status.HTTP_201_CREATED,
        )


class CreditsMyPaymentsView(APIView):
    """GET /api/credits/payments/mine - the user's submitted payments."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        payments = (
            Payment.objects.filter(user=request.user).order_by("-created_at")[:20]
        )
        return Response(
            {"items": [_serialize_payment(p, request=request) for p in payments]}
        )


class CreditsCostsView(APIView):
    """GET /api/credits/costs - default/base model costs."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        nano_quote = quote_image_job("textToImage", "fal-ai/nano-banana-2", {"numImages": 1})
        gpt_quote = quote_image_job("textToImage", "openai/gpt-image-2", {"numImages": 1})
        veo_quote = quote_video_job("textToVideo", "fal-ai/veo3.1", {"duration": "8s"})
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
                        "label": "Smooth markup curve",
                        "falCost": "any",
                        "markupMultiplier": "dynamic",
                        "formula": "price = falCost * (1 + max(0.25, 1.2 / (falCost + 1)))",
                        "minimumMarkup": serialize_decimal(MIN_MARKUP),
                        "curveNumerator": serialize_decimal(MARKUP_CURVE_NUMERATOR),
                    },
                    {
                        "label": "Nano Banana 2 example",
                        "falCost": quote_response(nano_quote)["falCost"],
                        "markupMultiplier": serialize_decimal(admart_markup_multiplier("0.08")),
                        "admartCredits": quote_response(nano_quote)["credits"],
                    },
                    {
                        "label": "GPT Image 2 example",
                        "falCost": quote_response(gpt_quote)["falCost"],
                        "markupMultiplier": serialize_decimal(admart_markup_multiplier("1")),
                        "admartCredits": quote_response(gpt_quote)["credits"],
                    },
                    {
                        "label": "Veo 3.1 8s example",
                        "falCost": quote_response(veo_quote)["falCost"],
                        "markupMultiplier": serialize_decimal(admart_markup_multiplier("3.2")),
                        "admartCredits": quote_response(veo_quote)["credits"],
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
