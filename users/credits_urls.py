from django.urls import path

from users.credits_views import CreditsCostsView, CreditsHistoryView

# Mounted under /api/credits/ (balance lives at /api/credits with no trailing slash).
urlpatterns = [
    path("costs", CreditsCostsView.as_view(), name="credits_costs"),
    path("history", CreditsHistoryView.as_view(), name="credits_history"),
]
