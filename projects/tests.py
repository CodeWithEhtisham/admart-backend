from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import SimpleTestCase, override_settings
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
        self.assertIn("youtube.force-ssl", response.data["authUrl"])
        self.assertIn("youtube.upload", response.data["authUrl"])
        self.assertIn("select_account", response.data["authUrl"])
        self.assertNotIn("include_granted_scopes", response.data["authUrl"])

        payload = signing.loads(response.data["state"], salt=OAUTH_STATE_SALT, max_age=600)
        self.assertEqual(payload["projectId"], str(self.project.id))
        self.assertEqual(payload["userId"], str(self.user.id))
        self.assertEqual(payload["platform"], "youtube")

    def test_tiktok_connect_url_returns_authurl(self) -> None:
        with self.settings(
            TIKTOK_CLIENT_KEY="tt-key",
            TIKTOK_CLIENT_SECRET="tt-secret",
            TIKTOK_OAUTH_REDIRECT_URI="https://example.ngrok-free.app/api/social/callback/tiktok",
        ):
            response = self.client.get(self._connect_url("tiktok"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("tiktok.com/v2/auth/authorize", response.data["authUrl"])
        self.assertIn("client_key=tt-key", response.data["authUrl"])
        self.assertIn("user.info.basic", response.data["authUrl"])
        self.assertNotIn("video.publish", response.data["authUrl"])

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
        self.assertNotIn("pages_show_list", response.data["authUrl"])

    @override_settings(FACEBOOK_PUBLISH_ENABLED=True)
    def test_facebook_connect_url_includes_publish_scopes_when_enabled(self) -> None:
        response = self.client.get(self._connect_url("facebook"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("pages_show_list", response.data["authUrl"])
        self.assertIn("pages_manage_posts", response.data["authUrl"])

    def test_instagram_connect_url(self) -> None:
        response = self.client.get(self._connect_url("instagram"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("instagram.com/oauth/authorize", response.data["authUrl"])
        self.assertIn("instagram_business_basic", response.data["authUrl"])
        self.assertIn("client_id=test-meta-app", response.data["authUrl"])
        self.assertNotIn("facebook.com", response.data["authUrl"])
        self.assertNotIn("instagram_business_content_publish", response.data["authUrl"])

    @override_settings(INSTAGRAM_APP_ID="ig-app-id")
    def test_instagram_connect_url_prefers_instagram_app_id(self) -> None:
        response = self.client.get(self._connect_url("instagram"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("client_id=ig-app-id", response.data["authUrl"])

    @override_settings(INSTAGRAM_PUBLISH_ENABLED=True)
    def test_instagram_connect_url_includes_publish_scopes_when_enabled(self) -> None:
        response = self.client.get(self._connect_url("instagram"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("instagram_business_basic", response.data["authUrl"])
        self.assertIn("instagram_business_content_publish", response.data["authUrl"])

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


@override_settings(
    INSTAGRAM_APP_ID="ig-id",
    INSTAGRAM_APP_SECRET="ig-secret",
    INSTAGRAM_OAUTH_REDIRECT_URI="http://testserver/api/social/callback/instagram",
    INSTAGRAM_PUBLISH_ENABLED=False,
)
class InstagramProviderTests(SimpleTestCase):
    """Instagram Business Login token exchange."""

    @patch("projects.oauth.requests.get")
    @patch("projects.oauth.requests.post")
    def test_exchange_code_unwraps_data_and_upgrades_token(self, mock_post, mock_get) -> None:
        mock_post.return_value.json.return_value = {
            "data": [
                {
                    "access_token": "short",
                    "user_id": "99",
                    "permissions": "instagram_business_basic",
                }
            ]
        }
        mock_get.return_value.json.return_value = {
            "access_token": "long",
            "token_type": "bearer",
            "expires_in": 5184000,
        }
        from projects.oauth import InstagramProvider

        tokens = InstagramProvider().exchange_code("auth-code")
        self.assertEqual(tokens["access_token"], "long")
        self.assertEqual(tokens["refresh_token"], "long")
        self.assertEqual(tokens["expires_in"], 5184000)
        self.assertEqual(mock_post.call_args.kwargs["data"]["code"], "auth-code")
        self.assertEqual(mock_get.call_args.kwargs["params"]["grant_type"], "ig_exchange_token")

    @patch("projects.oauth.requests.get")
    def test_fetch_profile_returns_handle(self, mock_get) -> None:
        mock_get.return_value.json.return_value = {
            "user_id": "17841",
            "username": "maya.creates",
            "name": "Maya",
            "profile_picture_url": "https://cdn.example/ig.jpg",
        }
        from projects.oauth import InstagramProvider

        profile = InstagramProvider().fetch_profile("long")
        self.assertEqual(profile["handle"], "maya.creates")
        self.assertEqual(profile["externalId"], "17841")
        self.assertEqual(profile["displayName"], "Maya")


@override_settings(
    TIKTOK_CLIENT_KEY="tt-key",
    TIKTOK_CLIENT_SECRET="tt-secret",
    TIKTOK_OAUTH_REDIRECT_URI="https://example.ngrok-free.app/api/social/callback/tiktok",
    TIKTOK_PUBLISH_ENABLED=False,
    FRONTEND_URL="http://localhost:5173",
)
class TikTokOAuthConnectionTests(APITestCase):
    """TikTok Login Kit connect URL + callback."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="tiktok@example.com", password="Password123!", first_name="Ty", last_name="Tok"
        )
        self.client.force_authenticate(user=self.user)
        self.project = Project.objects.create(owner=self.user, name="Brand A")

    def _valid_state(self) -> str:
        return signing.dumps(
            {
                "projectId": str(self.project.id),
                "platform": "tiktok",
                "userId": str(self.user.id),
                "nonce": "abc",
            },
            salt=OAUTH_STATE_SALT,
        )

    @override_settings(TIKTOK_PUBLISH_ENABLED=True)
    def test_connect_url_includes_publish_scopes_when_enabled(self) -> None:
        url = reverse(
            "project_social_connect_url",
            kwargs={"project_id": self.project.id, "platform": "tiktok"},
        )
        response = self.client.get(url)
        self.assertIn("video.upload", response.data["authUrl"])
        self.assertIn("video.publish", response.data["authUrl"])

    @patch("projects.oauth.TikTokProvider.fetch_profile")
    @patch("projects.oauth.TikTokProvider.exchange_code")
    def test_callback_success(self, mock_exchange, mock_profile) -> None:
        mock_exchange.return_value = {
            "access_token": "act.tt",
            "refresh_token": "rft.tt",
            "expires_in": 86400,
        }
        mock_profile.return_value = {
            "externalId": "oid-1",
            "displayName": "Maya Creates",
            "handle": "",
            "avatarUrl": "https://cdn.example/tt.jpg",
        }
        self.client.force_authenticate(user=None)
        url = reverse("social_callback", kwargs={"platform": "tiktok"})
        response = self.client.get(url, {"code": "c", "state": self._valid_state()})
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response["Location"], "http://localhost:5173/social?connected=tiktok")
        account = SocialAccount.objects.get(project=self.project, platform="tiktok")
        self.assertEqual(account.display_name, "Maya Creates")
        self.assertEqual(account.get_refresh_token(), "rft.tt")


@override_settings(
    TIKTOK_CLIENT_KEY="tt-key",
    TIKTOK_CLIENT_SECRET="tt-secret",
    TIKTOK_OAUTH_REDIRECT_URI="https://example.ngrok-free.app/api/social/callback/tiktok",
)
class TikTokProviderTests(SimpleTestCase):
    @patch("projects.oauth.requests.post")
    def test_exchange_code_returns_tokens(self, mock_post) -> None:
        mock_post.return_value.json.return_value = {
            "access_token": "act.tt",
            "refresh_token": "rft.tt",
            "expires_in": 86400,
            "open_id": "oid-1",
            "scope": "user.info.basic",
        }
        from projects.oauth import TikTokProvider

        tokens = TikTokProvider().exchange_code("auth-code")
        self.assertEqual(tokens["access_token"], "act.tt")
        self.assertEqual(tokens["refresh_token"], "rft.tt")
        self.assertEqual(mock_post.call_args.kwargs["data"]["grant_type"], "authorization_code")

    @patch("projects.oauth.requests.get")
    def test_fetch_profile_returns_display_name(self, mock_get) -> None:
        mock_get.return_value.json.return_value = {
            "data": {"user": {"open_id": "oid-1", "display_name": "Maya", "avatar_url": "https://cdn.example/a.jpg"}},
            "error": {"code": "ok", "message": ""},
        }
        from projects.oauth import TikTokProvider

        profile = TikTokProvider().fetch_profile("act.tt")
        self.assertEqual(profile["externalId"], "oid-1")
        self.assertEqual(profile["displayName"], "Maya")


@override_settings(
    SNAPCHAT_CLIENT_ID="snap-id",
    SNAPCHAT_CLIENT_SECRET="snap-secret",
    SNAPCHAT_OAUTH_REDIRECT_URI="http://localhost:8000/api/social/callback/snapchat",
    FRONTEND_URL="http://localhost:5173",
)
class SnapchatOAuthConnectionTests(APITestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="snap@example.com", password="Password123!", first_name="Sam", last_name="Snap"
        )
        self.client.force_authenticate(user=self.user)
        self.project = Project.objects.create(owner=self.user, name="Brand A")

    def _connect_url(self) -> str:
        return reverse(
            "project_social_connect_url",
            kwargs={"project_id": self.project.id, "platform": "snapchat"},
        )

    def test_connect_url_includes_pkce(self) -> None:
        response = self.client.get(self._connect_url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("accounts.snapchat.com", response.data["authUrl"])
        self.assertIn("code_challenge_method=S256", response.data["authUrl"])
        self.assertIn("client_id=snap-id", response.data["authUrl"])
        payload = signing.loads(response.data["state"], salt=OAUTH_STATE_SALT, max_age=600)
        self.assertTrue(payload.get("codeVerifier"))

    @patch("projects.oauth.SnapchatProvider.fetch_profile")
    @patch("projects.oauth.SnapchatProvider.exchange_code")
    def test_callback_success(self, mock_exchange, mock_profile) -> None:
        mock_exchange.return_value = {
            "access_token": "snap.access",
            "refresh_token": "snap.refresh",
            "expires_in": 3600,
        }
        mock_profile.return_value = {
            "externalId": "ext-1",
            "displayName": "Maya",
            "handle": "",
            "avatarUrl": "https://cdn.example/bitmoji.png",
        }
        state = signing.dumps(
            {
                "projectId": str(self.project.id),
                "platform": "snapchat",
                "userId": str(self.user.id),
                "nonce": "abc",
                "codeVerifier": "verifier",
            },
            salt=OAUTH_STATE_SALT,
        )
        self.client.force_authenticate(user=None)
        url = reverse("social_callback", kwargs={"platform": "snapchat"})
        response = self.client.get(url, {"code": "c", "state": state})
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response["Location"], "http://localhost:5173/social?connected=snapchat")
        mock_exchange.assert_called_once_with("c", code_verifier="verifier")
        account = SocialAccount.objects.get(project=self.project, platform="snapchat")
        self.assertEqual(account.display_name, "Maya")
        self.assertEqual(account.external_id, "ext-1")


@override_settings(
    SNAPCHAT_CLIENT_ID="snap-id",
    SNAPCHAT_CLIENT_SECRET="snap-secret",
    SNAPCHAT_OAUTH_REDIRECT_URI="http://localhost:8000/api/social/callback/snapchat",
)
class SnapchatProviderTests(SimpleTestCase):
    @patch("projects.oauth.requests.post")
    def test_fetch_profile_reads_graphql_me(self, mock_post) -> None:
        mock_post.return_value.json.return_value = {
            "data": {
                "me": {
                    "displayName": "Maya",
                    "externalId": "ext-1",
                    "bitmoji": {"avatar": "https://cdn.example/b.png"},
                }
            },
            "errors": [],
        }
        from projects.oauth import SnapchatProvider

        profile = SnapchatProvider().fetch_profile("tok")
        self.assertEqual(profile["displayName"], "Maya")
        self.assertEqual(profile["externalId"], "ext-1")
        self.assertEqual(profile["avatarUrl"], "https://cdn.example/b.png")


class MediaPolicyTests(SimpleTestCase):
    def test_youtube_rejects_image(self) -> None:
        from projects.media_policy import validate_organic_platforms

        self.assertEqual(
            validate_organic_platforms("image", ["youtube"]),
            "Video only — images cannot be posted here",
        )

    def test_youtube_accepts_video(self) -> None:
        from projects.media_policy import validate_organic_platforms

        self.assertEqual(validate_organic_platforms("video", ["youtube"]), "")

    def test_snapchat_organic_rejected(self) -> None:
        from projects.media_policy import validate_organic_platforms

        self.assertIn("Snapchat", validate_organic_platforms("video", ["snapchat"]))

    def test_tiktok_ads_rejects_image(self) -> None:
        from projects.media_policy import validate_ads_placements

        self.assertEqual(
            validate_ads_placements("image", "tiktok", ["tiktok"]),
            "Video only — images cannot be posted here",
        )

    def test_meta_ads_accepts_image(self) -> None:
        from projects.media_policy import validate_ads_placements

        self.assertEqual(validate_ads_placements("image", "meta", ["facebook", "instagram"]), "")

    def test_google_ads_rejects_image(self) -> None:
        from projects.media_policy import validate_ads_placements

        self.assertEqual(
            validate_ads_placements("image", "google", ["youtube"]),
            "Video only — images cannot be posted here",
        )

    def test_google_ads_accepts_video(self) -> None:
        from projects.media_policy import validate_ads_placements

        self.assertEqual(validate_ads_placements("video", "google", ["youtube"]), "")


def _youtube_ok(*_args, **_kwargs):
    return {"status": "succeeded", "externalId": "yt-vid-1"}


class OrganicPublishTests(APITestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="pub@example.com", password="Password123!", first_name="P", last_name="U"
        )
        self.client.force_authenticate(user=self.user)
        self.project = Project.objects.create(owner=self.user, name="Brand")
        self.url = reverse("project_publish", kwargs={"project_id": self.project.id})

    def test_image_youtube_returns_400(self) -> None:
        SocialAccount.objects.create(project=self.project, platform="youtube", connected=True)
        response = self.client.post(
            self.url,
            {"kind": "image", "sourceUrl": "https://cdn.example/a.png", "platforms": ["youtube"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Video only", response.data["message"])

    def test_snapchat_organic_returns_400(self) -> None:
        response = self.client.post(
            self.url,
            {"kind": "video", "sourceUrl": "https://cdn.example/v.mp4", "platforms": ["snapchat"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch.dict("projects.publish_views.PUBLISHERS", {"youtube": _youtube_ok})
    def test_video_youtube_returns_201(self) -> None:
        SocialAccount.objects.create(project=self.project, platform="youtube", connected=True)
        response = self.client.post(
            self.url,
            {"kind": "video", "sourceUrl": "https://cdn.example/v.mp4", "platforms": ["youtube"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "succeeded")
        self.assertEqual(response.data["results"]["youtube"]["externalId"], "yt-vid-1")

    def test_youtube_passes_title_tags_thumbnail(self) -> None:
        captured = {}

        def _capture(account, **kwargs):
            captured.update(kwargs)
            return {"status": "succeeded", "externalId": "yt-2"}

        SocialAccount.objects.create(project=self.project, platform="youtube", connected=True)
        with patch.dict("projects.publish_views.PUBLISHERS", {"youtube": _capture}):
            response = self.client.post(
                self.url,
                {
                    "kind": "video",
                    "sourceUrl": "https://cdn.example/v.mp4",
                    "platforms": ["youtube"],
                    "youtube": {
                        "title": "Summer drop",
                        "description": "New arrivals",
                        "tags": ["sale", "brand"],
                        "privacyStatus": "unlisted",
                        "thumbnailUrl": "https://cdn.example/thumb.jpg",
                        "categoryId": "24",
                    },
                },
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(captured["title"], "Summer drop")
        self.assertEqual(captured["description"], "New arrivals")
        self.assertEqual(captured["tags"], ["sale", "brand"])
        self.assertEqual(captured["privacy"], "unlisted")
        self.assertEqual(captured["thumbnail_url"], "https://cdn.example/thumb.jpg")
        self.assertEqual(captured["category_id"], "24")
        self.assertFalse(captured["made_for_kids"])
        self.assertTrue(captured["synthetic_media"])
        self.assertEqual(captured["license_type"], "youtube")

        captured.clear()
        with patch.dict("projects.publish_views.PUBLISHERS", {"youtube": _capture}):
            response = self.client.post(
                self.url,
                {
                    "kind": "video",
                    "sourceUrl": "https://cdn.example/v.mp4",
                    "platforms": ["youtube"],
                    "youtube": {
                        "title": "Kids cut",
                        "madeForKids": "yes",
                        "containsSyntheticMedia": False,
                        "license": "creativeCommon",
                        "notifySubscribers": False,
                        "playlistId": "PL123",
                        "language": "en",
                        "embeddable": False,
                        "publicStatsViewable": False,
                        "publishAt": "2026-09-10T15:30:00Z",
                        "recordingDate": "2026-08-01",
                        "paidPromotion": True,
                    },
                },
                format="json",
            )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(captured["title"], "Kids cut")
        self.assertTrue(captured["made_for_kids"])
        self.assertFalse(captured["synthetic_media"])
        self.assertEqual(captured["license_type"], "creativeCommon")
        self.assertFalse(captured["notify_subscribers"])
        self.assertEqual(captured["playlist_id"], "PL123")
        self.assertEqual(captured["language"], "en")
        self.assertFalse(captured["embeddable"])
        self.assertFalse(captured["public_stats"])
        self.assertEqual(captured["publish_at"], "2026-09-10T15:30:00Z")
        self.assertEqual(captured["recording_date"], "2026-08-01T00:00:00Z")
        self.assertTrue(captured["paid_promotion"])

    def test_facebook_without_review_fails(self) -> None:
        SocialAccount.objects.create(project=self.project, platform="facebook", connected=True)
        response = self.client.post(
            self.url,
            {"kind": "image", "sourceUrl": "https://cdn.example/a.png", "platforms": ["facebook"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["status"], "failed")
        self.assertIn("App Review", response.data["results"]["facebook"]["error"])

    def test_not_connected_returns_400(self) -> None:
        response = self.client.post(
            self.url,
            {"kind": "video", "sourceUrl": "https://cdn.example/v.mp4", "platforms": ["youtube"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Not connected", response.data["message"])

    def test_youtube_playlists_requires_connect(self) -> None:
        url = reverse("project_youtube_playlists", kwargs={"project_id": self.project.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("projects.publish_views.list_youtube_playlists")
    def test_youtube_playlists_returns_rows(self, mocked) -> None:
        mocked.return_value = [{"id": "PL1", "title": "Launch"}]
        SocialAccount.objects.create(project=self.project, platform="youtube", connected=True)
        url = reverse("project_youtube_playlists", kwargs={"project_id": self.project.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data[0]["title"], "Launch")


class YoutubeSuggestTests(APITestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="yt-suggest@example.com", password="Password123!", first_name="Y", last_name="T"
        )
        self.client.force_authenticate(user=self.user)
        self.project = Project.objects.create(
            owner=self.user, name="Shop", brand_name="Shop Co", brand_industry="retail"
        )
        self.url = reverse("project_youtube_suggest", kwargs={"project_id": self.project.id})

    @override_settings(GEMINI_API_KEY="")
    def test_suggest_requires_gemini_key(self) -> None:
        response = self.client.post(
            self.url,
            {"title": "Summer drop", "prompt": "cinematic product launch for a clothing brand"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertIn("GEMINI_API_KEY", response.data["message"])

    @override_settings(GEMINI_API_KEY="test-gemini-key", PROMPT_ENHANCER_MODEL="gemini-test")
    @patch("projects.youtube_suggest.requests.post")
    def test_suggest_uses_gemini_json(self, mock_post) -> None:
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": (
                                    '{"title":"Summer Drop Official","description":"New arrivals '
                                    'this season.","tags":["sale","fashion","brand"],'
                                    '"categoryId":"26","language":"en"}'
                                )
                            }
                        ]
                    }
                }
            ]
        }
        response = self.client.post(
            self.url,
            {"title": "clip", "prompt": "summer fashion haul"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Summer Drop Official")
        self.assertEqual(response.data["description"], "New arrivals this season.")
        self.assertEqual(response.data["tags"], ["sale", "fashion", "brand"])
        self.assertEqual(response.data["categoryId"], "26")
        self.assertEqual(response.data["language"], "en")

    @override_settings(GEMINI_API_KEY="test-gemini-key", PROMPT_ENHANCER_MODEL="gemini-test")
    @patch("projects.youtube_suggest.requests.post")
    def test_suggest_gemini_error_is_not_hidden(self, mock_post) -> None:
        mock_post.return_value.status_code = 404
        mock_post.return_value.text = "model not found"
        response = self.client.post(
            self.url,
            {"title": "clip", "prompt": "summer fashion haul"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("Gemini", response.data["message"])

    def test_suggest_requires_prompt_or_title(self) -> None:
        response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


@override_settings(
    META_APP_ID="meta-app",
    META_APP_SECRET="meta-secret",
    META_ADS_APP_ID="",
    META_ADS_APP_SECRET="",
    META_ADS_OAUTH_REDIRECT_URI="http://testserver/api/ads/callback/meta",
    FRONTEND_URL="http://localhost:5173",
)
class AdsAccountTests(APITestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="ads@example.com", password="Password123!", first_name="A", last_name="D"
        )
        self.client.force_authenticate(user=self.user)
        self.project = Project.objects.create(owner=self.user, name="Ads Brand")

    def test_meta_connect_url(self) -> None:
        url = reverse("project_ads_connect_url", kwargs={"project_id": self.project.id, "provider": "meta"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("facebook.com", response.data["authUrl"])
        self.assertIn("client_id=meta-app", response.data["authUrl"])
        self.assertIn("ads_management", response.data["authUrl"])
        self.assertIn("ads_read", response.data["authUrl"])
        self.assertNotIn("business_management", response.data["authUrl"])

    @override_settings(META_ADS_APP_ID="ads-app-id")
    def test_meta_connect_url_uses_ads_app_id(self) -> None:
        url = reverse("project_ads_connect_url", kwargs={"project_id": self.project.id, "provider": "meta"})
        response = self.client.get(url)
        self.assertIn("client_id=ads-app-id", response.data["authUrl"])

    def test_unknown_provider_400(self) -> None:
        url = reverse("project_ads_connect_url", kwargs={"project_id": self.project.id, "provider": "myspace"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_boost_without_account_400(self) -> None:
        url = reverse("project_ads_boost", kwargs={"project_id": self.project.id})
        response = self.client.post(
            url,
            {
                "provider": "meta",
                "kind": "video",
                "sourceUrl": "https://cdn.example/v.mp4",
                "placements": ["facebook"],
                "budget": "10",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Connect", response.data["message"])

    @patch("projects.ads_oauth.create_boost", return_value={"externalId": "camp-1"})
    def test_meta_boost_201(self, _mock_boost) -> None:
        from projects.models import AdAccount

        AdAccount.objects.create(
            project=self.project, provider="meta", connected=True, external_id="act_1"
        )
        url = reverse("project_ads_boost", kwargs={"project_id": self.project.id})
        response = self.client.post(
            url,
            {
                "provider": "meta",
                "kind": "video",
                "sourceUrl": "https://cdn.example/v.mp4",
                "placements": ["facebook", "instagram"],
                "budget": "25",
                "startDate": "2026-09-01",
                "endDate": "2026-09-07",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["status"], "succeeded")
        self.assertEqual(response.data["externalId"], "camp-1")

    @patch("projects.ads_oauth.create_boost", return_value={"externalId": "tt-1"})
    def test_tiktok_boost_201(self, _mock_boost) -> None:
        from projects.models import AdAccount

        AdAccount.objects.create(project=self.project, provider="tiktok", connected=True, external_id="adv_1")
        url = reverse("project_ads_boost", kwargs={"project_id": self.project.id})
        response = self.client.post(
            url,
            {
                "provider": "tiktok",
                "kind": "video",
                "sourceUrl": "https://cdn.example/v.mp4",
                "placements": ["tiktok"],
                "budget": "15",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["externalId"], "tt-1")

    @patch("projects.ads_oauth.create_boost", return_value={"externalId": "snap-1"})
    def test_snap_boost_201(self, _mock_boost) -> None:
        from projects.models import AdAccount

        AdAccount.objects.create(project=self.project, provider="snap", connected=True, external_id="snap_1")
        url = reverse("project_ads_boost", kwargs={"project_id": self.project.id})
        response = self.client.post(
            url,
            {
                "provider": "snap",
                "kind": "image",
                "sourceUrl": "https://cdn.example/a.png",
                "placements": ["snapchat"],
                "budget": "20",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_list_ad_accounts(self) -> None:
        from projects.models import AdAccount

        AdAccount.objects.create(project=self.project, provider="meta", connected=True, display_name="Acme Ads")
        url = reverse("project_ads_list", kwargs={"project_id": self.project.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["provider"], "meta")
        from projects.models import AdAccount

        AdAccount.objects.create(project=self.project, provider="tiktok", connected=True)
        url = reverse("project_ads_boost", kwargs={"project_id": self.project.id})
        response = self.client.post(
            url,
            {
                "provider": "tiktok",
                "kind": "image",
                "sourceUrl": "https://cdn.example/a.png",
                "placements": ["tiktok"],
                "budget": "10",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("projects.ads_oauth.MetaAdsProvider.fetch_profile")
    @patch("projects.ads_oauth.MetaAdsProvider.exchange_code")
    def test_ads_callback_creates_account(self, mock_exchange, mock_profile) -> None:
        from projects.ads_views import ADS_STATE_SALT
        from projects.models import AdAccount

        mock_exchange.return_value = {"access_token": "ads-tok", "expires_in": 3600}
        mock_profile.return_value = {
            "externalId": "123456",
            "displayName": "Meta Ads",
            "handle": "123456",
        }
        state = signing.dumps(
            {
                "projectId": str(self.project.id),
                "provider": "meta",
                "userId": str(self.user.id),
                "nonce": "n",
            },
            salt=ADS_STATE_SALT,
        )
        self.client.force_authenticate(user=None)
        url = reverse("ads_callback", kwargs={"provider": "meta"})
        response = self.client.get(url, {"code": "auth-code", "state": state})
        self.assertEqual(response.status_code, status.HTTP_302_FOUND)
        self.assertEqual(response["Location"], "http://localhost:5173/social?adsConnected=meta")
        account = AdAccount.objects.get(project=self.project, provider="meta")
        self.assertTrue(account.connected)
        self.assertEqual(account.external_id, "123456")

    @override_settings(
        GOOGLE_OAUTH_CLIENT_ID="google-client",
        GOOGLE_ADS_OAUTH_REDIRECT_URI="http://testserver/api/ads/callback/google",
    )
    def test_google_connect_url(self) -> None:
        url = reverse("project_ads_connect_url", kwargs={"project_id": self.project.id, "provider": "google"})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("accounts.google.com", response.data["authUrl"])
        self.assertIn("adwords", response.data["authUrl"])
        self.assertNotIn("youtube.upload", response.data["authUrl"])

    def test_google_boost_requires_youtube_channel(self) -> None:
        from projects.models import AdAccount

        AdAccount.objects.create(project=self.project, provider="google", connected=True, external_id="123")
        url = reverse("project_ads_boost", kwargs={"project_id": self.project.id})
        response = self.client.post(
            url,
            {
                "provider": "google",
                "kind": "video",
                "sourceUrl": "https://cdn.example/v.mp4",
                "placements": ["youtube"],
                "budget": "10",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("YouTube", response.data["message"])

    @patch("projects.ads_oauth.create_boost", return_value={"externalId": "yt-ad-1"})
    def test_google_boost_201(self, _mock_boost) -> None:
        from projects.models import AdAccount

        SocialAccount.objects.create(project=self.project, platform="youtube", connected=True)
        AdAccount.objects.create(project=self.project, provider="google", connected=True, external_id="123")
        url = reverse("project_ads_boost", kwargs={"project_id": self.project.id})
        response = self.client.post(
            url,
            {
                "provider": "google",
                "kind": "video",
                "sourceUrl": "https://cdn.example/v.mp4",
                "placements": ["youtube"],
                "budget": "20",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["externalId"], "yt-ad-1")
