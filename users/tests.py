from typing import Any
from django.contrib.auth import get_user_model
from django.core.signing import TimestampSigner
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()
signer = TimestampSigner()


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
        self.assertEqual(response.data["user"]["creditsRemaining"], 50)

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
        token = signer.sign(str(self.user.id))
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

    def test_google_oauth_exchange_success(self) -> None:
        """Test mock Google OAuth exchange creates user and returns JWT tokens."""
        google_data = {"code": "mock-auth-code-123456"}
        response = self.client.post(self.google_url, google_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("accessToken", response.data)
        self.assertIn("refreshToken", response.data)
        self.assertIn("user", response.data)
        self.assertTrue(response.data["user"]["email"].startswith("google_user_mock-a"))
        self.assertEqual(response.data["user"]["googleId"], "google-oauth-mock-auth-co")
        self.assertEqual(response.data["user"]["firstName"], "")
        self.assertEqual(response.data["user"]["lastName"], "")
        self.assertEqual(response.data["user"]["creditsRemaining"], 50)

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
        self.assertFalse(response.data["paymentConnected"])

    def test_activate_plan_for_testing(self) -> None:
        response = self.client.post("/api/credits/plan", {"plan": "plus"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["plan"], "plus")
        self.assertEqual(response.data["creditsTotal"], 35)
        self.assertEqual(response.data["creditsRemaining"], 35)
        self.assertEqual(response.data["creditsUsed"], 0)
        self.assertEqual(response.data["planDetails"]["priceUsd"], "29")

        self.user.refresh_from_db()
        self.assertEqual(self.user.plan, "plus")

    def test_unauthenticated(self) -> None:
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get("/api/credits").status_code, status.HTTP_401_UNAUTHORIZED)


class ClerkAuthenticationTests(APITestCase):
    """Test suite for Clerk JWT authentication class."""

    def test_clerk_auth_creates_new_user(self) -> None:
        """Test ClerkJWTAuthentication creates user when valid token is presented."""
        from unittest.mock import MagicMock, patch
        from users.authentication import ClerkJWTAuthentication

        auth = ClerkJWTAuthentication()
        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Bearer fake.clerk.jwt.token"}

        mock_payload = {
            "iss": "https://calm-seal-81.clerk.accounts.dev",
            "sub": "user_2test123456789",
            "email": "clerk_test@example.com",
            "first_name": "Clerk",
            "last_name": "Tester",
        }

        with patch("jwt.decode", return_value=mock_payload):
            with patch("users.authentication._get_jwks_client") as mock_jwks:
                mock_jwks_client = MagicMock()
                mock_jwks_client.get_signing_key_from_jwt.return_value = MagicMock(key="public_key")
                mock_jwks.return_value = mock_jwks_client

                user, token = auth.authenticate(mock_request)
                self.assertIsNotNone(user)
                self.assertEqual(user.email, "clerk_test@example.com")
                self.assertEqual(user.google_id, "user_2test123456789")
                self.assertEqual(user.credits_remaining, 50)
                self.assertEqual(token, "fake.clerk.jwt.token")

    def test_clerk_auth_returns_existing_user(self) -> None:
        """Test ClerkJWTAuthentication matches existing user by google_id."""
        from unittest.mock import MagicMock, patch
        from users.authentication import ClerkJWTAuthentication

        existing_user = User.objects.create_user(
            email="existing_clerk@example.com",
            google_id="user_2existing_id",
        )

        auth = ClerkJWTAuthentication()
        mock_request = MagicMock()
        mock_request.headers = {"Authorization": "Bearer fake.clerk.jwt.token"}

        mock_payload = {
            "iss": "https://calm-seal-81.clerk.accounts.dev",
            "sub": "user_2existing_id",
        }

        with patch("jwt.decode", return_value=mock_payload):
            with patch("users.authentication._get_jwks_client") as mock_jwks:
                mock_jwks_client = MagicMock()
                mock_jwks_client.get_signing_key_from_jwt.return_value = MagicMock(key="public_key")
                mock_jwks.return_value = mock_jwks_client

                user, token = auth.authenticate(mock_request)
                self.assertEqual(user, existing_user)
