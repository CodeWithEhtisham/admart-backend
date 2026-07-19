from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from content.fal_client import FalSubmission
from content.mapping import build_fal_input
from content.models import ImageJob
from projects.models import Project
from users.models import User


def _submission(request_id: str = "fal-req-1") -> FalSubmission:
    return FalSubmission(
        request_id=request_id,
        status_url=f"https://queue.fal.run/fal-ai/flux/requests/{request_id}/status",
        response_url=f"https://queue.fal.run/fal-ai/flux/requests/{request_id}",
    )


class UrlResolveTests(APITestCase):
    def test_rewrites_localhost_media_to_data_uri(self):
        from django.conf import settings
        from pathlib import Path

        from content.url_resolve import resolve_url_for_fal

        rel = "projects/test/uploads/x.png"
        abs_path = Path(settings.MEDIA_ROOT) / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        out = resolve_url_for_fal(f"http://localhost:8000/media/{rel}")
        self.assertTrue(out.startswith("data:image/png;base64,"))

    def test_keeps_public_https(self):
        from content.url_resolve import resolve_url_for_fal

        url = "https://cdn.example.com/a.png"
        self.assertEqual(resolve_url_for_fal(url), url)


class MappingTests(APITestCase):
    def test_flux_aspect_maps_to_image_size(self):
        out = build_fal_input(
            "textToImage",
            "fal-ai/flux/dev",
            {"prompt": "a cat", "aspectRatio": "1:1", "numImages": 1},
        )
        self.assertEqual(out["prompt"], "a cat")
        self.assertEqual(out["image_size"], "square_hd")
        self.assertTrue(out["enable_safety_checker"])

    def test_nano_uses_aspect_ratio(self):
        out = build_fal_input(
            "textToImage",
            "fal-ai/nano-banana-2",
            {"prompt": "a dog", "aspectRatio": "16:9", "resolution": "1K"},
        )
        self.assertEqual(out["aspect_ratio"], "16:9")
        self.assertEqual(out["resolution"], "1K")
        self.assertNotIn("image_size", out)

    def test_rembg_singular_url(self):
        out = build_fal_input(
            "removeBackground",
            "fal-ai/birefnet",
            {"imageUrls": ["https://cdn.example.com/a.png"], "rembgModel": "light"},
        )
        self.assertEqual(out["image_url"], "https://cdn.example.com/a.png")
        self.assertEqual(out["model"], "General Use (Light)")

    def test_gpt_image_edit_mapping(self):
        out = build_fal_input(
            "edit",
            "openai/gpt-image-2/edit",
            {
                "prompt": "make it black",
                "imageUrls": ["https://cdn.example.com/a.png"],
                "aspectRatio": "auto",
                "quality": "high",
            },
        )
        self.assertEqual(out["prompt"], "make it black")
        self.assertEqual(out["image_urls"], ["https://cdn.example.com/a.png"])
        self.assertEqual(out["image_size"], "auto")
        self.assertEqual(out["quality"], "high")


@override_settings(FAL_KEY="test-fal-key", MEDIA_ROOT="/tmp/admart-test-media")
class ImageJobApiTests(APITestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="img@example.com",
            password="pass12345",
            credits_total=100,
            credits_remaining=100,
            credits_used=0,
        )
        self.project = Project.objects.create(owner=self.user, name="Ads")
        self.client.force_authenticate(user=self.user)
        self.jobs_url = f"/api/projects/{self.project.id}/images/jobs"

    @patch("content.views.fal_client.submit", return_value=_submission("fal-req-1"))
    def test_create_text_to_image_job(self, mock_submit):
        response = self.client.post(
            self.jobs_url,
            {
                "capability": "textToImage",
                "prompt": "Product shot on marble",
                "aspectRatio": "1:1",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["status"], "queued")
        self.assertEqual(response.data["model"], "fal-ai/flux/dev")
        self.assertEqual(response.data["images"], [])
        job = ImageJob.objects.get(id=response.data["id"])
        self.assertEqual(job.fal_request_id, "fal-req-1")
        self.assertIn("/fal-ai/flux/requests/", job.fal_status_url)
        mock_submit.assert_called_once()
        args = mock_submit.call_args[0]
        self.assertEqual(args[0], "fal-ai/flux/dev")
        self.assertEqual(args[1]["prompt"], "Product shot on marble")
        self.user.refresh_from_db()
        self.assertEqual(self.user.credits_remaining, 99)

    def test_create_rejects_empty_prompt(self):
        response = self.client.post(
            self.jobs_url,
            {"capability": "textToImage", "prompt": "  "},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data.get("field"), "prompt")

    def test_create_rejects_unknown_model(self):
        response = self.client.post(
            self.jobs_url,
            {
                "capability": "textToImage",
                "prompt": "hi",
                "model": "fal-ai/not-a-real-model",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_insufficient_credits(self):
        self.user.credits_remaining = 0
        self.user.save(update_fields=["credits_remaining"])
        response = self.client.post(
            self.jobs_url,
            {"capability": "textToImage", "prompt": "hi"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_402_PAYMENT_REQUIRED)
        self.assertEqual(response.data["code"], "INSUFFICIENT_CREDITS")
        self.assertEqual(response.data["creditsRemaining"], 0)
        self.assertIn("creditsTotal", response.data)

    @patch("content.views.fal_client.submit", return_value=_submission("fal-req-bal"))
    def test_create_includes_credits_remaining(self, _mock):
        self.user.credits_remaining = 10
        self.user.save(update_fields=["credits_remaining"])
        response = self.client.post(
            self.jobs_url,
            {"capability": "textToImage", "prompt": "balance check"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["creditsRemaining"], 9)

    @patch("content.views.fal_client.submit", return_value=_submission("fal-req-2"))
    def test_edit_requires_image(self, _mock):
        response = self.client.post(
            self.jobs_url,
            {"capability": "edit", "prompt": "make blue"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.post(
            self.jobs_url,
            {
                "capability": "edit",
                "prompt": "make blue",
                "imageUrls": ["https://cdn.example.com/x.png"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)

    @patch("content.jobs.fal_client.result")
    @patch("content.jobs.fal_client.status")
    @patch("content.jobs.persist_remote_image")
    def test_poll_completes_job(self, mock_persist, mock_status, mock_result):
        job = ImageJob.objects.create(
            project=self.project,
            user=self.user,
            capability="textToImage",
            model="fal-ai/flux/dev",
            status="queued",
            prompt="hi",
            fal_request_id="fal-req-3",
            fal_status_url="https://queue.fal.run/fal-ai/flux/requests/fal-req-3/status",
            fal_response_url="https://queue.fal.run/fal-ai/flux/requests/fal-req-3",
            credits_reserved=1,
        )
        mock_status.return_value = {"status": "COMPLETED"}
        mock_result.return_value = {
            "images": [{"url": "https://fal.media/out.png", "width": 1024, "height": 1024}],
            "seed": 42,
        }
        mock_persist.return_value = {
            "url": "http://testserver/media/projects/x/out-0.png",
            "contentType": "image/png",
            "fileName": "out-0.png",
            "width": 1024,
            "height": 1024,
        }
        response = self.client.get(f"{self.jobs_url}/{job.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "succeeded")
        self.assertEqual(len(response.data["images"]), 1)
        self.assertEqual(response.data["seed"], 42)

    def test_upload_image(self):
        url = f"/api/projects/{self.project.id}/images/uploads"
        png = SimpleUploadedFile("a.png", b"\x89PNG\r\n\x1a\nfake", content_type="image/png")
        response = self.client.post(url, {"file": png}, format="multipart")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("url", response.data)
        self.assertEqual(response.data["contentType"], "image/png")

    def test_model_catalog(self):
        response = self.client.get("/api/images/models")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("textToImage", response.data)
        self.assertTrue(any(m["default"] for m in response.data["textToImage"]))
        edit_ids = {m["id"] for m in response.data["edit"]}
        self.assertIn("openai/gpt-image-2/edit", edit_ids)

    @patch("content.views.fal_client.submit", return_value=_submission("fal-req-gpt"))
    def test_gpt_image_edit_allowed(self, mock_submit):
        response = self.client.post(
            self.jobs_url,
            {
                "capability": "edit",
                "model": "openai/gpt-image-2/edit",
                "prompt": "make it black",
                "imageUrls": ["https://cdn.example.com/a.png"],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["model"], "openai/gpt-image-2/edit")
        self.assertEqual(mock_submit.call_args[0][0], "openai/gpt-image-2/edit")

    def test_other_users_project_404(self):
        other = User.objects.create_user(email="other@example.com", password="pass12345")
        other_project = Project.objects.create(owner=other, name="Other")
        response = self.client.post(
            f"/api/projects/{other_project.id}/images/jobs",
            {"capability": "textToImage", "prompt": "nope"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
