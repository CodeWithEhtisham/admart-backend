import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from blog.models import BlogPost

User = get_user_model()


class BlogTests(APITestCase):
    def setUp(self) -> None:
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        media = override_settings(MEDIA_ROOT=self.media)
        media.enable()
        self.addCleanup(media.disable)
        self.admin = User.objects.create_user(email="staff@example.com", password="Password123!", is_staff=True)

    def _create(self, **data):
        self.client.force_authenticate(self.admin)
        return self.client.post(reverse("admin_blog_posts"), data, format="json")

    def test_only_published_posts_are_public(self) -> None:
        self.assertEqual(self._create(title="Make Shorts with AI!", body="## Step one").status_code, 201)
        self._create(title="Cross-posting", status="published", summary="One video, three platforms.")
        self.client.force_authenticate(None)
        listed = self.client.get(reverse("blog_list")).data
        self.assertEqual([p["slug"] for p in listed], ["cross-posting"])
        self.assertNotIn("body", listed[0])
        self.assertIsNotNone(listed[0]["publishedAt"])
        self.assertEqual(self.client.get(reverse("blog_detail", args=["make-shorts-with-ai"])).status_code, 404)

        draft = BlogPost.objects.get(slug="make-shorts-with-ai")
        self.client.force_authenticate(self.admin)
        self.client.patch(reverse("admin_blog_post", args=[draft.id]), {"status": "published"}, format="json")
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(reverse("blog_detail", args=["make-shorts-with-ai"])).data["body"], "## Step one")

    def test_writing_needs_staff_and_valid_fields(self) -> None:
        user = User.objects.create_user(email="user@example.com", password="Password123!")
        self.client.force_authenticate(user)
        self.assertEqual(self.client.post(reverse("admin_blog_posts"), {"title": "x"}, format="json").status_code, 403)
        self.assertEqual(self._create(title="").status_code, 400)
        self._create(title="Same name")
        self.assertIn("already", self._create(title="Other", slug="same-name").data["message"])
        self.assertEqual(self._create(title="Bad cover", cover="../../etc/passwd").status_code, 400)

    def test_image_upload(self) -> None:
        self.client.force_authenticate(self.admin)
        url = reverse("admin_blog_images")
        bad = SimpleUploadedFile("x.svg", b"<svg/>", content_type="image/svg+xml")
        self.assertEqual(self.client.post(url, {"file": bad}).status_code, 400)
        png = SimpleUploadedFile("x.png", b"\x89PNG\r\n\x1a\n" + b"0" * 10, content_type="image/png")
        response = self.client.post(url, {"file": png})
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["path"].startswith("blog/"))
        created = self._create(title="With cover", cover=response.data["path"]).data
        self.assertTrue(created["coverUrl"].endswith(response.data["path"]))
