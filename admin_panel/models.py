import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Subscription(models.Model):
    """A customer's plan subscription.

    Payment integration is not connected yet, so subscriptions are created
    manually by admins (or seeded for demos) until a real gateway lands.
    """

    STATUS_CHOICES = [
        ("active", "Active"),
        ("trialing", "Trialing"),
        ("cancelled", "Cancelled"),
        ("expired", "Expired"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    PLAN_CHOICES = [
        ("free", "Free"),
        ("basic", "Basic"),
        ("plus", "Plus"),
        ("pro", "Pro"),
    ]
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES)
    current_period_end = models.DateTimeField(null=True, blank=True)
    auto_renew = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} — {self.plan} ({self.status})"


class Payment(models.Model):
    """A payment/charge record for a customer.

    Manual entry for now; swap in real gateway transactions (JazzCash/EasyPaisa)
    without changing this shape.
    """

    METHOD_CHOICES = [
        ("manual", "Manual"),
        ("jazzcash", "JazzCash"),
        ("easypaisa", "EasyPaisa"),
        ("card", "Card"),
        ("other", "Other"),
    ]
    STATUS_CHOICES = [
        ("paid", "Paid"),
        ("pending", "Pending"),
        ("failed", "Failed"),
        ("refunded", "Refunded"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payments",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=8, default="USD")
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default="manual")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="paid")
    provider_ref = models.CharField(max_length=128, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} — {self.amount} {self.currency} ({self.status})"


class CreditAdjustment(models.Model):
    """Audit log of admin credit grants/resets and plan-change credit effects."""

    REASON_CHOICES = [
        ("plan_change", "Plan change"),
        ("grant", "Manual grant"),
        ("reset", "Manual reset"),
        ("adjust", "Adjustment"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="credit_adjustments",
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    amount = models.DecimalField(max_digits=10, decimal_places=4)
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, default="grant")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.user_id} — {self.amount} ({self.reason})"


class PlanDefinition(models.Model):
    """Database-backed plan that the admin can edit. Replaces the hardcoded PLAN_TIERS."""

    plan_id = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=60)
    description = models.TextField(blank=True, default="")
    price_usd = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    price_pkr = models.PositiveIntegerField(default=0)
    monthly_credits = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    features = models.JSONField(default=list, blank=True)
    is_public = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order"]

    def __str__(self) -> str:
        return f"{self.name} ({self.plan_id})"


class AdminSetting(models.Model):
    """Key/value store for superadmin-controlled platform settings.

    Seeded with defaults on startup; editable via the admin panel Settings tab
    (superuser only). Read through ``get_setting()``.
    """

    key = models.CharField(max_length=64, unique=True)
    value = models.TextField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["key"]

    def __str__(self) -> str:
        return f"{self.key}={self.value}"
