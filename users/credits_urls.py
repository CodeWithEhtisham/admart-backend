from django.urls import path

from users.credits_views import (
    CreditsCostsView,
    CreditsHistoryView,
    CreditsMyPaymentsView,
    CreditsPaymentMethodsView,
    CreditsPaymentSubmitView,
    PaymentScreenshotView,
    CreditsPlansView,
    CreditsQuoteView,
    CreditsTopupsView,
)

# Mounted under /api/credits/ (balance lives at /api/credits with no trailing slash).
urlpatterns = [
    path("costs", CreditsCostsView.as_view(), name="credits_costs"),
    path("plans", CreditsPlansView.as_view(), name="credits_plans"),
    path("topups", CreditsTopupsView.as_view(), name="credits_topups"),
    path("quote", CreditsQuoteView.as_view(), name="credits_quote"),
    path("history", CreditsHistoryView.as_view(), name="credits_history"),
    path("payments/methods", CreditsPaymentMethodsView.as_view(), name="credits_payment_methods"),
    path("payments/submit", CreditsPaymentSubmitView.as_view(), name="credits_payment_submit"),
    path("payments/mine", CreditsMyPaymentsView.as_view(), name="credits_my_payments"),
    path(
        "payments/<uuid:payment_id>/screenshot",
        PaymentScreenshotView.as_view(),
        name="credits_payment_screenshot",
    ),
]
