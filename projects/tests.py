from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from projects.models import Project, SocialAccount

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
