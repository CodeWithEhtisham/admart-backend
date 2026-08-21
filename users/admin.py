from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from admin_panel.models import CreditAdjustment, Payment, Subscription
from users.models import User


class SubscriptionInline(admin.TabularInline):
    model = Subscription
    extra = 0
    readonly_fields = ("id", "created_at", "updated_at")
    fields = ("plan", "status", "auto_renew", "current_period_end", "created_at")


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ("id", "created_at", "updated_at")
    fields = ("amount", "currency", "method", "status", "provider_ref", "created_at")


class CreditAdjustmentInline(admin.TabularInline):
    model = CreditAdjustment
    fk_name = "user"
    extra = 0
    readonly_fields = ("id", "created_at")
    fields = ("amount", "reason", "performed_by", "notes", "created_at")


class UserAdmin(BaseUserAdmin):
    """Custom UserAdmin class to support our custom User model in Django Admin."""

    list_display = (
        "email",
        "first_name",
        "last_name",
        "plan",
        "credits_remaining",
        "credits_total",
        "is_staff",
        "is_superuser",
        "is_active",
        "last_active_at",
        "created_at",
    )
    list_filter = ("plan", "is_staff", "is_superuser", "is_active", "onboarding_completed")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal Info"), {"fields": ("first_name", "last_name", "avatar_url", "google_id")}),
        (
            _("Credits & Plan"),
            {
                "fields": (
                    "plan",
                    "credits_total",
                    "credits_used",
                    "credits_remaining",
                    "credits_reset_at",
                    "onboarding_completed",
                    "active_project",
                )
            },
        ),
        (
            _("Brand Kit"),
            {
                "fields": (
                    "brand_name",
                    "brand_industry",
                    "brand_color_hex",
                    "brand_logo_url",
                )
            },
        ),
        (_("Permissions"), {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        (_("Important dates"), {"fields": ("last_login", "created_at", "last_active_at")}),
    )
    readonly_fields = ("created_at", "updated_at", "last_active_at")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("-created_at",)
    inlines = [SubscriptionInline, PaymentInline, CreditAdjustmentInline]


admin.site.register(User, UserAdmin)
