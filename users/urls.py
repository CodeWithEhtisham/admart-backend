from django.urls import path

from users.views import (
    CustomTokenObtainPairView,
    DeleteAccountView,
    RefreshView,
    ForgotPasswordView,
    GoogleAuthView,
    LogoutView,
    MeView,
    OnboardingCompleteView,
    RegisterView,
    ResetPasswordView,
)

urlpatterns = [
    # Authentication
    path("register", RegisterView.as_view(), name="auth_register"),
    path("login", CustomTokenObtainPairView.as_view(), name="auth_login"),
    path("refresh", RefreshView.as_view(), name="auth_refresh"),
    path("logout", LogoutView.as_view(), name="auth_logout"),
    path("google", GoogleAuthView.as_view(), name="auth_google"),
    path("forgot-password", ForgotPasswordView.as_view(), name="auth_forgot_password"),
    path("reset-password", ResetPasswordView.as_view(), name="auth_reset_password"),
    path("me", MeView.as_view(), name="auth_me"),
    path("delete-account", DeleteAccountView.as_view(), name="auth_delete_account"),
    # Onboarding
    path("onboarding/complete", OnboardingCompleteView.as_view(), name="onboarding_complete"),
]
