from django.urls import path

from admin_panel.views import (
    AdminPaymentListView,
    AdminPlanCreateView,
    AdminPlanDetailView,
    AdminPlansView,
    AdminRevenueView,
    AdminSettingsView,
    AdminStatsView,
    AdminUsageView,
    AdminUserCreditsView,
    AdminUserDetailView,
    AdminUserListView,
    AdminUserPlanView,
)

# Mounted under /api/admin/.
urlpatterns = [
    path("stats", AdminStatsView.as_view(), name="admin_stats"),
    path("usage", AdminUsageView.as_view(), name="admin_usage"),
    path("revenue", AdminRevenueView.as_view(), name="admin_revenue"),
    path("plans", AdminPlansView.as_view(), name="admin_plans"),
    path("plans/create", AdminPlanCreateView.as_view(), name="admin_plan_create"),
    path("plans/<str:plan_id>", AdminPlanDetailView.as_view(), name="admin_plan_detail"),
    path("settings", AdminSettingsView.as_view(), name="admin_settings"),
    path("users", AdminUserListView.as_view(), name="admin_users"),
    path("users/<uuid:user_id>", AdminUserDetailView.as_view(), name="admin_user_detail"),
    path("users/<uuid:user_id>/plan", AdminUserPlanView.as_view(), name="admin_user_plan"),
    path("users/<uuid:user_id>/credits", AdminUserCreditsView.as_view(), name="admin_user_credits"),
    path("payments", AdminPaymentListView.as_view(), name="admin_payments"),
]
