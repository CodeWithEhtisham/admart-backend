from django.urls import path

from users.credits_views import (
    CreditsCostsView,
    CreditsHistoryView,
    CreditsPlanActivateView,
    CreditsPlansView,
    CreditsQuoteView,
)

# Mounted under /api/credits/ (balance lives at /api/credits with no trailing slash).
urlpatterns = [
    path("costs", CreditsCostsView.as_view(), name="credits_costs"),
    path("plans", CreditsPlansView.as_view(), name="credits_plans"),
    path("plan", CreditsPlanActivateView.as_view(), name="credits_plan_activate"),
    path("quote", CreditsQuoteView.as_view(), name="credits_quote"),
    path("history", CreditsHistoryView.as_view(), name="credits_history"),
]
