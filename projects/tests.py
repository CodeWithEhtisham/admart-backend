from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from projects.crypto import decrypt
from projects.models import Project, SocialAccount
from projects.views import OAUTH_STATE_SALT

User = get_user_model()


class ProjectCRUDTests(APITestCase):
    """Test suite for Project list/create/detail/update/delete/activate."""

    def setUp(self) -> None:
        self.list_url = reverse("project_list_create")
        self.user = User.objects.create_user(
            email="owner@example.com", password="Password123!", first_name="Ann", last_name="Owner"
        )
        self.other = User.objects.create_user(
            email="other@example.com", password="Password123!", first_name="Bob", last_name="Other"
        )
        self.client.force_authenticate(user=self.user)

    def test_list_requires_auth(self) -> None:
        self.client.force_authenticate(user=None)
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_empty_list_signals_onboarding(self) -> None:
        """A user with no projects gets an empty list and null active id."""
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["projects"], [])
        self.assertIsNone(response.data["activeProjectId"])

    def test_create_project_becomes_active(self) -> None:
        response = self.client.post(
            self.list_url,
            {"name": "Summer Campaign", "icon": "☀", "color": "#7c3aed", "org": "Admart"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["name"], "Summer Campaign")
        self.assertIsNotNone(response.data["lastAccessedAt"])

        self.user.refresh_from_db()
        self.assertEqual(str(self.user.active_project_id), response.data["id"])

    def test_create_validation_error(self) -> None:
        response = self.client.post(self.list_url, {"name": ""}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("name", response.data)

    def test_list_ordered_by_recency(self) -> None:
        p1 = Project.objects.create(owner=self.user, name="First")
        p2 = Project.objects.create(owner=self.user, name="Second")
        p1.touch()  # make p1 most recent

        response = self.client.get(self.list_url)
        ids = [p["id"] for p in response.data["projects"]]
        self.assertEqual(ids[0], str(p1.id))
        self.assertEqual(response.data["activeProjectId"], str(p1.id))
        self.assertEqual(set(ids), {str(p1.id), str(p2.id)})

    def test_detail_not_owned_returns_404(self) -> None:
        foreign = Project.objects.create(owner=self.other, name="Secret")
        url = reverse("project_detail", kwargs={"id": foreign.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_patch_project(self) -> None:
        project = Project.objects.create(owner=self.user, name="Old Name")
        url = reverse("project_detail", kwargs={"id": project.id})
        response = self.client.patch(url, {"name": "New Name", "org": "Personal"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["name"], "New Name")
        self.assertEqual(response.data["org"], "Personal")

    def test_delete_project(self) -> None:
        project = Project.objects.create(owner=self.user, name="Doomed")
        url = reverse("project_detail", kwargs={"id": project.id})
        response = self.client.delete(url)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(Project.objects.filter(id=project.id).exists())

    def test_delete_active_project_clears_pointer(self) -> None:
        """SET_NULL keeps the user valid after deleting their active project."""
        project = Project.objects.create(owner=self.user, name="Active")
        self.user.active_project = project
        self.user.save(update_fields=["active_project"])

        url = reverse("project_detail", kwargs={"id": project.id})
        self.client.delete(url)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.active_project_id)

    def test_activate_project(self) -> None:
        project = Project.objects.create(owner=self.user, name="Switch To Me")
        url = reverse("project_activate", kwargs={"id": project.id})
        response = self.client.post(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["activeProjectId"], str(project.id))

        self.user.refresh_from_db()
        self.assertEqual(self.user.active_project_id, project.id)
        project.refresh_from_db()
        self.assertIsNotNone(project.last_accessed_at)

    def test_activate_not_owned_returns_404(self) -> None:
        foreign = Project.objects.create(owner=self.other, name="Nope")
        url = reverse("project_activate", kwargs={"id": foreign.id})
        response = self.client.post(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_active_project_persists_across_logout_login(self) -> None:
        """After activating a project, logging back in auto-selects it."""
        Project.objects.create(owner=self.user, name="Older")
        chosen = Project.objects.create(owner=self.user, name="Chosen")
        self.client.post(reverse("project_activate", kwargs={"id": chosen.id}), format="json")

        # Simulate logout + fresh login (no force_authenticate).
        self.client.force_authenticate(user=None)
        login = self.client.post(
            reverse("auth_login"),
            {"email": "owner@example.com", "password": "Password123!"},
            format="json",
        )
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.assertEqual(login.data["user"]["activeProjectId"], str(chosen.id))


class ProjectSocialTests(APITestCase):
    """Test suite for project-scoped social account endpoints."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="social@example.com", password="Password123!", first_name="Sam", last_name="Social"
        )
        self.other = User.objects.create_user(
            email="intruder@example.com", password="Password123!", first_name="Eve", last_name="Intruder"
        )
        self.client.force_authenticate(user=self.user)
        self.project = Project.objects.create(owner=self.user, name="Brand A")

    def _url(self, name: str, **extra) -> str:
        return reverse(name, kwargs={"project_id": self.project.id, **extra})

    def test_connect_social(self) -> None:
        url = self._url("project_social_connect", platform="instagram")
        response = self.client.post(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["platform"], "instagram")
        self.assertEqual(response.data["projectId"], str(self.project.id))
        self.assertTrue(response.data["connected"])

    def test_connect_invalid_platform(self) -> None:
        url = self._url("project_social_connect", platform="twitter")
        response = self.client.post(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_connect_on_foreign_project_returns_404(self) -> None:
        foreign = Project.objects.create(owner=self.other, name="Brand B")
        url = reverse("project_social_connect", kwargs={"project_id": foreign.id, "platform": "tiktok"})
        response = self.client.post(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_social(self) -> None:
        SocialAccount.objects.create(project=self.project, platform="tiktok", connected=True)
        SocialAccount.objects.create(project=self.project, platform="youtube", connected=True)
        url = self._url("project_social_list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_disconnect_social(self) -> None:
        SocialAccount.objects.create(project=self.project, platform="facebook", connected=True)
        url = self._url("project_social_disconnect", platform="facebook")
        response = self.client.delete(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        account = SocialAccount.objects.get(project=self.project, platform="facebook")
        self.assertFalse(account.connected)

    def test_disconnect_nonexistent_returns_404(self) -> None:
        url = self._url("project_social_disconnect", platform="tiktok")
        response = self.client.delete(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_reconnect_social(self) -> None:
        SocialAccount.objects.create(project=self.project, platform="instagram", connected=False)
        url = self._url("project_social_connect", platform="instagram")
        response = self.client.post(url, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["connected"])

    def test_same_platform_isolated_per_project(self) -> None:
        """Two projects can each connect the same platform independently."""
        project_b = Project.objects.create(owner=self.user, name="Brand B")
        SocialAccount.objects.create(project=self.project, platform="tiktok")
        # Should not conflict with the unique_together(project, platform).
        SocialAccount.objects.create(project=project_b, platform="tiktok")
        self.assertEqual(SocialAccount.objects.filter(platform="tiktok").count(), 2)


@override_settings(
    GOOGLE_OAUTH_CLIENT_ID="test-client-id",
    GOOGLE_OAUTH_CLIENT_SECRET="test-secret",
    YOUTUBE_OAUTH_REDIRECT_URI="http://testserver/api/social/callback/youtube",
    FRONTEND_URL="http://localhost:5173",
)
class YouTubeOAuthConnectionTests(APITestCase):
    """Test suite for the real OAuth connect-url + provider callback flow."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="creator@example.com", password="Password123!", first_name="Cara", last_name="Creator"
        )
        self.other = User.objects.create_user(
            email="stranger@example.com", password="Password123!", first_name="Stu", last_name="Stranger"
        )
        self.client.force_authenticate(user=self.user)
        self.project = Project.objects.create(owner=self.user, name="Brand A")

    def _connect_url(self, platform: str) -> str:
        return reverse(
            "project_social_connect_url",
            kwargs={"project_id": self.project.id, "platform": platform},
        )

    def test_connect_url_returns_authurl_and_state(self) -> None:
        response = self.client.get(self._connect_url("youtube"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("authUrl", response.data)
        self.assertIn("state", response.data)
        self.assertIn("accounts.google.com", response.data["authUrl"])
        self.assertIn("client_id=test-client-id", response.data["authUrl"])
        self.assertIn("youtube.upload", response.data["authUrl"])

        payload = signing.loads(response.data["state"], salt=OAUTH_STATE_SALT, max_age=600)
        self.assertEqual(payload["projectId"], str(self.project.id))
        self.assertEqual(payload["userId"], str(self.user.id))
        self.assertEqual(payload["platform"], "youtube")

    def test_connect_url_unimplemented_platform_returns_501(self) -> None:
        response = self.client.get(self._connect_url("tiktok"))
        self.assertEqual(response.status_code, status.HTTP_501_NOT_IMPLEMENTED)
        self.assertEqual(response.data["platform"], "tiktok")

    def test_connect_url_unknown_platform_returns_400(self) -> None:
        response = self.client.get(self._connect_url("myspace"))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_connect_url_foreign_project_returns_404(self) -> None:
        foreign = Project.objects.create(owner=self.other, name="Not Mine")
        url = reverse(
            "project_social_connect_url",
            kwargs={"project_id": foreign.id, "platform": "youtube"},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def _valid_state(self) -> str:
        return signing.dumps(
            {
                "projectId": str(self.project.id),
                "platform": "youtube",
                "userId": str(self.user.id),
                "nonce": "abc",
            },
            salt=OAUTH_STATE_SALT,
        )

    @patch("projects.oauth.YouTubeProvider.fetch_profile")
    @patch("projects.oauth.YouTubeProvider.exchange_code")
    def test_callback_success_creates_connected_account(self, mock_exchange, mock_profile) -> None:
        mock_exchange.return_value = {
            "access_token": "ya29.access",
            "refresh_token": "1//refresh",
            "expires_in": 3600,
            "scope": "https://www.googleapis.com/auth/youtube.upload",
        }
        mock_profile.return_value = {
            "externalId": "UC_channel_123",
            "displayName": "Cara's Channel",
            "handle": "@cara",
            "avatarUrl": "https://yt3.example/avatar.jpg",
        }

        # Callback is reached unauthenticated (browser redirect).
        self.client.force_authenticate(user=None)
        url = reverse("social_callback", kwargs={"platform": "youtube"})
        response = self.client.get(url, {"code": "auth-code", "state": self._valid_state()})

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response["Location"], "http://localhost:5173/social?connected=youtube")

        account = SocialAccount.objects.get(project=self.project, platform="youtube")
        self.assertTrue(account.connected)
        self.assertEqual(account.external_id, "UC_channel_123")
        self.assertEqual(account.display_name, "Cara's Channel")
        self.assertEqual(account.handle, "@cara")
        # Tokens are encrypted at rest but decrypt back to the originals.
        self.assertNotEqual(account.access_token, "ya29.access")
        self.assertEqual(decrypt(account.access_token), "ya29.access")
        self.assertEqual(account.get_refresh_token(), "1//refresh")
        self.assertIsNotNone(account.token_expires_at)

    def test_callback_bad_state_redirects_with_error(self) -> None:
        self.client.force_authenticate(user=None)
        url = reverse("social_callback", kwargs={"platform": "youtube"})
        response = self.client.get(url, {"code": "auth-code", "state": "tampered"})
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response["Location"], "http://localhost:5173/social?error=youtube")
        self.assertFalse(SocialAccount.objects.filter(project=self.project).exists())

    def test_callback_provider_error_param_redirects_with_error(self) -> None:
        self.client.force_authenticate(user=None)
        url = reverse("social_callback", kwargs={"platform": "youtube"})
        response = self.client.get(url, {"error": "access_denied", "state": self._valid_state()})
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn("error=youtube", response["Location"])

    @patch("projects.oauth.YouTubeProvider.exchange_code", side_effect=Exception("boom"))
    def test_callback_exchange_failure_redirects_with_error(self, _mock_exchange) -> None:
        self.client.force_authenticate(user=None)
        url = reverse("social_callback", kwargs={"platform": "youtube"})
        response = self.client.get(url, {"code": "auth-code", "state": self._valid_state()})
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertIn("error=youtube", response["Location"])
        self.assertFalse(SocialAccount.objects.filter(project=self.project).exists())


@override_settings(
    META_APP_ID="test-meta-app",
    META_APP_SECRET="test-meta-secret",
    FACEBOOK_OAUTH_REDIRECT_URI="http://testserver/api/social/callback/facebook",
    INSTAGRAM_OAUTH_REDIRECT_URI="http://testserver/api/social/callback/instagram",
    FRONTEND_URL="http://localhost:5173",
)
class MetaOAuthConnectionTests(APITestCase):
    """Test suite for the shared Meta (Facebook + Instagram) OAuth flow."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="meta@example.com", password="Password123!", first_name="Maya", last_name="Meta"
        )
        self.client.force_authenticate(user=self.user)
        self.project = Project.objects.create(owner=self.user, name="Brand A")

    def _connect_url(self, platform: str) -> str:
        return reverse(
            "project_social_connect_url",
            kwargs={"project_id": self.project.id, "platform": platform},
        )

    def _valid_state(self, platform: str) -> str:
        return signing.dumps(
            {
                "projectId": str(self.project.id),
                "platform": platform,
                "userId": str(self.user.id),
                "nonce": "abc",
            },
            salt=OAUTH_STATE_SALT,
        )

    def test_facebook_connect_url(self) -> None:
        response = self.client.get(self._connect_url("facebook"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("facebook.com", response.data["authUrl"])
        self.assertIn("client_id=test-meta-app", response.data["authUrl"])
        # Login works with a default scope; publishing scopes are gated behind App Review.
        self.assertIn("public_profile", response.data["authUrl"])

    def test_instagram_connect_url(self) -> None:
        response = self.client.get(self._connect_url("instagram"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("facebook.com", response.data["authUrl"])
        self.assertIn("public_profile", response.data["authUrl"])

    @patch("projects.oauth.MetaProvider.fetch_profile")
    @patch("projects.oauth.MetaProvider.exchange_code")
    def test_facebook_callback_success(self, mock_exchange, mock_profile) -> None:
        mock_exchange.return_value = {"access_token": "EAA.long", "expires_in": 5184000}
        mock_profile.return_value = {
            "externalId": "fb-123",
            "displayName": "Maya's Page",
            "handle": "",
            "avatarUrl": None,
        }
        self.client.force_authenticate(user=None)
        url = reverse("social_callback", kwargs={"platform": "facebook"})
        response = self.client.get(url, {"code": "c", "state": self._valid_state("facebook")})

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response["Location"], "http://localhost:5173/social?connected=facebook")
        account = SocialAccount.objects.get(project=self.project, platform="facebook")
        self.assertTrue(account.connected)
        self.assertEqual(account.external_id, "fb-123")
        self.assertEqual(account.get_access_token(), "EAA.long")

    @patch("projects.oauth.InstagramProvider.fetch_profile")
    @patch("projects.oauth.InstagramProvider.exchange_code")
    def test_instagram_callback_success(self, mock_exchange, mock_profile) -> None:
        mock_exchange.return_value = {"access_token": "EAA.iglong", "expires_in": 5184000}
        mock_profile.return_value = {
            "externalId": "ig-999",
            "displayName": "maya.creates",
            "handle": "maya.creates",
            "avatarUrl": "https://cdn.example/ig.jpg",
        }
        self.client.force_authenticate(user=None)
        url = reverse("social_callback", kwargs={"platform": "instagram"})
        response = self.client.get(url, {"code": "c", "state": self._valid_state("instagram")})

        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response["Location"], "http://localhost:5173/social?connected=instagram")
        account = SocialAccount.objects.get(project=self.project, platform="instagram")
        self.assertEqual(account.handle, "maya.creates")
        self.assertEqual(account.external_id, "ig-999")
