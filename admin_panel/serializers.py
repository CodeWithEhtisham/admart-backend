from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import serializers

from admin_panel.models import CreditAdjustment, Payment, Subscription

User = get_user_model()

_ZERO = Decimal("0")


class SubscriptionSerializer(serializers.ModelSerializer):
    currentPeriodEnd = serializers.DateTimeField(source="current_period_end", read_only=True, allow_null=True)
    autoRenew = serializers.BooleanField(source="auto_renew", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Subscription
        fields = ["id", "plan", "status", "currentPeriodEnd", "autoRenew", "createdAt"]
        read_only_fields = fields


class PaymentSerializer(serializers.ModelSerializer):
    userId = serializers.CharField(source="user_id", read_only=True)
    providerRef = serializers.CharField(source="provider_ref", read_only=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Payment
        fields = [
            "id",
            "userId",
            "amount",
            "currency",
            "method",
            "status",
            "providerRef",
            "notes",
            "createdAt",
        ]
        read_only_fields = ["id", "createdAt"]


class PaymentCreateSerializer(serializers.ModelSerializer):
    userId = serializers.UUIDField(source="user_id", write_only=True, required=False, default=None)
    email = serializers.EmailField(write_only=True, required=False)
    providerRef = serializers.CharField(source="provider_ref", required=False, allow_blank=True)

    class Meta:
        model = Payment
        fields = ["userId", "email", "amount", "currency", "method", "status", "providerRef", "notes"]
        extra_kwargs = {
            "amount": {"required": True},
            "currency": {"default": "USD"},
            "method": {"default": "manual"},
            "status": {"default": "paid"},
        }

    def validate(self, attrs):
        user_id = attrs.pop("user_id", None)
        email = attrs.pop("email", None)
        user = None
        if user_id:
            user = User.objects.filter(pk=user_id).first()
        elif email:
            user = User.objects.filter(email__iexact=email).first()
        if user is None:
            raise serializers.ValidationError({"userId": "No user found for the given id/email."})
        attrs["user"] = user
        return attrs


class CreditAdjustmentSerializer(serializers.ModelSerializer):
    performedByEmail = serializers.CharField(
        source="performed_by.email", read_only=True, default=None
    )
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = CreditAdjustment
        fields = ["id", "amount", "reason", "notes", "performedByEmail", "createdAt"]
        read_only_fields = fields


class AdminUserSerializer(serializers.ModelSerializer):
    """Row-level customer summary for the admin customers table."""

    firstName = serializers.CharField(source="first_name", read_only=True)
    lastName = serializers.CharField(source="last_name", read_only=True)
    avatarUrl = serializers.URLField(source="avatar_url", read_only=True, allow_null=True)
    isActive = serializers.BooleanField(source="is_active", read_only=True)
    isStaff = serializers.BooleanField(source="is_staff", read_only=True)
    isSuperuser = serializers.BooleanField(source="is_superuser", read_only=True)
    onboardingCompleted = serializers.BooleanField(source="onboarding_completed", read_only=True)
    creditsTotal = serializers.DecimalField(
        source="credits_total", max_digits=10, decimal_places=4, read_only=True, coerce_to_string=False
    )
    creditsUsed = serializers.DecimalField(
        source="credits_used", max_digits=10, decimal_places=4, read_only=True, coerce_to_string=False
    )
    creditsRemaining = serializers.DecimalField(
        source="credits_remaining", max_digits=10, decimal_places=4, read_only=True, coerce_to_string=False
    )
    creditsResetAt = serializers.DateTimeField(source="credits_reset_at", read_only=True, allow_null=True)
    createdAt = serializers.DateTimeField(source="created_at", read_only=True)
    lastActiveAt = serializers.DateTimeField(source="last_active_at", read_only=True, allow_null=True)
    jobCount = serializers.SerializerMethodField()
    projectCount = serializers.SerializerMethodField()
    socialCount = serializers.SerializerMethodField()
    paymentsTotal = serializers.SerializerMethodField()
    subscription = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "firstName",
            "lastName",
            "avatarUrl",
            "plan",
            "isActive",
            "isStaff",
            "isSuperuser",
            "onboardingCompleted",
            "creditsTotal",
            "creditsUsed",
            "creditsRemaining",
            "creditsResetAt",
            "createdAt",
            "lastActiveAt",
            "jobCount",
            "projectCount",
            "socialCount",
            "paymentsTotal",
            "subscription",
        ]

    def get_projectCount(self, obj) -> int:
        return obj.projects.count()

    def get_jobCount(self, obj) -> int:
        return obj.image_jobs.count() + obj.video_jobs.count()

    def get_socialCount(self, obj) -> int:
        return sum(p.social_accounts.count() for p in obj.projects.all())

    def get_paymentsTotal(self, obj) -> Decimal:
        return sum(
            (p.amount for p in obj.payments.all() if p.status == "paid"),
            _ZERO,
        )

    def get_subscription(self, obj):
        sub = obj.subscriptions.first()
        if sub is None:
            return None
        return {
            "plan": sub.plan,
            "status": sub.status,
            "currentPeriodEnd": sub.current_period_end,
            "autoRenew": sub.auto_renew,
        }


class AdminUserDetailSerializer(AdminUserSerializer):
    """Full customer profile for the admin detail drawer."""

    payments = serializers.SerializerMethodField()
    subscriptions = serializers.SerializerMethodField()
    creditAdjustments = serializers.SerializerMethodField()
    projects = serializers.SerializerMethodField()
    jobs = serializers.SerializerMethodField()

    class Meta(AdminUserSerializer.Meta):
        fields = AdminUserSerializer.Meta.fields + [
            "payments",
            "subscriptions",
            "creditAdjustments",
            "projects",
            "jobs",
        ]

    def get_payments(self, obj) -> list[dict]:
        return PaymentSerializer(obj.payments.all()[:20], many=True).data

    def get_subscriptions(self, obj) -> list[dict]:
        return SubscriptionSerializer(obj.subscriptions.all()[:5], many=True).data

    def get_creditAdjustments(self, obj) -> list[dict]:
        return CreditAdjustmentSerializer(obj.credit_adjustments.all()[:20], many=True).data

    def get_projects(self, obj) -> list[dict]:
        return [
            {"id": str(p.id), "name": p.name, "createdAt": p.created_at}
            for p in obj.projects.all()[:20]
        ]

    def get_jobs(self, obj) -> list[dict]:
        items = []
        for job in list(obj.image_jobs.all()[:10]) + list(obj.video_jobs.all()[:10]):
            amount = job.credits_used if job.credits_used is not None else job.credits_reserved
            items.append(
                {
                    "kind": "image" if hasattr(job, "images") else "video",
                    "capability": job.capability,
                    "model": job.model,
                    "status": job.status,
                    "credits": float(amount) if amount is not None else 0,
                    "createdAt": job.created_at,
                }
            )
        items.sort(key=lambda j: j["createdAt"], reverse=True)
        return items[:20]
