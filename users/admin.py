from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from users.models import User


class UserAdmin(BaseUserAdmin):
    """Custom UserAdmin class to support our custom User model in Django Admin."""

    list_display = ("email", "first_name", "last_name", "plan", "credits_remaining", "is_staff")
    list_filter = ("plan", "is_staff", "is_superuser", "is_active")
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
        (_("Important dates"), {"fields": ("last_login", "created_at")}),
    )
    readonly_fields = ("created_at", "updated_at")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("-created_at",)


admin.site.register(User, UserAdmin)
