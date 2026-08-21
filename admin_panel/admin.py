from django.contrib import admin

from admin_panel.models import AdminSetting, CreditAdjustment, Payment, PlanDefinition, Subscription


@admin.register(AdminSetting)
class AdminSettingAdmin(admin.ModelAdmin):
    list_display = ("key", "value", "updated_at")
    search_fields = ("key",)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user_email", "plan", "status", "auto_renew", "current_period_end", "created_at")
    list_filter = ("plan", "status", "auto_renew")
    search_fields = ("user__email",)
    readonly_fields = ("id", "created_at", "updated_at")
    date_hierarchy = "created_at"

    @admin.display(description="User")
    def user_email(self, obj):
        return obj.user.email


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("user_email", "amount", "currency", "method", "status", "provider_ref", "created_at")
    list_filter = ("status", "method", "currency")
    search_fields = ("user__email", "provider_ref")
    readonly_fields = ("id", "created_at", "updated_at")
    date_hierarchy = "created_at"

    @admin.display(description="User")
    def user_email(self, obj):
        return obj.user.email


@admin.register(CreditAdjustment)
class CreditAdjustmentAdmin(admin.ModelAdmin):
    list_display = ("user_email", "amount", "reason", "performed_by_email", "notes", "created_at")
    list_filter = ("reason",)
    search_fields = ("user__email", "performed_by__email", "notes")
    readonly_fields = ("id", "created_at")
    date_hierarchy = "created_at"

    @admin.display(description="User")
    def user_email(self, obj):
        return obj.user.email

    @admin.display(description="Performed by")
    def performed_by_email(self, obj):
        return obj.performed_by.email if obj.performed_by else "-"


@admin.register(PlanDefinition)
class PlanDefinitionAdmin(admin.ModelAdmin):
    list_display = ("plan_id", "name", "price_usd", "price_pkr", "monthly_credits", "is_public", "sort_order")
    list_filter = ("is_public",)
    search_fields = ("plan_id", "name")
    ordering = ("sort_order",)
    readonly_fields = ("id", "created_at", "updated_at")
