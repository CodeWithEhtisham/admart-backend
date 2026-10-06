from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import unquote

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView

from admin_panel.permissions import IsAdmin, IsOwnerAdmin
from admin_panel.models import AdminSetting, CreditAdjustment, Payment, PlanDefinition, Subscription, TopupPack
from admin_panel.serializers import (
    AdminUserDetailSerializer,
    AdminUserSerializer,
    PaymentCreateSerializer,
    PaymentSerializer,
)
from admin_panel.services import (
    all_settings,
    build_revenue,
    build_stats,
    build_usage,
    free_signup_credits,
    payment_screenshot_url,
    review_payment,
)
from users.authentication import AdmartJWTAuthentication
from users.packs import serialize_topup_pack
from users.plans import get_plan, serialize_plan, _plans_dict

User = get_user_model()


class AdminAPIView(APIView):
    """Base class for admin views — accepts both JWT (API) and session (admin dashboard) auth."""

    authentication_classes = [AdmartJWTAuthentication, SessionAuthentication]


class AdminStatsView(AdminAPIView):
    """GET /api/admin/stats — overview KPIs, charts, and recent activity."""

    permission_classes = [IsAdmin]

    @extend_schema(summary="Superadmin overview statistics")
    def get(self, request):
        return Response(build_stats())


class AdminUsageView(AdminAPIView):
    """GET /api/admin/usage — detailed job/credit usage breakdown."""

    permission_classes = [IsAdmin]

    @extend_schema(summary="Superadmin usage breakdown")
    def get(self, request):
        return Response(build_usage())


class AdminRevenueView(AdminAPIView):
    """GET /api/admin/revenue — payment and subscription revenue summary."""

    permission_classes = [IsAdmin]

    @extend_schema(summary="Superadmin revenue summary")
    def get(self, request):
        return Response(build_revenue())


class AdminPlansView(AdminAPIView):
    """GET /api/admin/plans — plan definitions with subscriber counts."""

    permission_classes = [IsAdmin]

    @extend_schema(summary="Superadmin plan definitions")
    def get(self, request):
        counts = dict(User.objects.values_list("plan").annotate(c=Count("id")))
        sub_counts = dict(
            Subscription.objects.filter(status="active").values_list("plan").annotate(c=Count("id"))
        )
        items = []
        for plan_def in PlanDefinition.objects.order_by("sort_order"):
            plan = serialize_plan(plan_def.plan_id)
            plan["subscriberCount"] = counts.get(plan_def.plan_id, 0)
            plan["activeSubscriptions"] = sub_counts.get(plan_def.plan_id, 0)
            plan["monthlyCredits"] = float(plan["monthlyCredits"])
            plan["isPublic"] = plan_def.is_public
            items.append(plan)
        return Response({"items": items})


def _non_negative_decimal(value) -> Decimal:
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        raise ValueError("must be a non-negative number")
    return number


def _non_negative_int(value) -> int:
    number = int(value)
    if number < 0:
        raise ValueError("must be a non-negative whole number")
    return number


def _features(value) -> list:
    if not isinstance(value, list):
        raise ValueError("must be a list of strings")
    return [str(f).strip() for f in value if str(f).strip()]


def _limits(value) -> dict:
    # The dashboard plan editor sends numbers (incl. fractional discount_percent) and booleans.
    if not isinstance(value, dict) or not all(
        isinstance(v, (bool, int, float)) for v in value.values()
    ):
        raise ValueError("must map each limit to a number or true/false")
    return value


def _flag(value) -> bool:
    if not isinstance(value, bool):
        raise ValueError("must be true or false")
    return value


def _text(value) -> str:
    return str(value).strip()


# API field -> (model attribute, parser) for admin-editable plans and packs.
PLAN_FIELDS = {
    "name": ("name", _text),
    "description": ("description", _text),
    "priceUsd": ("price_usd", _non_negative_decimal),
    "pricePkr": ("price_pkr", _non_negative_int),
    "monthlyCredits": ("monthly_credits", _non_negative_decimal),
    "features": ("features", _features),
    "limits": ("limits", _limits),
    "isPublic": ("is_public", _flag),
    "sortOrder": ("sort_order", int),
}
PACK_FIELDS = {
    "name": ("name", _text),
    "description": ("description", _text),
    "priceUsd": ("price_usd", _non_negative_decimal),
    "pricePkr": ("price_pkr", _non_negative_int),
    "credits": ("credits", _non_negative_decimal),
    "features": ("features", _features),
    "popular": ("popular", _flag),
    "isPublic": ("is_public", _flag),
    "sortOrder": ("sort_order", int),
}


def _apply_fields(obj, data: dict, fields: dict) -> Response | None:
    """Set each present field on ``obj``; 400 response on the first invalid value."""
    for key, (attr, parse) in fields.items():
        if key not in data:
            continue
        try:
            setattr(obj, attr, parse(data[key]))
        except (InvalidOperation, ValueError, TypeError) as exc:
            return Response({"message": f"{key}: {exc}"}, status=status.HTTP_400_BAD_REQUEST)
    if not obj.name:
        return Response({"message": "name: is required"}, status=status.HTTP_400_BAD_REQUEST)
    return None


class AdminPlanDetailView(AdminAPIView):
    """PUT/DELETE /api/admin/plans/<plan_id> — edit or delete a plan."""

    permission_classes = [IsOwnerAdmin]

    def _get_plan(self, plan_id):
        return get_object_or_404(PlanDefinition, plan_id=unquote(plan_id))

    @extend_schema(summary="Update a plan definition", request=None)
    def put(self, request, plan_id):
        plan = self._get_plan(plan_id)
        error = _apply_fields(plan, request.data or {}, PLAN_FIELDS)
        if error:
            return error
        plan.save()
        return Response(serialize_plan(plan.plan_id))

    @extend_schema(summary="Delete a plan definition", request=None)
    def delete(self, request, plan_id):
        plan = self._get_plan(plan_id)
        if plan.plan_id == "free":
            return Response({"message": "Cannot delete the free plan."}, status=status.HTTP_400_BAD_REQUEST)
        plan.delete()
        return Response({"message": "Plan deleted."}, status=status.HTTP_200_OK)


def _serialize_admin_pack(pack: TopupPack) -> dict:
    """Pack card for the admin panel: public fields plus visibility and order."""
    return {
        **serialize_topup_pack(
            {
                "id": pack.pack_id,
                "name": pack.name,
                "description": pack.description,
                "credits": pack.credits,
                "price_usd": pack.price_usd,
                "price_pkr": pack.price_pkr,
                "features": pack.features or [],
                "popular": pack.popular,
            }
        ),
        "isPublic": pack.is_public,
        "sortOrder": pack.sort_order,
        "purchases": Payment.objects.filter(
            payment_type="topup", pack=pack.pack_id, status="paid"
        ).count(),
    }


class AdminPacksView(AdminAPIView):
    """GET /api/admin/packs — all top-up packs, including hidden ones."""

    permission_classes = [IsAdmin]

    @extend_schema(summary="Superadmin top-up pack definitions")
    def get(self, request):
        return Response({"items": [_serialize_admin_pack(p) for p in TopupPack.objects.order_by("sort_order")]})


class AdminPackDetailView(AdminAPIView):
    """PUT /api/admin/packs/<pack_id> — edit a top-up pack."""

    permission_classes = [IsOwnerAdmin]

    @extend_schema(summary="Update a top-up pack", request=None)
    def put(self, request, pack_id):
        pack = get_object_or_404(TopupPack, pack_id=unquote(pack_id))
        error = _apply_fields(pack, request.data or {}, PACK_FIELDS)
        if error:
            return error
        pack.save()
        return Response(_serialize_admin_pack(pack))


class AdminPlanCreateView(AdminAPIView):
    """POST /api/admin/plans — create a new plan."""

    permission_classes = [IsOwnerAdmin]

    @extend_schema(summary="Create a new plan", request=None)
    def post(self, request):
        data = request.data or {}
        plan_id = (data.get("planId") or "").strip().lower()
        name = (data.get("name") or "").strip()
        if not plan_id or not name:
            return Response(
                {"message": "planId and name are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if PlanDefinition.objects.filter(plan_id=plan_id).exists():
            return Response(
                {"message": f"A plan with id '{plan_id}' already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        plan = PlanDefinition.objects.create(
            plan_id=plan_id,
            name=name,
            description=data.get("description", ""),
            price_usd=Decimal(str(data.get("priceUsd", 0))),
            price_pkr=int(data.get("pricePkr", 0)),
            monthly_credits=Decimal(str(data.get("monthlyCredits", 0))),
            features=list(data.get("features", [])),
            limits=dict(data.get("limits", {})),
            is_public=bool(data.get("isPublic", True)),
            sort_order=int(data.get("sortOrder", 100)),
        )
        return Response(serialize_plan(plan.plan_id), status=status.HTTP_201_CREATED)


class AdminUserListView(AdminAPIView):
    """GET /api/admin/users — paginated, filterable customer list.

    POST (superuser) creates a customer account manually.
    """

    def get_permissions(self):
        return [IsOwnerAdmin()] if self.request.method == "POST" else [IsAdmin()]

    @extend_schema(summary="List customers for admin")
    def get(self, request):
        qs = User.objects.all()
        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                email__icontains=search
            ) | qs.filter(first_name__icontains=search) | qs.filter(last_name__icontains=search)

        plan = (request.query_params.get("plan") or "").strip()
        if plan:
            qs = qs.filter(plan=plan)

        status_flag = (request.query_params.get("status") or "").strip()
        if status_flag == "active":
            qs = qs.filter(is_active=True)
        elif status_flag == "inactive":
            qs = qs.filter(is_active=False)

        try:
            page = max(int(request.query_params.get("page", 1)), 1)
            page_size = min(max(int(request.query_params.get("pageSize", 20)), 1), 100)
        except (TypeError, ValueError):
            page, page_size = 1, 20

        total = qs.count()
        items = (
            qs.select_related()
            .prefetch_related(
                "projects",
                "projects__social_accounts",
                "image_jobs",
                "video_jobs",
                "subscriptions",
                "payments",
            )
            .order_by("-created_at")[(page - 1) * page_size : page * page_size]
        )
        return Response(
            {
                "items": AdminUserSerializer(items, many=True).data,
                "total": total,
                "page": page,
                "pageSize": page_size,
            }
        )

    @extend_schema(summary="Create a customer account manually", request=None)
    def post(self, request):
        data = request.data or {}
        email = (data.get("email") or "").strip().lower()
        if not email:
            return Response({"message": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)
        if User.objects.filter(email=email).exists():
            return Response({"message": "A user with this email already exists."}, status=status.HTTP_400_BAD_REQUEST)

        plan_id = (data.get("plan") or "free").lower()
        plan = get_plan(plan_id)
        monthly_credits = (
            free_signup_credits()
            if plan["id"] == "free"
            else plan["monthly_credits"]
        )

        user = User.objects.create(
            email=email,
            first_name=(data.get("firstName") or "").strip(),
            last_name=(data.get("lastName") or "").strip(),
            plan=plan["id"],
            credits_total=monthly_credits,
            credits_used=0,
            credits_remaining=monthly_credits,
            credits_reset_at=timezone.now() + timedelta(days=30),
            onboarding_completed=True,
        )
        Subscription.objects.create(
            user=user, plan=plan["id"], status="active",
            current_period_end=timezone.now() + timedelta(days=30),
        )
        return Response(AdminUserSerializer(user).data, status=status.HTTP_201_CREATED)
class AdminUserDetailView(AdminAPIView):
    """GET/PATCH/DELETE /api/admin/users/{id} — customer detail, support actions, delete."""

    def get_permissions(self):
        if self.request.method == "DELETE":
            return [IsOwnerAdmin()]
        return [IsAdmin()]

    def _get_user(self, user_id):
        return get_object_or_404(
            User.objects.prefetch_related(
                "projects",
                "projects__social_accounts",
                "image_jobs",
                "video_jobs",
                "subscriptions",
                "payments",
                "credit_adjustments__performed_by",
            ),
            pk=user_id,
        )

    @extend_schema(summary="Customer detail for admin")
    def get(self, request, user_id):
        return Response(AdminUserDetailSerializer(self._get_user(user_id)).data)

    @extend_schema(summary="Update customer support fields")
    def patch(self, request, user_id):
        user = self._get_user(user_id)
        data = request.data or {}
        allowed = {"isActive": "is_active", "onboardingCompleted": "onboarding_completed"}
        update_fields = []
        for camel, field in allowed.items():
            if camel in data:
                setattr(user, field, bool(data[camel]))
                update_fields.append(field)
        if update_fields:
            update_fields.append("updated_at")
            user.save(update_fields=update_fields)
        return Response(AdminUserSerializer(user).data)

    @extend_schema(summary="Delete a customer account")
    def delete(self, request, user_id):
        from users.deletion import delete_account

        user = self._get_user(user_id)
        delete_account(user)
        return Response({"message": "User deleted."}, status=status.HTTP_200_OK)


class AdminUserPlanView(AdminAPIView):
    """POST /api/admin/users/{id}/plan — change plan + optional credit reset/top-up."""

    permission_classes = [IsOwnerAdmin]

    @extend_schema(summary="Change a customer's plan", request=None)
    def post(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)
        data = request.data or {}
        plan_id = (data.get("plan") or "").lower()
        if plan_id not in _plans_dict():
            return Response(
                {"message": f"Invalid plan. Choose from: {', '.join(_plans_dict().keys())}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        plan = get_plan(plan_id)
        credits_mode = data.get("creditsMode") or "reset"
        notes = (data.get("notes") or "").strip()

        adjustment = 0
        if credits_mode == "reset":
            adjustment = plan["monthly_credits"] - user.credits_total
            user.credits_total = plan["monthly_credits"]
            user.credits_used = 0
            user.credits_remaining = plan["monthly_credits"]
            user.topup_credits = 0
            user.credits_reset_at = timezone.now() + timedelta(days=30)
        elif credits_mode == "topup":
            try:
                add = Decimal(str(data.get("creditsToAdd") or 0))
            except (TypeError, ValueError):
                add = Decimal("0")
            adjustment = add
            user.credits_total += add
            user.credits_remaining += add

        user.plan = plan["id"]
        user.save(
            update_fields=[
                "plan", "credits_total", "credits_used", "credits_remaining",
                "topup_credits", "credits_reset_at", "updated_at",
            ]
        )

        sub = Subscription.objects.filter(user=user).order_by("-created_at").first()
        if sub is None:
            Subscription.objects.create(
                user=user, plan=plan["id"], status="active", auto_renew=True,
                current_period_end=timezone.now() + timedelta(days=30),
            )
        else:
            sub.plan = plan["id"]
            sub.status = "active"
            sub.auto_renew = True
            sub.current_period_end = timezone.now() + timedelta(days=30)
            sub.save(update_fields=["plan", "status", "auto_renew", "current_period_end", "updated_at"])
        if adjustment:
            CreditAdjustment.objects.create(
                user=user,
                performed_by=request.user,
                amount=adjustment,
                reason="plan_change",
                notes=notes or f"Plan changed to {plan['name']}",
            )

        return Response(AdminUserSerializer(user).data)


class AdminUserCreditsView(AdminAPIView):
    """POST /api/admin/users/{id}/credits — grant or deduct credits (audited)."""

    permission_classes = [IsOwnerAdmin]

    @extend_schema(summary="Adjust a customer's credits", request=None)
    def post(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)
        data = request.data or {}
        try:
            amount = Decimal(str(data.get("amount")))
        except (TypeError, ValueError):
            return Response({"message": "Amount is required."}, status=status.HTTP_400_BAD_REQUEST)
        if amount == 0:
            return Response({"message": "Amount must be non-zero."}, status=status.HTTP_400_BAD_REQUEST)

        reason = (data.get("reason") or "grant").lower()
        if reason not in dict(CreditAdjustment.REASON_CHOICES):
            reason = "grant"
        notes = (data.get("notes") or "").strip()

        user.credits_total = max(0, user.credits_total + amount)
        user.credits_remaining = max(0, user.credits_remaining + amount)
        user.topup_credits = min(user.topup_credits, user.credits_remaining)
        user.save(update_fields=["credits_total", "credits_remaining", "topup_credits", "updated_at"])
        CreditAdjustment.objects.create(
            user=user, performed_by=request.user, amount=amount, reason=reason, notes=notes
        )
        return Response(AdminUserSerializer(user).data)


class AdminPaymentListView(AdminAPIView):
    """GET /api/admin/payments — payment list (staff); POST (superuser) manual entry."""

    def get_permissions(self):
        return [IsOwnerAdmin()] if self.request.method == "POST" else [IsAdmin()]

    @extend_schema(summary="List payments for admin")
    def get(self, request):
        qs = Payment.objects.select_related("user", "reviewed_by")
        status_flag = (request.query_params.get("status") or "").strip()
        if status_flag:
            qs = qs.filter(status=status_flag)
        plan_flag = (request.query_params.get("plan") or "").strip()
        if plan_flag:
            qs = qs.filter(plan=plan_flag)
        email = (request.query_params.get("email") or "").strip()
        if email:
            qs = qs.filter(user__email__icontains=email)

        try:
            limit = min(max(int(request.query_params.get("limit", 50)), 1), 200)
        except (TypeError, ValueError):
            limit = 50

        from users.packs import get_topup_pack
        from users.plans import get_plan

        payments = qs.order_by("-created_at")[:limit]
        items = []
        for p in payments:
            is_topup = getattr(p, "payment_type", "subscription") == "topup"
            pack_obj = get_topup_pack(p.pack) if is_topup else None
            plan_obj = get_plan(p.plan) if not is_topup else None
            items.append(
                {
                    **PaymentSerializer(p).data,
                    "paymentType": getattr(p, "payment_type", "subscription"),
                    "plan": p.plan,
                    "pack": getattr(p, "pack", ""),
                    "planName": (
                        pack_obj["name"]
                        if is_topup and pack_obj
                        else (plan_obj["name"] if plan_obj else p.plan or p.pack)
                    ),
                    "packName": pack_obj["name"] if pack_obj else "",
                    "credits": (
                        pack_obj["credits"]
                        if is_topup and pack_obj
                        else (plan_obj["monthly_credits"] if plan_obj else None)
                    ),
                    "email": p.user.email if p.user else f"{p.payer_email} (deleted account)",
                    "firstName": p.user.first_name if p.user else "",
                    "lastName": p.user.last_name if p.user else "",
                    "currentPlan": p.user.plan if p.user else "",
                    "screenshotUrl": (
                        payment_screenshot_url(p, request) if p.screenshot else None
                    ),
                    "reviewedAt": p.reviewed_at,
                    "reviewedByEmail": p.reviewed_by.email if p.reviewed_by else None,
                }
            )
        return Response({"items": items})

    @extend_schema(summary="Record a manual payment", request=PaymentCreateSerializer)
    def post(self, request):
        serializer = PaymentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = serializer.save()
        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


class AdminPaymentReviewView(AdminAPIView):
    """POST /api/admin/payments/{id}/review — approve or reject a pending payment."""

    permission_classes = [IsOwnerAdmin]

    @extend_schema(summary="Approve or reject a pending manual payment", request=None)
    def post(self, request, payment_id):
        data = request.data or {}
        decision = str(data.get("decision") or "").strip().lower()
        reason = str(data.get("reason") or "").strip()
        try:
            payment = review_payment(payment_id, decision, request.user, reason)
        except ValidationError as exc:
            return Response({"message": "; ".join(exc.messages)}, status=status.HTTP_409_CONFLICT)
        return Response(
            {
                **PaymentSerializer(payment).data,
                "plan": payment.plan,
                "reviewedAt": payment.reviewed_at,
                "reviewedByEmail": request.user.email,
            }
        )


class AdminSettingsView(AdminAPIView):
    """GET /api/admin/settings — app settings + platform status (staff).

    PUT (superuser) persists editable settings via the AdminSetting key/value store.
    """

    def get_permissions(self):
        return [IsOwnerAdmin()] if self.request.method == "PUT" else [IsAdmin()]

    def _payload(self) -> dict:
        values = all_settings()
        return {
            "defaultFreeCredits": values.get("default_free_credits", "0"),
            "maintenanceBanner": values.get("maintenance_banner", ""),
            "easypaisaNumber": values.get("easypaisa_number", ""),
            "easypaisaName": values.get("easypaisa_name", ""),
            "platforms": {
                "youtube": {
                    "connectEnabled": bool(settings.GOOGLE_OAUTH_CLIENT_ID),
                    "publishEnabled": False,
                },
                "facebook": {
                    "connectEnabled": bool(settings.META_APP_ID),
                    "publishEnabled": settings.FACEBOOK_PUBLISH_ENABLED,
                },
                "instagram": {
                    "connectEnabled": bool(settings.INSTAGRAM_APP_ID or settings.META_APP_ID),
                    "publishEnabled": settings.INSTAGRAM_PUBLISH_ENABLED,
                },
                "tiktok": {
                    "connectEnabled": bool(settings.TIKTOK_CLIENT_KEY),
                    "publishEnabled": settings.TIKTOK_PUBLISH_ENABLED,
                },
                "snapchat": {
                    "connectEnabled": bool(settings.SNAPCHAT_CLIENT_ID),
                    "publishEnabled": False,
                },
            },
        }

    @extend_schema(summary="Read admin settings and platform status")
    def get(self, request):
        return Response(self._payload())

    @extend_schema(summary="Update admin settings", request=None)
    def put(self, request):
        data = request.data or {}
        editable = {
            "defaultFreeCredits": "default_free_credits",
            "maintenanceBanner": "maintenance_banner",
            "easypaisaNumber": "easypaisa_number",
            "easypaisaName": "easypaisa_name",
        }
        for camel, key in editable.items():
            if camel in data:
                AdminSetting.objects.update_or_create(key=key, defaults={"value": str(data[camel])})
        return Response(self._payload())
