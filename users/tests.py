from typing import Any
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()


class APITestCase(APITestCase):  # noqa: F811 — shadow DRF's so every test here starts throttle-free
    """Clears the cache (where DRF throttle history lives) before each test, so the
    5/minute auth limit doesn't leak between tests."""

    def run(self, result=None):
        from django.core.cache import cache

        cache.clear()
        return super().run(result)


class UserAuthTests(APITestCase):
    """Test suite for User Authentication and registration endpoints."""

    def setUp(self) -> None:
        """Set up test user data."""
        self.register_url = reverse("auth_register")
        self.login_url = reverse("auth_login")
        self.me_url = reverse("auth_me")
        self.forgot_password_url = reverse("auth_forgot_password")
        self.reset_password_url = reverse("auth_reset_password")
        self.google_url = reverse("auth_google")
        self.logout_url = reverse("auth_logout")

        self.user_data = {
            "email": "testuser@example.com",
            "password": "Password123!",
            "firstName": "John",
            "lastName": "Doe",
        }
        # Pre-create a user for login and password reset tests
        self.user = User.objects.create_user(
            email="existinguser@example.com",
            password="ExistingPassword123!",
            first_name="Jane",
            last_name="Smith",
        )

    def test_user_registration_success(self) -> None:
        """Test successful registration returns user profile and JWT tokens."""
        response = self.client.post(self.register_url, self.user_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("accessToken", response.data)
        self.assertIn("refreshToken", response.data)
        self.assertIn("user", response.data)
        self.assertEqual(response.data["user"]["email"], self.user_data["email"])
        self.assertEqual(response.data["user"]["firstName"], self.user_data["firstName"])
        self.assertEqual(response.data["user"]["plan"], "free")
        self.assertEqual(response.data["user"]["creditsRemaining"], 0)

    def test_user_registration_allows_blank_names(self) -> None:
        """Registration does not require first/last name fields."""
        data = {
            "email": "blanknames@example.com",
            "password": "Password123!",
        }
        response = self.client.post(self.register_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["user"]["firstName"], "")
        self.assertEqual(response.data["user"]["lastName"], "")

    def test_user_registration_duplicate_email(self) -> None:
        """Test registration fails with a duplicate email."""
        duplicate_data = self.user_data.copy()
        duplicate_data["email"] = "existinguser@example.com"
        response = self.client.post(self.register_url, duplicate_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)

    def test_user_login_success(self) -> None:
        """Test successful login with email/password returns tokens."""
        login_data = {"email": "existinguser@example.com", "password": "ExistingPassword123!"}
        response = self.client.post(self.login_url, login_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("accessToken", response.data)
        self.assertIn("refreshToken", response.data)
        self.assertEqual(response.data["user"]["email"], "existinguser@example.com")

    def test_user_login_invalid_credentials(self) -> None:
        """Test login fails with incorrect password."""
        login_data = {"email": "existinguser@example.com", "password": "WrongPassword"}
        response = self.client.post(self.login_url, login_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_user_login_unknown_email_is_404(self) -> None:
        """Unknown email must not create a user; 404 no_account (not 401)."""
        response = self.client.post(
            self.login_url,
            {"email": "nobody@example.com", "password": "Password123!"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "no_account")
        self.assertEqual(
            response.data["message"],
            "There is no Admart account for this email. Please sign up first, then sign in.",
        )
        self.assertFalse(User.objects.filter(email="nobody@example.com").exists())

    def test_get_me_unauthorized(self) -> None:
        """Test accessing /me without authorization fails."""
        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_me_success(self) -> None:
        """Test accessing /me with authorization header returns user details."""
        self.client.force_authenticate(user=self.user)
        response = self.client.get(self.me_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], self.user.email)
        self.assertEqual(response.data["firstName"], "Jane")

    def test_update_me_success(self) -> None:
        """Test updating user profile fields via PUT."""
        self.client.force_authenticate(user=self.user)
        update_data = {
            "firstName": "JaneUpdated",
            "lastName": "SmithUpdated",
            "onboardingCompleted": True,
        }
        response = self.client.put(self.me_url, update_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["firstName"], "JaneUpdated")
        self.assertEqual(response.data["onboardingCompleted"], True)

    def test_forgot_password_sends_link(self) -> None:
        """Test forgot password request responds with success regardless of user existence."""
        # Registered email
        response = self.client.post(
            self.forgot_password_url, {"email": "existinguser@example.com"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Unregistered email (should return same success response for security)
        response = self.client.post(
            self.forgot_password_url, {"email": "nonexistent@example.com"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_reset_password_success(self) -> None:
        """Test resetting password with a valid signed token."""
        from users.views import password_reset_token

        token = password_reset_token(self.user)
        reset_data = {"token": token, "newPassword": "NewPassword123!"}
        response = self.client.post(self.reset_password_url, reset_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Verify password changed by trying to log in
        login_data = {"email": "existinguser@example.com", "password": "NewPassword123!"}
        login_response = self.client.post(self.login_url, login_data, format="json")
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)

    def test_reset_password_invalid_token(self) -> None:
        """Test resetting password with an invalid token fails."""
        reset_data = {"token": "invalid-token", "newPassword": "NewPassword123!"}
        response = self.client.post(self.reset_password_url, reset_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("non_field_errors", response.data)

    def test_logout_success(self) -> None:
        """Test logout returns standard success message."""
        response = self.client.post(self.logout_url, {"refreshToken": "mock-token"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("message", response.data)


class OnboardingTests(APITestCase):
    """Test suite for the onboarding endpoint (now creates the first project)."""

    def setUp(self) -> None:
        """Set up test data."""
        self.onboarding_url = reverse("onboarding_complete")
        self.me_url = reverse("auth_me")

        self.user = User.objects.create_user(
            email="onboard@example.com",
            password="Password123!",
            first_name="Test",
            last_name="User",
        )
        self.client.force_authenticate(user=self.user)

    def test_onboarding_creates_project_with_social_accounts(self) -> None:
        """Onboarding creates a project that owns the brand kit and platforms."""
        from projects.models import Project, SocialAccount

        data = {
            "projectName": "My Brand Project",
            "connectedPlatforms": ["tiktok", "youtube"],
            "brandName": "My Brand",
            "industry": "SaaS",
            "brandColorHex": "#7c3aed",
        }
        response = self.client.post(self.onboarding_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["onboardingCompleted"])
        self.assertEqual(response.data["projectCount"], 1)
        self.assertIsNotNone(response.data["activeProjectId"])

        project = Project.objects.get(owner=self.user)
        self.assertEqual(project.name, "My Brand Project")
        self.assertEqual(project.brand_name, "My Brand")
        self.assertEqual(project.brand_color_hex, "#7c3aed")
        self.user.refresh_from_db()
        self.assertEqual(self.user.active_project_id, project.id)

        accounts = SocialAccount.objects.filter(project=project)
        self.assertEqual(accounts.count(), 2)
        self.assertEqual(set(accounts.values_list("platform", flat=True)), {"tiktok", "youtube"})

    def test_onboarding_defaults_project_name(self) -> None:
        """With no project/brand name, a default project is still created."""
        from projects.models import Project

        response = self.client.post(self.onboarding_url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["onboardingCompleted"])
        self.assertEqual(Project.objects.filter(owner=self.user).count(), 1)
        self.assertEqual(Project.objects.get(owner=self.user).name, "My Project")

    def test_patch_me_with_brand_fields(self) -> None:
        """Test PATCH /api/auth/me with snake_case brand fields."""
        data = {
            "onboardingCompleted": True,
            "brand_name": "Patched Brand",
            "brand_industry": "E-commerce",
            "brand_color_hex": "#ef4444",
        }
        response = self.client.patch(self.me_url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["onboardingCompleted"])
        self.assertEqual(response.data["brandKit"]["brandName"], "Patched Brand")
        self.assertEqual(response.data["brandKit"]["industry"], "E-commerce")
        self.assertEqual(response.data["brandKit"]["brandColorHex"], "#ef4444")


@override_settings(FAL_KEY="")
@override_settings(PRIVATE_MEDIA_ROOT=__import__("tempfile").mkdtemp(prefix="admart-test-private-"))
class CreditsApiTests(APITestCase):
    """Credits balance / costs / history endpoints."""

    def setUp(self) -> None:
        from content import pricing

        pricing._CACHE["prices"] = None
        pricing._CACHE["expires_at"] = 0
        self.user = User.objects.create_user(
            email="credits@example.com",
            password="Password123!",
            credits_total=50,
            credits_remaining=40,
            credits_used=10,
        )
        self.client.force_authenticate(user=self.user)

    def test_balance(self) -> None:
        response = self.client.get("/api/credits")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["creditsRemaining"], 40)
        self.assertEqual(response.data["creditsTotal"], 50)
        self.assertEqual(response.data["creditsUsed"], 10)
        self.assertTrue(response.data["canGenerate"])
        self.assertIn("planDetails", response.data)

    def test_costs(self) -> None:
        response = self.client.get("/api/credits/costs")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("byCapability", response.data)
        self.assertEqual(response.data["currency"], "Admart credits")
        self.assertEqual(response.data["byCapability"]["textToImage"], "0.0543")
        self.assertEqual(response.data["byCapability"]["multiEdit"], "0.3065")
        self.assertEqual(response.data["pricingFormula"][0]["markupMultiplier"], "dynamic")
        self.assertTrue(any(i["capability"] == "edit" for i in response.data["items"]))

    def test_quote(self) -> None:
        response = self.client.post(
            "/api/credits/quote",
            {
                "kind": "image",
                "capability": "textToImage",
                "model": "fal-ai/flux/dev",
                "settings": {"numImages": 2},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["credits"], "0.1071")
        self.assertEqual(response.data["falCost"], "0.05")
        self.assertEqual(response.data["markupMultiplier"], "2.1429")
        self.assertEqual(response.data["creditsRemaining"], "40")
        self.assertEqual(response.data["creditsAfter"], "39.8929")
        self.assertTrue(response.data["canAfford"])

    def test_history(self) -> None:
        from content.models import ImageJob
        from projects.models import Project

        project = Project.objects.create(owner=self.user, name="P")
        ImageJob.objects.create(
            project=project,
            user=self.user,
            capability="textToImage",
            model="fal-ai/flux/dev",
            status="succeeded",
            prompt="a cat",
            credits_reserved=1,
            credits_used=1,
        )
        response = self.client.get("/api/credits/history")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["items"]), 1)
        self.assertEqual(response.data["items"][0]["credits"], 1.0)
        self.assertEqual(response.data["items"][0]["capability"], "textToImage")

    def test_plans(self) -> None:
        response = self.client.get("/api/credits/plans")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in response.data["items"]]
        self.assertEqual(ids, ["basic", "plus", "pro"])
        self.assertEqual(response.data["items"][0]["monthlyCredits"], "8")
        self.assertTrue(response.data["paymentConnected"])

    def test_payment_methods_requires_auth(self) -> None:
        self.client.force_authenticate(user=None)
        self.assertEqual(
            self.client.get("/api/credits/payments/methods").status_code,
            status.HTTP_401_UNAUTHORIZED,
        )

    def test_payment_methods_returns_settings(self) -> None:
        from admin_panel.models import AdminSetting

        AdminSetting.objects.update_or_create(
            key="easypaisa_number", defaults={"value": "0300-1234567"}
        )
        response = self.client.get("/api/credits/payments/methods")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["methods"][0]["id"], "easypaisa")
        self.assertEqual(response.data["methods"][0]["accountNumber"], "0300-1234567")

    def _screenshot(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return SimpleUploadedFile(
            "proof.png", b"\x89PNG\r\n\x1a\nfake-png-body", content_type="image/png"
        )

    def test_submit_payment_creates_pending(self) -> None:
        response = self.client.post(
            "/api/credits/payments/submit",
            {"plan": "plus", "screenshot": self._screenshot(), "transactionId": "EP-1"},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "pending")
        self.assertEqual(response.data["plan"], "plus")
        self.assertEqual(response.data["currency"], "PKR")
        self.assertEqual(response.data["amount"], 7999)

        from admin_panel.models import Payment

        payment = Payment.objects.get(user=self.user)
        self.assertEqual(payment.status, "pending")
        self.assertTrue(payment.screenshot)

    def test_submit_payment_requires_transaction_id(self) -> None:
        response = self.client.post(
            reverse("credits_payment_submit"),
            {"plan": "plus", "screenshot": self._screenshot()},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("transactionId", response.data)

    def test_submit_payment_rejects_reused_transaction_id(self) -> None:
        from admin_panel.models import Payment

        other = User.objects.create_user(email="other@example.com", password="Password123!")
        Payment.objects.create(user=other, amount=1, status="paid", provider_ref="EP-DUP")
        response = self.client.post(
            reverse("credits_payment_submit"),
            {"plan": "plus", "screenshot": self._screenshot(), "transactionId": "ep-dup"},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("transactionId", response.data)

    def test_submit_payment_rejects_free_plan(self) -> None:
        response = self.client.post(
            "/api/credits/payments/submit",
            {"plan": "free", "screenshot": self._screenshot()},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submit_payment_requires_screenshot(self) -> None:
        response = self.client.post(
            "/api/credits/payments/submit",
            {"plan": "basic"},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submit_payment_rejects_bad_content_type(self) -> None:
        from django.core.files.uploadedfile import SimpleUploadedFile

        bad = SimpleUploadedFile("proof.txt", b"data", content_type="text/plain")
        response = self.client.post(
            "/api/credits/payments/submit",
            {"plan": "basic", "screenshot": bad},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_submit_payment_blocked_while_pending(self) -> None:
        first = self.client.post(
            "/api/credits/payments/submit",
            {"plan": "basic", "screenshot": self._screenshot(), "transactionId": "EP-2"},
            format="multipart",
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        second = self.client.post(
            "/api/credits/payments/submit",
            {"plan": "plus", "screenshot": self._screenshot(), "transactionId": "EP-3"},
            format="multipart",
        )
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("under review", str(second.data))

    def test_my_payments_lists_own(self) -> None:
        from admin_panel.models import Payment

        Payment.objects.create(
            user=self.user, plan="basic", amount=2499, currency="PKR",
            method="easypaisa", status="pending",
        )
        response = self.client.get("/api/credits/payments/mine")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["items"]), 1)
        self.assertEqual(response.data["items"][0]["status"], "pending")
        self.assertEqual(response.data["items"][0]["planName"], "Basic")

    def test_topups_list(self) -> None:
        response = self.client.get("/api/credits/topups")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["items"]), 3)
        ids = [item["id"] for item in response.data["items"]]
        self.assertEqual(ids, ["pack_small", "pack_medium", "pack_large"])
        self.assertEqual(response.data["items"][0]["credits"], "5")

    def test_submit_topup_payment_creates_pending(self) -> None:
        response = self.client.post(
            "/api/credits/payments/submit",
            {"pack": "pack_medium", "screenshot": self._screenshot(), "transactionId": "EP-4"},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "pending")
        self.assertEqual(response.data["paymentType"], "topup")
        self.assertEqual(response.data["pack"], "pack_medium")
        self.assertEqual(response.data["planName"], "Creator Booster")
        self.assertEqual(response.data["amount"], 4199)

        from admin_panel.models import Payment

        payment = Payment.objects.get(user=self.user)
        self.assertEqual(payment.status, "pending")
        self.assertEqual(payment.payment_type, "topup")
        self.assertEqual(payment.pack, "pack_medium")

    def test_submit_topup_payment_rejects_invalid_pack(self) -> None:
        response = self.client.post(
            "/api/credits/payments/submit",
            {"pack": "fake_pack", "screenshot": self._screenshot()},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unauthenticated(self) -> None:
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get("/api/credits").status_code, status.HTTP_401_UNAUTHORIZED)


GOOGLE_CLAIMS = {
    "sub": "google-sub-123",
    "email": "ada@example.com",
    "email_verified": True,
    "given_name": "Ada",
    "family_name": "Lovelace",
    "iss": "https://accounts.google.com",
    "aud": "test-google-client.apps.googleusercontent.com",
}

GOOGLE_SETTINGS = dict(
    GOOGLE_OAUTH_CLIENT_ID="test-google-client.apps.googleusercontent.com",
    GOOGLE_OAUTH_CLIENT_SECRET="test-google-secret",
    FRONTEND_URL="http://localhost:5173",
    CORS_ALLOWED_ORIGINS=["http://localhost:5173", "http://127.0.0.1:5173"],
)


@override_settings(**GOOGLE_SETTINGS)
class GoogleAuthTests(APITestCase):
    """POST /api/auth/google — real code exchange (Google mocked)."""

    def setUp(self) -> None:
        self.url = reverse("auth_google")
        self.body = {
            "code": "4/0AX4XfWh-test-code",
            "redirectUri": "http://localhost:5173/auth-callback",
            "redirect_uri": "http://localhost:5173/auth-callback",
        }

    def test_google_login_missing_user_is_404(self) -> None:
        with patch("users.views.exchange_code", return_value="fake-id-token"):
            with patch("users.views.verify_id_token", return_value=GOOGLE_CLAIMS):
                response = self.client.post(
                    self.url,
                    {**self.body, "intent": "login", "createAccount": False},
                    format="json",
                )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "no_account")
        self.assertEqual(
            response.data["message"],
            "There is no Admart account for this email. Please sign up first, then sign in.",
        )
        self.assertFalse(User.objects.filter(email="ada@example.com").exists())

    def test_google_missing_intent_does_not_create(self) -> None:
        with patch("users.views.exchange_code", return_value="fake-id-token"):
            with patch("users.views.verify_id_token", return_value=GOOGLE_CLAIMS):
                response = self.client.post(self.url, self.body, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data["code"], "no_account")
        self.assertFalse(User.objects.filter(email="ada@example.com").exists())

    def test_google_register_creates_user_and_returns_jwt(self) -> None:
        with patch("users.views.exchange_code", return_value="fake-id-token") as mock_ex:
            with patch("users.views.verify_id_token", return_value=GOOGLE_CLAIMS) as mock_verify:
                response = self.client.post(
                    self.url,
                    {**self.body, "intent": "register", "createAccount": True},
                    format="json",
                )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("accessToken", response.data)
        self.assertIn("refreshToken", response.data)
        self.assertEqual(response.data["user"]["email"], "ada@example.com")
        self.assertEqual(response.data["user"]["firstName"], "Ada")
        self.assertEqual(response.data["user"]["lastName"], "Lovelace")
        self.assertEqual(response.data["user"]["googleId"], "google-sub-123")
        self.assertTrue(response.data["user"]["emailVerified"])
        self.assertEqual(response.data["user"]["creditsRemaining"], 0)
        mock_ex.assert_called_once_with(
            "4/0AX4XfWh-test-code", "http://localhost:5173/auth-callback"
        )
        mock_verify.assert_called_once_with("fake-id-token")
        user = User.objects.get(email="ada@example.com")
        self.assertTrue(user.email_verified)
        self.assertFalse(user.has_usable_password())

    def test_google_login_after_register_reuses_user(self) -> None:
        with patch("users.views.exchange_code", return_value="fake-id-token"):
            with patch("users.views.verify_id_token", return_value=GOOGLE_CLAIMS):
                signup = self.client.post(
                    self.url,
                    {**self.body, "intent": "register", "createAccount": True},
                    format="json",
                )
                signin = self.client.post(
                    self.url,
                    {**self.body, "intent": "login", "createAccount": False},
                    format="json",
                )
        self.assertEqual(signup.status_code, status.HTTP_200_OK)
        self.assertEqual(signin.status_code, status.HTTP_200_OK)
        self.assertEqual(User.objects.filter(email="ada@example.com").count(), 1)

    def test_google_links_existing_email(self) -> None:
        existing = User.objects.create_user(
            email="ada@example.com",
            password="Password123!",
            first_name="Ada",
            last_name="",
            email_verified=False,
        )
        with patch("users.views.exchange_code", return_value="fake-id-token"):
            with patch("users.views.verify_id_token", return_value=GOOGLE_CLAIMS):
                response = self.client.post(self.url, self.body, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(User.objects.filter(email="ada@example.com").count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.google_id, "google-sub-123")
        self.assertTrue(existing.email_verified)
        self.assertEqual(existing.last_name, "Lovelace")

    def test_google_rejects_unverified_email(self) -> None:
        from users.google import GoogleAuthError

        with patch("users.views.exchange_code", return_value="fake-id-token"):
            with patch(
                "users.views.verify_id_token",
                side_effect=GoogleAuthError("Google email is not verified."),
            ):
                response = self.client.post(self.url, self.body, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["message"], "Google email is not verified.")
        self.assertFalse(User.objects.filter(email="ada@example.com").exists())

    def test_google_failed_exchange_is_400_not_401(self) -> None:
        from users.google import GoogleAuthError

        with patch(
            "users.views.exchange_code",
            side_effect=GoogleAuthError("Google sign-in failed."),
        ):
            response = self.client.post(self.url, self.body, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["message"], "Google sign-in failed.")

    def test_google_missing_code_is_400(self) -> None:
        response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["message"], "Missing authorization code.")

    def test_google_rejects_unknown_redirect_uri(self) -> None:
        from users.google import exchange_code, GoogleAuthError

        with self.assertRaises(GoogleAuthError):
            exchange_code("some-code", "https://evil.example/callback")

    def test_google_id_token_path_skips_code_exchange(self) -> None:
        with patch("users.views.exchange_code") as mock_ex:
            with patch("users.views.verify_id_token", return_value=GOOGLE_CLAIMS):
                response = self.client.post(
                    self.url,
                    {"idToken": "mobile-id-token", "intent": "register", "createAccount": True},
                    format="json",
                )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_ex.assert_not_called()
        self.assertEqual(response.data["user"]["email"], "ada@example.com")



class PublicPlansFromDatabaseTests(APITestCase):
    def setUp(self) -> None:
        from admin_panel.models import PlanDefinition

        # Plans are seeded by migration; the admin hides everything except Plus.
        PlanDefinition.objects.exclude(plan_id="plus").update(is_public=False)
        PlanDefinition.objects.filter(plan_id="plus").update(is_public=True)
        self.user = User.objects.create_user(email="dbplans@example.com", password="Password123!")
        self.client.force_authenticate(user=self.user)

    def test_plans_endpoint_follows_database(self) -> None:
        response = self.client.get("/api/credits/plans")
        self.assertEqual([p["id"] for p in response.data["items"]], ["plus"])

    def test_hidden_plan_cannot_be_purchased(self) -> None:
        from django.core.files.uploadedfile import SimpleUploadedFile

        shot = SimpleUploadedFile("proof.png", b"\x89PNG\r\n", content_type="image/png")
        response = self.client.post(
            "/api/credits/payments/submit", {"plan": "basic", "screenshot": shot}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("plan", response.data)


class ForgedTokenTests(APITestCase):
    """#1: a token signed by someone else's key must never authenticate anyone."""

    def test_self_signed_rs256_token_for_superuser_is_rejected(self) -> None:
        import jwt
        from cryptography.hazmat.primitives.asymmetric import rsa

        User.objects.create_superuser(email="boss@example.com", password="Password123!")
        attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        forged = jwt.encode(
            {"iss": "https://attacker.example", "sub": "x", "email": "boss@example.com"},
            attacker_key,
            algorithm="RS256",
        )
        # Simulate the attacker serving their own JWKS at the issuer URL.
        signing_key = MagicMock(key=attacker_key.public_key())
        with patch("jwt.PyJWKClient.get_signing_key_from_jwt", return_value=signing_key):
            response = self.client.get("/api/auth/me", HTTP_AUTHORIZATION=f"Bearer {forged}")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class ProductionSettingsTests(APITestCase):
    """#4: production must not boot without a real SECRET_KEY, and DEBUG is off by default."""

    FERNET_KEY = "Y2ktb25seS1kdW1teS1rZXktMzItYnl0ZXMtbG9uZyE="

    def _load_settings(self, expr: str = "s.DEBUG, s.SECRET_KEY", **env) -> "subprocess.CompletedProcess":
        import os
        import subprocess
        import sys

        clean = {k: v for k, v in os.environ.items() if k not in ("DEBUG", "SECRET_KEY")}
        clean.update(env)
        code = f"import config.settings as s; print({expr})"
        # dotenv must not refill the vars from a local .env, so point it at an empty dir.
        return subprocess.run(
            [sys.executable, "-c", f"import dotenv; dotenv.load_dotenv = lambda *a, **k: None; {code}"],
            capture_output=True, text=True, env=clean,
        )

    def test_missing_secret_key_refuses_to_start(self) -> None:
        result = self._load_settings()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SECRET_KEY must be set", result.stderr)

    def test_production_cookies_and_proxy_are_https_only(self) -> None:
        result = self._load_settings(
            "s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE, s.SECURE_PROXY_SSL_HEADER[0], s.SECURE_HSTS_SECONDS > 0",
            SECRET_KEY="prod-secret",
            SOCIAL_TOKEN_ENCRYPTION_KEY=self.FERNET_KEY,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ["True", "True", "HTTP_X_FORWARDED_PROTO", "True"])

    def test_secret_key_from_env_and_debug_off_by_default(self) -> None:
        result = self._load_settings(SECRET_KEY="prod-secret", SOCIAL_TOKEN_ENCRYPTION_KEY=self.FERNET_KEY)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ["False", "prod-secret"])


PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png-body"


class UploadedFileSafetyTests(APITestCase):
    """A: uploads keep neither the client's filename nor a fake type; B: payment proofs are private."""

    def setUp(self) -> None:
        import tempfile
        from pathlib import Path

        self.tmp = Path(tempfile.mkdtemp())
        self.override = override_settings(MEDIA_ROOT=str(self.tmp / "media"), PRIVATE_MEDIA_ROOT=self.tmp / "private")
        self.override.enable()
        self.user = User.objects.create_user(email="payer@example.com", password="Password123!")
        self.client.force_authenticate(user=self.user)

    def tearDown(self) -> None:
        import shutil

        self.override.disable()
        shutil.rmtree(self.tmp)

    def _submit(self, name: str, data: bytes, txn: str):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return self.client.post(
            "/api/credits/payments/submit",
            {"plan": "plus", "transactionId": txn, "screenshot": SimpleUploadedFile(name, data, content_type="image/png")},
            format="multipart",
        )

    def test_html_disguised_as_png_is_rejected(self) -> None:
        response = self._submit("evil.html", b"<script>alert(document.cookie)</script>", "EP-XSS")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("screenshot", response.data)

    def test_proof_is_private_with_server_name_and_signed_link(self) -> None:
        from admin_panel.models import Payment

        response = self._submit("evil.html", PNG_BYTES, "EP-OK")  # real PNG, hostile name
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payment = Payment.objects.get(pk=response.data["id"])
        stored = self.tmp / "private" / payment.screenshot.name
        self.assertTrue(stored.is_file())
        self.assertTrue(payment.screenshot.name.endswith(".png"))
        self.assertNotIn("evil", payment.screenshot.name)
        self.assertFalse(any((self.tmp / "media").rglob("*")))  # nothing in public media

        link = response.data["screenshotUrl"]
        self.client.force_authenticate(user=None)
        self.assertEqual(b"".join(self.client.get(link).streaming_content), PNG_BYTES)
        unsigned = link.split("?")[0]
        self.assertEqual(self.client.get(unsigned).status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(self.client.get(unsigned + "?sig=forged").status_code, status.HTTP_404_NOT_FOUND)


@override_settings(FRONTEND_URL="https://app.example", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordResetSafetyTests(APITestCase):
    """C: reset links are emailed (never logged), point at the real frontend, and work once."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(email="forgetful@example.com", password="OldPassword123!")

    def _request_link(self) -> str:
        import re

        from django.core import mail

        with patch("users.views.logger") as mock_logger:
            response = self.client.post(reverse("auth_forgot_password"), {"email": "forgetful@example.com"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)
        link = re.search(r"https://app\.example/auth/reset-password\?token=\S+", mail.outbox[0].body).group(0)
        token = link.split("token=")[1]
        logged = " ".join(str(c) for c in mock_logger.mock_calls)
        self.assertNotIn(token, logged)
        return token

    def test_link_is_one_time(self) -> None:
        token = self._request_link()
        url = reverse("auth_reset_password")
        first = self.client.post(url, {"token": token, "newPassword": "NewPassword123!"}, format="json")
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        again = self.client.post(url, {"token": token, "newPassword": "Hijack123!pass"}, format="json")
        self.assertEqual(again.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewPassword123!"))

    def test_unknown_email_sends_nothing_but_same_answer(self) -> None:
        from django.core import mail

        response = self.client.post(reverse("auth_forgot_password"), {"email": "nobody@example.com"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 0)


class RefreshTokenRotationTests(APITestCase):
    """F: refresh tokens rotate and are revoked after use or logout."""

    def setUp(self) -> None:
        User.objects.create_user(email="rotate@example.com", password="Password123!")
        login = self.client.post(reverse("auth_login"), {"email": "rotate@example.com", "password": "Password123!"}, format="json")
        self.refresh = login.data["refreshToken"]

    def test_old_refresh_token_stops_working_after_rotation(self) -> None:
        url = reverse("auth_refresh")
        first = self.client.post(url, {"refresh": self.refresh}, format="json")
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertIn("refresh", first.data)
        self.assertNotEqual(first.data["refresh"], self.refresh)
        replay = self.client.post(url, {"refresh": self.refresh}, format="json")
        self.assertEqual(replay.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_revokes_refresh_token(self) -> None:
        self.client.post(reverse("auth_logout"), {"refreshToken": self.refresh}, format="json")
        replay = self.client.post(reverse("auth_refresh"), {"refresh": self.refresh}, format="json")
        self.assertEqual(replay.status_code, status.HTTP_401_UNAUTHORIZED)


class TokenEncryptionKeyTests(APITestCase):
    """D: social tokens survive key rotation; production refuses to start without a key."""

    def test_rotation_keeps_old_tokens_readable(self) -> None:
        from cryptography.fernet import Fernet

        from projects import crypto

        old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
        try:
            with override_settings(SOCIAL_TOKEN_ENCRYPTION_KEY=old):
                crypto._fernet.cache_clear()
                stored = crypto.encrypt("ya29.secret")
            with override_settings(SOCIAL_TOKEN_ENCRYPTION_KEY=f"{new},{old}"):
                crypto._fernet.cache_clear()
                self.assertEqual(crypto.decrypt(stored), "ya29.secret")
                self.assertEqual(Fernet(new.encode()).decrypt(crypto.encrypt("x").encode()), b"x")
        finally:
            crypto._fernet.cache_clear()

    def test_production_requires_encryption_key_and_hardens_cookies(self) -> None:
        settings_test = ProductionSettingsTests()
        missing = settings_test._load_settings(SECRET_KEY="prod-secret")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("SOCIAL_TOKEN_ENCRYPTION_KEY must be set", missing.stderr)


class AuthBruteForceLimitTests(APITestCase):
    """#9: credential endpoints are rate limited per IP (settings "auth_sensitive")."""

    def test_sixth_login_attempt_in_a_minute_is_blocked(self) -> None:
        User.objects.create_user(email="victim2@example.com", password="Correct-Horse-9")
        codes = [
            self.client.post(reverse("auth_login"), {"email": "victim2@example.com", "password": f"guess{i}"}, format="json").status_code
            for i in range(6)
        ]
        self.assertEqual(codes[:5], [401] * 5)
        self.assertEqual(codes[5], 429)


class AccountDeletionTests(APITestCase):
    """Self-service deletion removes the account, its data and files; keeps payment rows."""

    def setUp(self) -> None:
        import tempfile
        from pathlib import Path

        self.tmp = Path(tempfile.mkdtemp())
        self.override = override_settings(MEDIA_ROOT=str(self.tmp / "media"), PRIVATE_MEDIA_ROOT=self.tmp / "private")
        self.override.enable()
        self.user = User.objects.create_user(email="leaving@example.com", password="Password123!")

    def tearDown(self) -> None:
        import shutil

        self.override.disable()
        shutil.rmtree(self.tmp)

    def _seed(self):
        from django.core.files.base import ContentFile

        from admin_panel.models import Payment
        from content.models import ImageUpload
        from projects.models import Project, SocialAccount

        project = Project.objects.create(owner=self.user, name="Brand")
        account = SocialAccount.objects.create(project=project, platform="youtube", connected=True)
        account.store_tokens(access_token="ya29.secret", refresh_token="1//refresh", expires_in=3600, scope="")
        account.save()
        out = self.tmp / "media" / "projects" / str(project.id) / "images" / "job1"
        out.mkdir(parents=True)
        (out / "out-0.png").write_bytes(b"png")
        upload = ImageUpload.objects.create(project=project, user=self.user, content_type="image/png", byte_size=3)
        upload.file.save("u.png", ContentFile(b"png"))
        payment = Payment.objects.create(user=self.user, amount=7999, currency="PKR", status="paid", plan="plus", provider_ref="EP-77")
        payment.screenshot.save("proof.png", ContentFile(b"proof"))
        return project, payment, upload

    def _delete(self, **body):
        self.client.force_authenticate(user=self.user)
        return self.client.post(reverse("auth_delete_account"), body, format="json")

    def test_deletes_everything_but_keeps_anonymous_payment_record(self) -> None:
        from admin_panel.models import Payment
        from projects.models import Project, SocialAccount

        project, payment, upload = self._seed()
        upload_path = self.tmp / "media" / upload.file.name
        proof_path = self.tmp / "private" / payment.screenshot.name
        self.assertTrue(upload_path.exists() and proof_path.exists())

        with self.captureOnCommitCallbacks(execute=True):
            response = self._delete(password="Password123!")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertFalse(User.objects.filter(email="leaving@example.com").exists())
        self.assertFalse(Project.objects.filter(pk=project.pk).exists())
        self.assertFalse(SocialAccount.objects.exists())  # OAuth tokens gone
        self.assertFalse((self.tmp / "media" / "projects" / str(project.id)).exists())
        self.assertFalse(upload_path.exists())
        self.assertFalse(proof_path.exists())

        kept = Payment.objects.get(pk=payment.pk)
        self.assertIsNone(kept.user)
        self.assertEqual((kept.payer_email, kept.amount, kept.provider_ref), ("leaving@example.com", 7999, "EP-77"))
        self.assertFalse(kept.screenshot)

    def test_wrong_password_deletes_nothing(self) -> None:
        response = self._delete(password="nope")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_google_only_account_confirms_with_email(self) -> None:
        self.user.set_unusable_password()
        self.user.save()
        self.assertEqual(self._delete(confirmEmail="someone@else.com").status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self._delete(confirmEmail="LEAVING@example.com").status_code, status.HTTP_200_OK)
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())

    def test_staff_cannot_self_delete(self) -> None:
        self.user.is_staff = True
        self.user.save()
        self.assertEqual(self._delete(password="Password123!").status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_old_refresh_token_stops_working(self) -> None:
        login = self.client.post(reverse("auth_login"), {"email": "leaving@example.com", "password": "Password123!"}, format="json")
        refresh = login.data["refreshToken"]
        self._delete(password="Password123!")
        self.client.force_authenticate(user=None)
        response = self.client.post(reverse("auth_refresh"), {"refresh": refresh}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
