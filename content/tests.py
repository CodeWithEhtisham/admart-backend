from decimal import Decimal
from unittest.mock import Mock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from content.fal_client import FalSubmission
from content.mapping import build_fal_input
from content.models import ImageJob, LibraryAsset, Template, TemplateUseEvent
from content.video_catalog import VIDEO_ALLOW_LISTS
from content.video_mapping import build_video_fal_input
from projects.models import Project
from users.models import User


def _submission(request_id: str = "fal-req-1") -> FalSubmission:
    return FalSubmission(
        request_id=request_id,
        status_url=f"https://queue.fal.run/fal-ai/flux/requests/{request_id}/status",
        response_url=f"https://queue.fal.run/fal-ai/flux/requests/{request_id}",
    )


def _json_response(payload: dict, status_code: int = 200) -> Mock:
    response = Mock()
    response.status_code = status_code
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


class PromptEnhancerApiTests(APITestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="prompt@example.com",
            password="pass12345",
        )
        self.client.force_authenticate(user=self.user)
        self.url = "/api/prompts/enhance"

    @override_settings(GEMINI_API_KEY="test-gemini-key", PROMPT_ENHANCER_MODEL="gemini-test")
    @patch("content.prompt_enhancer.requests.post")
    def test_enhance_prompt_uses_gemini_json(self, mock_post):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": (
                                    '{"enhancedPrompt":"Professional fast-food ad with a '
                                    'hero burger, crispy fries, chilled drink, studio lighting, '
                                    'clean composition, readable offer space, high detail.",'
                                    '"negativePrompt":"blurry, low quality, unreadable text"}'
                                )
                            }
                        ]
                    }
                }
            ]
        }
        mock_post.return_value = mock_response

        response = self.client.post(
            self.url,
            {
                "kind": "image",
                "prompt": "burger fries cold drink deal 999",
                "context": {"aspectRatio": "1:1", "unknown": "ignored"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("hero burger", response.data["enhancedPrompt"])
        self.assertEqual(response.data["negativePrompt"], "blurry, low quality, unreadable text")
        payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertNotIn("unknown", payload["contents"][0]["parts"][0]["text"])

    @override_settings(GEMINI_API_KEY="")
    def test_enhance_prompt_falls_back_without_key(self):
        response = self.client.post(
            self.url,
            {"kind": "video", "prompt": "burger fries cold drink deal 999"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("Professional social media video", response.data["enhancedPrompt"])
        self.assertIn("motion", response.data["negativePrompt"])

    def test_enhance_prompt_rejects_empty_prompt(self):
        response = self.client.post(self.url, {"kind": "image", "prompt": ""}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["field"], "prompt")



class TemplateApiTests(APITestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="template-api@example.com",
            password="pass12345",
        )
        self.image_template = Template.objects.create(
            title="Burger Deal Poster",
            category="ad",
            format="1:1 image",
            is_video=False,
            preview_url="/template-media/burger-deal.png",
            uses_count=4,
            uses_last_7d=2,
            template_config={
                "kind": "image",
                "capability": "textToImage",
                "model": "fal-ai/nano-banana-2",
                "prompt": "Create a poster for [RESTAURANT_NAME]",
                "settings": {"aspectRatio": "1:1", "numImages": 1},
            },
        )
        self.video_template = Template.objects.create(
            title="Launch Reel",
            category="reel",
            format="9:16 video",
            is_video=True,
            uses_count=10,
            uses_last_7d=6,
            template_config={
                "kind": "video",
                "capability": "textToVideo",
                "model": "bytedance/seedance-2.0/text-to-video",
                "prompt": "Create a launch reel",
                "settings": {"duration": "8", "aspectRatio": "9:16"},
            },
        )

    def test_template_list_is_public_and_filters_server_side(self):
        response = self.client.get(
            "/api/templates",
            {"category": "ad", "search": "burger", "sort": "trending"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 1)
        item = response.data["items"][0]
        self.assertEqual(item["id"], str(self.image_template.id))
        self.assertEqual(item["category"], "ad")
        self.assertEqual(item["isVideo"], False)
        self.assertIn("estimatedCredits", item)

    def test_template_list_sorts_trending(self):
        response = self.client.get("/api/templates", {"sort": "trending"})

        ids = [item["id"] for item in response.data["items"]]
        self.assertEqual(ids[:2], [str(self.video_template.id), str(self.image_template.id)])
        self.assertTrue(response.data["items"][0]["trending"])

    def test_template_detail_is_public(self):
        response = self.client.get(f"/api/templates/{self.image_template.id}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["title"], "Burger Deal Poster")
        self.assertEqual(response.data["templateConfig"]["prompt"], "Create a poster for [RESTAURANT_NAME]")

    def test_template_use_requires_auth_and_increments_usage(self):
        url = f"/api/templates/{self.image_template.id}/use"
        unauthenticated = self.client.post(url, {}, format="json")
        self.assertEqual(unauthenticated.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_authenticate(user=self.user)
        response = self.client.post(url, {}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["template"]["usesCount"], 5)
        self.assertEqual(response.data["template"]["usesLast7d"], 3)
        self.assertEqual(response.data["templateConfig"]["kind"], "image")
        self.assertEqual(TemplateUseEvent.objects.filter(template=self.image_template, user=self.user).count(), 1)


class PricingFormulaTests(APITestCase):
    @override_settings(FAL_KEY="")
    def test_admart_markup_curve_examples(self):
        from content import pricing

        pricing._CACHE["prices"] = None
        pricing._CACHE["expires_at"] = 0

        nano = pricing.quote_image_job("textToImage", "fal-ai/nano-banana-2", {"numImages": 1})
        gpt = pricing.quote_image_job("textToImage", "openai/gpt-image-2", {"numImages": 1})
        veo = pricing.quote_video_job("textToVideo", "fal-ai/veo3.1", {"duration": "8s"})

        self.assertEqual(nano["fal_cost_decimal"], Decimal("0.0800"))
        self.assertEqual(nano["credits_decimal"], Decimal("0.1689"))
        self.assertEqual(gpt["fal_cost_decimal"], Decimal("1.0000"))
        self.assertEqual(gpt["credits_decimal"], Decimal("1.6000"))
        self.assertEqual(veo["fal_cost_decimal"], Decimal("3.2000"))
        self.assertEqual(veo["credits_decimal"], Decimal("4.1143"))


class FalModelSearchApiTests(APITestCase):
    def setUp(self) -> None:
        from content import fal_models, pricing

        fal_models._CACHE.clear()
        pricing._CACHE["prices"] = None
        pricing._CACHE["expires_at"] = 0
        self.user = User.objects.create_user(
            email="falmodels@example.com",
            password="pass12345",
        )
        self.client.force_authenticate(user=self.user)
        self.url = "/api/fal/models"

    @override_settings(FAL_KEY="test-fal-key")
    @patch("content.fal_models.get_fal_prices")
    @patch("content.fal_models.requests.get")
    def test_search_fal_models_normalizes_supported_and_new_models(self, mock_models, mock_prices):
        mock_models.return_value = _json_response(
            {
                "models": [
                    {
                        "endpoint_id": "fal-ai/flux/dev",
                        "metadata": {
                            "display_name": "FLUX.1 Dev",
                            "category": "text-to-image",
                            "status": "active",
                        },
                    },
                    {
                        "endpoint_id": "fal-ai/new-image-model",
                        "metadata": {
                            "display_name": "New Image Model",
                            "category": "text-to-image",
                            "status": "active",
                        },
                    },
                ],
                "next_cursor": None,
                "has_more": False,
            }
        )
        mock_prices.return_value = {
            "fal-ai/flux/dev": {
                "unit_price": "0.025",
                "unit": "megapixels",
                "currency": "USD",
            },
            "fal-ai/new-image-model": {
                "unit_price": "0.03",
                "unit": "images",
                "currency": "USD",
            },
        }

        response = self.client.get(self.url, {"capability": "textToImage", "limit": 10})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["items"]), 2)
        enabled = response.data["items"][0]
        discovered = response.data["items"][1]
        self.assertTrue(enabled["enabled"])
        self.assertIn("textToImage", enabled["supportedCapabilities"])
        self.assertFalse(discovered["enabled"])
        self.assertEqual(discovered["pricing"]["unitPrice"], "0.03")
        self.assertEqual(mock_models.call_args.kwargs["params"]["category"], "text-to-image")

    @override_settings(FAL_KEY="test-fal-key")
    @patch("content.fal_models.get_fal_prices")
    @patch("content.fal_models.requests.get")
    def test_image_catalog_can_include_discovery_report(self, mock_models, mock_prices):
        mock_models.return_value = _json_response(
            {
                "models": [
                    {
                        "endpoint_id": "fal-ai/new-image-model",
                        "metadata": {
                            "display_name": "New Image Model",
                            "category": "text-to-image",
                            "status": "active",
                        },
                    }
                ],
                "next_cursor": None,
                "has_more": False,
            }
        )
        mock_prices.return_value = {}

        response = self.client.get("/api/images/models", {"discover": "1"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("_fal", response.data)
        self.assertIn("textToImage", response.data["_fal"]["discoverable"])


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

    def test_wan_image_edit_mapping(self):
        out = build_fal_input(
            "multiEdit",
            "wan/v2.6/image-to-image",
            {
                "prompt": "combine the product and background",
                "imageUrls": [
                    "https://cdn.example.com/product.png",
                    "https://cdn.example.com/bg.png",
                ],
                "aspectRatio": "16:9",
                "numImages": 2,
                "negativePrompt": "blur",
                "expandPrompt": False,
            },
        )
        self.assertEqual(out["prompt"], "combine the product and background")
        self.assertEqual(
            out["image_urls"],
            ["https://cdn.example.com/product.png", "https://cdn.example.com/bg.png"],
        )
        self.assertEqual(out["image_size"], "landscape_16_9")
        self.assertEqual(out["num_images"], 2)
        self.assertEqual(out["negative_prompt"], "blur")
        self.assertFalse(out["enable_prompt_expansion"])

    def test_wan_video_catalog_uses_callable_ids(self):
        self.assertIn("wan/v2.6/text-to-video", VIDEO_ALLOW_LISTS["textToVideo"])
        self.assertIn("wan/v2.6/image-to-video", VIDEO_ALLOW_LISTS["imageToVideo"])
        self.assertNotIn("fal-ai/wan/v2.6/text-to-video", VIDEO_ALLOW_LISTS["textToVideo"])
        self.assertNotIn("fal-ai/wan/v2.6/image-to-video", VIDEO_ALLOW_LISTS["imageToVideo"])

        out = build_video_fal_input(
            "imageToVideo",
            "wan/v2.6/image-to-video",
            {
                "prompt": "animate the burger",
                "startImageUrl": "https://cdn.example.com/burger.png",
                "duration": "15",
                "resolution": "1080p",
                "negativePrompt": "flicker",
            },
        )
        self.assertEqual(out["image_url"], "https://cdn.example.com/burger.png")
        self.assertEqual(out["duration"], "15")
        self.assertEqual(out["resolution"], "1080p")
        self.assertEqual(out["negative_prompt"], "flicker")


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
        self.assertEqual(self.user.credits_remaining, Decimal("99.9457"))
        asset = LibraryAsset.objects.get(image_job=job)
        self.assertEqual(asset.status, "generating")
        self.assertEqual(asset.media_type, "image")

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
        self.assertEqual(response.data["creditsRemaining"], Decimal("9.9457"))

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
        asset = LibraryAsset.objects.get(image_job=job, source_index=0)
        self.assertEqual(asset.status, "ready")
        self.assertEqual(asset.source_url, "http://testserver/media/projects/x/out-0.png")

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


@override_settings(FAL_KEY="test-fal-key", MEDIA_ROOT="/tmp/admart-test-media")
class LibraryApiTests(APITestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(
            email="lib@example.com",
            password="pass12345",
            credits_total=100,
            credits_remaining=100,
            credits_used=0,
        )
        self.project = Project.objects.create(owner=self.user, name="Lib")
        self.client.force_authenticate(user=self.user)
        self.library_url = f"/api/projects/{self.project.id}/library"

    def test_empty_library(self):
        response = self.client.get(self.library_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["items"], [])
        self.assertIsNone(response.data["nextCursor"])

    def test_list_filters_media_type_and_sorts_newest_first(self):
        older = LibraryAsset.objects.create(
            project=self.project,
            user=self.user,
            media_type="image",
            title="old",
            status="ready",
            source_url="https://cdn.example.com/old.png",
            thumbnail_url="https://cdn.example.com/old.png",
        )
        newer = LibraryAsset.objects.create(
            project=self.project,
            user=self.user,
            media_type="video",
            title="new",
            status="ready",
            source_url="https://cdn.example.com/new.mp4",
            thumbnail_url="https://cdn.example.com/new.jpg",
            duration_seconds=12,
        )
        LibraryAsset.objects.filter(id=older.id).update(created_at=older.created_at.replace(year=2020))

        response = self.client.get(self.library_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = [item["id"] for item in response.data["items"]]
        self.assertEqual(ids, [str(newer.id), str(older.id)])

        images = self.client.get(f"{self.library_url}?mediaType=image")
        self.assertEqual(len(images.data["items"]), 1)
        self.assertEqual(images.data["items"][0]["mediaType"], "image")

        videos = self.client.get(f"{self.library_url}?mediaType=video")
        self.assertEqual(len(videos.data["items"]), 1)
        self.assertEqual(videos.data["items"][0]["durationSeconds"], 12)

    def test_soft_delete(self):
        asset = LibraryAsset.objects.create(
            project=self.project,
            user=self.user,
            media_type="image",
            title="bye",
            status="ready",
            source_url="https://cdn.example.com/bye.png",
        )
        response = self.client.delete(f"{self.library_url}/{asset.id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        asset.refresh_from_db()
        self.assertIsNotNone(asset.deleted_at)
        listed = self.client.get(self.library_url)
        self.assertEqual(listed.data["items"], [])

    def test_other_users_library_404(self):
        other = User.objects.create_user(email="lib-other@example.com", password="pass12345")
        other_project = Project.objects.create(owner=other, name="Other")
        response = self.client.get(f"/api/projects/{other_project.id}/library")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
