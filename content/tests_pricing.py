"""Credit pricing: live fal prices in batches, the persisted snapshot, the price guard,
option-aware quotes (resolution, audio, duration, quality) and the no-loss margin floor.

Expected USD figures below are copied from each model's fal.ai page (2026-10-20), so they
check the pricing code against fal's published prices, not against itself.
"""

from __future__ import annotations

import itertools
import threading
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import Mock, patch

import requests
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from content import pricing
from content.catalog import MODEL_CATALOG
from content.models import FalPriceSnapshot
from content.video_catalog import VIDEO_MODEL_CATALOG


def _reset_cache() -> None:
    pricing._CACHE["prices"] = None
    pricing._CACHE["expires_at"] = 0


def _response(rows: list[dict], status_code: int = 200) -> Mock:
    response = Mock(status_code=status_code, text="")
    response.json.return_value = {"prices": rows}
    if status_code >= 400:
        response.text = '{"error":{"type":"validation_error"}}'
        response.raise_for_status.side_effect = requests.HTTPError(f"{status_code} error")
    else:
        response.raise_for_status.return_value = None
    return response


def _row(endpoint_id: str, unit_price: str, unit: str) -> dict:
    return {"endpoint_id": endpoint_id, "unit_price": unit_price, "unit": unit, "currency": "USD"}


def _fal_cost(kind: str, capability: str, model: str, data: dict) -> Decimal:
    quote = (pricing.quote_image_job if kind == "image" else pricing.quote_video_job)(capability, model, data)
    return quote["fal_cost_decimal"]


@override_settings(FAL_KEY="test-key")
class FetchLivePricesTests(SimpleTestCase):
    def test_ids_are_sent_in_batches_of_at_most_40(self) -> None:
        ids = [f"vendor/model-{i}" for i in range(61)]
        with patch("content.pricing.requests.get", return_value=_response([])) as get:
            pricing.fetch_live_prices(ids)
        self.assertEqual(get.call_count, 2)
        sizes = [len(call.kwargs["params"]) for call in get.call_args_list]
        self.assertEqual(sizes, [40, 21])
        self.assertTrue(all(call.kwargs["timeout"] <= 10 for call in get.call_args_list))

    def test_a_failed_batch_is_logged_and_only_its_models_are_missing(self) -> None:
        ids = [f"vendor/model-{i}" for i in range(45)]
        ok = _response([_row("vendor/model-44", "0.2", "seconds")])
        with patch("content.pricing.requests.get", side_effect=[_response([], 400), ok]), \
                self.assertLogs("content.pricing", "WARNING") as logs:
            prices = pricing.fetch_live_prices(ids)
        self.assertEqual(set(prices), {"vendor/model-44"})
        self.assertIn("400", "\n".join(logs.output))
        self.assertIn("validation_error", "\n".join(logs.output))

    def test_network_errors_are_logged_not_swallowed(self) -> None:
        with patch("content.pricing.requests.get", side_effect=requests.ConnectionError("dns")), \
                self.assertLogs("content.pricing", "WARNING") as logs:
            self.assertEqual(pricing.fetch_live_prices(["fal-ai/veo3.1"]), {})
        self.assertIn("dns", "\n".join(logs.output))

    @override_settings(FAL_KEY="")
    def test_no_key_means_no_request(self) -> None:
        with patch("content.pricing.requests.get") as get:
            self.assertEqual(pricing.fetch_live_prices(["fal-ai/veo3.1"]), {})
        get.assert_not_called()


class PriceGuardTests(SimpleTestCase):
    """resolve_price: overrides, placeholders, unit changes and implausible jumps."""

    def test_plausible_live_price_is_used(self) -> None:
        row = pricing.resolve_price("fal-ai/veo3.1", {"unit_price": "0.5", "unit": "seconds", "currency": "USD"})
        self.assertEqual(Decimal(row["unit_price"]), Decimal("0.5"))

    def test_placeholder_falls_back_and_is_logged(self) -> None:
        with self.assertLogs("content.pricing", "WARNING"):
            row = pricing.resolve_price("fal-ai/nano-banana-2", {"unit_price": "1", "unit": "units"})
        self.assertEqual(row, pricing.FALLBACK_PRICES["fal-ai/nano-banana-2"])

    def test_a_much_lower_live_price_never_undercuts_the_fallback(self) -> None:
        with self.assertLogs("content.pricing", "WARNING"):
            row = pricing.resolve_price("fal-ai/veo3.1", {"unit_price": "0.01", "unit": "seconds"})
        self.assertEqual(Decimal(row["unit_price"]), Decimal(pricing.FALLBACK_PRICES["fal-ai/veo3.1"]["unit_price"]))

    def test_a_much_higher_live_price_is_kept_because_it_is_the_safer_one(self) -> None:
        with self.assertLogs("content.pricing", "WARNING"):
            row = pricing.resolve_price("fal-ai/veo3.1", {"unit_price": "4", "unit": "seconds"})
        self.assertEqual(Decimal(row["unit_price"]), Decimal("4"))

    def test_a_changed_unit_falls_back(self) -> None:
        with self.assertLogs("content.pricing", "WARNING"):
            row = pricing.resolve_price("fal-ai/veo3.1", {"unit_price": "0.4", "unit": "videos"})
        self.assertEqual(row["unit"], "seconds")

    def test_overrides_win_over_placeholders(self) -> None:
        for model in ("openai/gpt-image-2", "openai/gpt-image-2.5/flare/text-to-image", "google/nano-banana-2.1"):
            row = pricing.resolve_price(model, {"unit_price": "1", "unit": "units"})
            self.assertEqual(row, pricing.PRICE_OVERRIDES[model])
            self.assertLess(Decimal(row["unit_price"]), Decimal("0.5"))

    def test_every_catalog_model_has_a_known_price(self) -> None:
        for model in pricing.all_priced_endpoint_ids():
            row = pricing.resolve_price(model, None)
            self.assertIsNotNone(row, model)
            self.assertGreater(Decimal(row["unit_price"]), 0, model)
            self.assertFalse(pricing.is_placeholder(row), model)


@override_settings(FAL_KEY="test-key")
class PriceSnapshotTests(TestCase):
    def setUp(self) -> None:
        _reset_cache()
        self.addCleanup(_reset_cache)

    def _snapshot(self, model: str, price: str, unit: str, age: timedelta = timedelta()) -> None:
        FalPriceSnapshot.objects.update_or_create(
            endpoint_id=model,
            defaults={"unit_price": Decimal(price), "unit": unit, "fetched_at": timezone.now() - age},
        )

    def test_refresh_stores_live_prices_and_quotes_use_them_without_calling_fal(self) -> None:
        live = [_row("fal-ai/veo3.1", "0.45", "seconds")]
        with patch("content.pricing.requests.get", return_value=_response(live)):
            summary = pricing.refresh_price_snapshot()
        self.assertEqual(summary["fetched"], 1)
        self.assertEqual(FalPriceSnapshot.objects.get(endpoint_id="fal-ai/veo3.1").unit_price, Decimal("0.45"))

        _reset_cache()
        with patch("content.pricing.requests.get") as get:
            quote = pricing.quote_video_job("textToVideo", "fal-ai/veo3.1", {"duration": "8s", "resolution": "1080p"})
        get.assert_not_called()
        self.assertEqual(quote["fal_cost_decimal"], Decimal("3.6000"))  # 0.45/s x 8 s, with audio

    def test_refresh_logs_models_whose_price_moved_more_than_20_percent(self) -> None:
        self._snapshot("fal-ai/veo3.1", "0.40", "seconds")
        self._snapshot("fal-ai/veo3.1/fast", "0.15", "seconds")
        live = [_row("fal-ai/veo3.1", "0.50", "seconds"), _row("fal-ai/veo3.1/fast", "0.16", "seconds")]
        with patch("content.pricing.requests.get", return_value=_response(live)), \
                self.assertLogs("content.pricing", "WARNING") as logs:
            summary = pricing.refresh_price_snapshot()
        self.assertEqual([c["endpoint_id"] for c in summary["changed"]], ["fal-ai/veo3.1"])
        self.assertIn("fal-ai/veo3.1", "\n".join(logs.output))

    def test_a_failed_refresh_keeps_the_last_snapshot(self) -> None:
        self._snapshot("fal-ai/veo3.1", "0.45", "seconds", age=timedelta(days=2))
        with patch("content.pricing.requests.get", side_effect=requests.ConnectionError("down")), \
                self.assertLogs("content.pricing", "WARNING"):
            pricing.refresh_price_snapshot()
        self.assertEqual(FalPriceSnapshot.objects.get(endpoint_id="fal-ai/veo3.1").unit_price, Decimal("0.45"))
        _reset_cache()
        with patch("content.pricing._start_background_refresh"):
            self.assertEqual(pricing.get_fal_prices(["fal-ai/veo3.1"])["fal-ai/veo3.1"]["unit_price"], "0.45")

    def test_snapshot_rows_go_through_the_guard(self) -> None:
        self._snapshot("openai/gpt-image-2", "1", "units")
        with patch("content.pricing._start_background_refresh"):
            row = pricing.get_fal_prices(["openai/gpt-image-2"])["openai/gpt-image-2"]
        self.assertEqual(row, pricing.PRICE_OVERRIDES["openai/gpt-image-2"])

    def test_stale_snapshot_starts_a_background_refresh(self) -> None:
        self._snapshot("fal-ai/veo3.1", "0.40", "seconds", age=pricing.PRICES_STALE_AFTER + timedelta(minutes=1))
        with patch("content.pricing._start_background_refresh") as refresh:
            pricing.get_fal_prices(["fal-ai/veo3.1"])
        refresh.assert_called_once()

    def test_fresh_snapshot_does_not_refresh(self) -> None:
        self._snapshot("fal-ai/veo3.1", "0.40", "seconds")
        with patch("content.pricing._start_background_refresh") as refresh:
            pricing.get_fal_prices(["fal-ai/veo3.1"])
        refresh.assert_not_called()

    @override_settings(FAL_KEY="")
    def test_without_a_key_quotes_use_fallbacks_and_never_refresh(self) -> None:
        with patch("content.pricing._start_background_refresh") as refresh:
            row = pricing.get_fal_prices(["fal-ai/veo3.1"])["fal-ai/veo3.1"]
        refresh.assert_not_called()
        self.assertEqual(row, pricing.FALLBACK_PRICES["fal-ai/veo3.1"])

    def test_refresh_if_stale_only_calls_fal_when_stale(self) -> None:
        self._snapshot("fal-ai/veo3.1", "0.40", "seconds")
        with patch("content.pricing.refresh_price_snapshot") as refresh:
            pricing.refresh_prices_if_stale(max_age=timedelta(hours=6))
            refresh.assert_not_called()
            pricing.refresh_prices_if_stale(max_age=timedelta(seconds=0))
            refresh.assert_called_once()

    def test_management_command_refreshes_and_reports(self) -> None:
        live = [_row("fal-ai/veo3.1", "0.40", "seconds")]
        out = StringIO()
        with patch("content.pricing.requests.get", return_value=_response(live)):
            call_command("refresh_fal_prices", stdout=out)
        self.assertTrue(FalPriceSnapshot.objects.filter(endpoint_id="fal-ai/veo3.1").exists())
        self.assertIn("1", out.getvalue())

    def test_celery_task_and_beat_entry(self) -> None:
        from django.conf import settings

        from content.tasks import refresh_fal_prices

        entry = settings.CELERY_BEAT_SCHEDULE["fal-price-refresh"]
        self.assertEqual(entry["task"], "content.tasks.refresh_fal_prices")
        self.assertEqual(entry["schedule"], 6 * 60 * 60.0)
        with patch("content.tasks.call_command") as command:
            refresh_fal_prices()
        command.assert_called_once_with("refresh_fal_prices", verbosity=0)


class AgentWorkerRefreshTests(SimpleTestCase):
    def test_the_worker_loop_refreshes_stale_prices(self) -> None:
        class Stop(Exception):
            pass

        module = "agents.management.commands.run_agents_worker"
        with patch(f"{module}.claim_next", return_value=None), patch(f"{module}.run_due", return_value=0), \
                patch(f"{module}.beat"), patch(f"{module}.time.sleep", side_effect=Stop), \
                patch("content.fal_models.discover_if_stale"), \
                patch("content.pricing.refresh_prices_if_stale") as refresh:
            with self.assertRaises(Stop):
                call_command("run_agents_worker", stdout=StringIO())
            join_catalog_refresh()
        refresh.assert_called_once()

    def test_a_slow_refresh_does_not_keep_the_runner_offline(self) -> None:
        # After a long break both are stale and fal can take minutes; the runner must beat and work meanwhile.
        class Stop(Exception):
            pass

        release = threading.Event()
        refresh_done = threading.Event()
        seen = {}

        def slow_refresh():
            release.wait(5)
            refresh_done.set()

        def claim(**_):
            seen["refresh_done_at_claim"] = refresh_done.is_set()
            raise Stop

        module = "agents.management.commands.run_agents_worker"
        with patch(f"{module}.claim_next", side_effect=claim), patch(f"{module}.run_due", return_value=0), \
                patch(f"{module}.beat") as beat, \
                patch("content.fal_models.discover_if_stale"), \
                patch("content.pricing.refresh_prices_if_stale", side_effect=slow_refresh):
            with self.assertRaises(Stop):
                call_command("run_agents_worker", stdout=StringIO())
            beat.assert_called_once()
            release.set()
            join_catalog_refresh()
        self.assertFalse(seen["refresh_done_at_claim"])


def join_catalog_refresh() -> None:
    for thread in threading.enumerate():
        if thread.name == "fal-catalog-refresh":
            thread.join(5)


@override_settings(FAL_KEY="")
class PublishedPriceTests(TestCase):
    """Quotes must cover fal's published price for each option (resolution, audio, duration, quality)."""

    def setUp(self) -> None:
        _reset_cache()
        self.addCleanup(_reset_cache)

    def check(self, kind: str, capability: str, model: str, data: dict, published: str) -> None:
        self.assertEqual(_fal_cost(kind, capability, model, data), Decimal(published), f"{model} {data}")

    def test_nano_banana_resolution_and_surcharges(self) -> None:
        for model, cap in (("fal-ai/nano-banana-2", "textToImage"), ("fal-ai/nano-banana-2/edit", "edit")):
            for res, usd in (("0.5K", "0.06"), ("1K", "0.08"), ("2K", "0.12"), ("4K", "0.16")):
                self.check("image", cap, model, {"resolution": res}, usd)
        self.check("image", "textToImage", "fal-ai/nano-banana-2", {"numImages": 2, "resolution": "4K"}, "0.32")
        self.check("image", "textToImage", "fal-ai/nano-banana-2", {"enableWebSearch": True}, "0.095")
        self.check("image", "textToImage", "fal-ai/nano-banana-2", {"thinkingLevel": "high"}, "0.082")
        for res, usd in (("1K", "0.15"), ("2K", "0.15"), ("4K", "0.30")):
            self.check("image", "textToImage", "fal-ai/nano-banana-pro", {"resolution": res}, usd)
            self.check("image", "multiEdit", "fal-ai/nano-banana-pro/edit", {"resolution": res}, usd)
        self.check("image", "textToImage", "fal-ai/nano-banana-pro", {"enableWebSearch": True}, "0.165")

    def test_nano_banana_2_1_is_priced_from_its_token_examples(self) -> None:
        for res, usd in (("1K", "0.04"), ("2K", "0.059"), ("4K", "0.134")):
            self.check("image", "textToImage", "google/nano-banana-2.1", {"resolution": res}, usd)
        self.check("image", "edit", "google/nano-banana-2.1/edit", {"imageUrls": ["a", "b"]}, "0.044")

    def test_gpt_image_quality_and_size(self) -> None:
        for model in ("openai/gpt-image-2.5/flare/text-to-image", "openai/gpt-image-2.5/sunburst/text-to-image"):
            self.check("image", "textToImage", model, {"aspectRatio": "1:1"}, "0.0527")  # high is fal's default
            self.check("image", "textToImage", model, {"quality": "auto"}, "0.0527")
            self.check("image", "textToImage", model, {"quality": "medium"}, "0.0132")
            self.check("image", "textToImage", model, {"quality": "low"}, "0.0059")
            self.check("image", "textToImage", model, {"imageSize": {"width": 3840, "height": 2160}}, "0.1001")
        self.check("image", "textToImage", "openai/gpt-image-2", {}, "0.211")
        self.check("image", "textToImage", "openai/gpt-image-2", {"imageSize": {"width": 2560, "height": 1440}}, "0.222")
        # Edits also pay for the input images' tokens.
        self.check("image", "edit", "openai/gpt-image-2.5/flare/edit", {"imageUrls": ["a", "b"]}, "0.1327")

    def test_seedream_5_pro_by_area(self) -> None:
        model = "bytedance/seedream/v5/pro/text-to-image"
        self.check("image", "textToImage", model, {"aspectRatio": "1:1"}, "0.0675")
        self.check("image", "textToImage", model, {"imageSize": {"width": 2048, "height": 2048}}, "0.135")
        self.check("image", "textToImage", model, {}, "0.135")  # fal picks the size: assume the larger tier

    def test_flux_2_pro_processed_megapixels_and_ideogram_speed(self) -> None:
        self.check("image", "textToImage", "fal-ai/flux-2-pro", {"aspectRatio": "1:1"}, "0.03")
        self.check("image", "textToImage", "fal-ai/flux-2-pro", {"imageSize": {"width": 1920, "height": 1080}}, "0.045")
        self.check("image", "textToImage", "fal-ai/ideogram/v3", {"renderingSpeed": "TURBO"}, "0.03")
        self.check("image", "textToImage", "fal-ai/ideogram/v3", {}, "0.06")
        self.check("image", "textToImage", "fal-ai/ideogram/v3", {"renderingSpeed": "QUALITY"}, "0.09")

    def test_veo_audio_and_4k(self) -> None:
        for model, cap in (("fal-ai/veo3.1", "textToVideo"), ("fal-ai/veo3.1/image-to-video", "imageToVideo")):
            self.check("video", cap, model, {"duration": "8s", "resolution": "1080p"}, "3.2")
            self.check("video", cap, model, {"duration": "8s", "resolution": "1080p", "generateAudio": False}, "1.6")
            self.check("video", cap, model, {"duration": "8s", "resolution": "4k"}, "4.8")
            self.check("video", cap, model, {"duration": "8s", "resolution": "4k", "generateAudio": False}, "3.2")
        self.check("video", "textToVideo", "fal-ai/veo3.1/fast", {"duration": "8s", "resolution": "1080p"}, "1.2")
        self.check("video", "textToVideo", "fal-ai/veo3.1/fast",
                   {"duration": "8s", "resolution": "720p", "generateAudio": False}, "0.8")

    def test_kling_audio_is_billed_because_fal_generates_it_by_default(self) -> None:
        # Admart has no audio switch for Kling, so fal's default (generate_audio=true) always applies.
        self.check("video", "textToVideo", "fal-ai/kling-video/v3/pro/text-to-video", {"duration": "5"}, "1.68")
        self.check("video", "textToVideo", "fal-ai/kling-video/v3/pro/text-to-video",
                   {"duration": "5", "generateAudio": False}, "1.68")
        self.check("video", "textToVideo", "fal-ai/kling-video/v3/standard/text-to-video", {"duration": "5"}, "1.26")
        self.check("video", "imageToVideo", "fal-ai/kling-video/v2.6/pro/image-to-video", {"duration": "5"}, "0.7")
        self.check("video", "textToVideo", "fal-ai/kling-video/v3/pro/text-to-video", {}, "3.36")  # 10 s max

    def test_seedance_tokens_4k_and_auto_duration(self) -> None:
        t2v = "bytedance/seedance-2.0/text-to-video"
        self.check("video", "textToVideo", t2v, {"duration": "5", "resolution": "720p"}, "1.512")
        self.check("video", "textToVideo", t2v, {"duration": "5", "resolution": "4k"}, "7.776")  # $0.008/1k tokens
        self.check("video", "textToVideo", t2v, {"duration": "auto", "resolution": "720p"}, "4.536")  # 15 s
        self.check("video", "textToVideo", t2v, {"duration": "5", "resolution": "480p"}, "0.7031")  # 864x496
        s25 = "bytedance/seedance-2.5/text-to-video"
        self.check("video", "textToVideo", s25, {"duration": "6s", "resolution": "720p"}, "2.7734")
        self.check("video", "textToVideo", s25, {"duration": "auto", "resolution": "720p"}, "13.8672")  # 30 s
        # fal publishes no 4K discount for 2.5, so 4K is billed at the full token rate.
        self.check("video", "textToVideo", s25, {"duration": "4s", "resolution": "4k"}, "16.6406")

    def test_resolution_priced_video_models(self) -> None:
        self.check("video", "textToVideo", "fal-ai/pixverse/v5/text-to-video", {"duration": "5"}, "0.2")
        self.check("video", "textToVideo", "fal-ai/pixverse/v5/text-to-video", {"duration": "8"}, "0.4")
        self.check("video", "textToVideo", "alibaba/wan-3.0/text-to-video", {"duration": "5", "resolution": "720p"}, "0.5")
        self.check("video", "textToVideo", "alibaba/wan-3.0/text-to-video", {"duration": "5", "resolution": "1080p"}, "1")
        self.check("video", "textToVideo", "wan/v2.6/text-to-video", {"duration": "5", "resolution": "1080p"}, "0.75")
        self.check("video", "textToVideo", "minimax/h3-max/text-to-video", {"duration": "6"}, "0.48")  # 768p list price
        self.check("video", "textToVideo", "minimax/h3-max-turbo/text-to-video", {"duration": "10"}, "0.4")

    def test_models_added_october_2026_images(self) -> None:
        self.check("image", "textToImage", "fal-ai/flux-2", {"imageSize": "square_hd"}, "0.012")
        self.check("image", "textToImage", "fal-ai/z-image/turbo", {"aspectRatio": "1:1"}, "0.005")
        self.check("image", "textToImage", "fal-ai/flux-pro/v1.1-ultra", {"aspectRatio": "16:9"}, "0.06")
        self.check("image", "textToImage", "fal-ai/bytedance/seedream/v4.5/text-to-image", {}, "0.04")
        self.check("image", "edit", "fal-ai/bytedance/seedream/v4.5/edit", {"imageUrls": ["a"]}, "0.04")
        self.check("image", "textToImage", "xai/grok-imagine-image", {}, "0.02")
        self.check("image", "edit", "xai/grok-imagine-image/edit", {"imageUrls": ["a"]}, "0.022")
        # Flux 3 bills per megapixel and picks the size from the aspect ratio: bill 2 MP.
        self.check("image", "textToImage", "blackforestlabs/flux-3/text-to-image", {"aspectRatio": "16:9"}, "0.096")

    def test_models_added_october_2026_videos(self) -> None:
        for model, cap in (("google/gemini-omni-flash/v1.1/text-to-video", "textToVideo"),
                           ("google/gemini-omni-flash/v1.1/image-to-video", "imageToVideo")):
            self.check("video", cap, model, {"duration": "8", "resolution": "720p"}, "0.8")
            self.check("video", cap, model, {"duration": "8", "resolution": "1080p"}, "1.2")
        fast = "bytedance/seedance-2.0/fast/text-to-video"
        self.check("video", "textToVideo", fast, {"duration": "5", "resolution": "720p"}, "1.2096")
        self.check("video", "textToVideo", fast, {"duration": "auto", "resolution": "720p"}, "3.6288")  # 15 s
        self.check("video", "textToVideo", "bytedance/seedance-2.0/mini/text-to-video",
                   {"duration": "5", "resolution": "720p"}, "0.756")
        o3 = "fal-ai/kling-video/o3/pro/text-to-video"
        self.check("video", "textToVideo", o3, {"duration": "5", "generateAudio": True}, "0.7")
        self.check("video", "textToVideo", o3, {"duration": "5", "generateAudio": False}, "0.56")
        self.check("video", "textToVideo", "fal-ai/kling-video/v2.6/pro/text-to-video", {"duration": "5"}, "0.7")
        pix = "fal-ai/pixverse/v6/text-to-video"
        self.check("video", "textToVideo", pix, {"duration": "5", "resolution": "720p"}, "0.225")
        self.check("video", "textToVideo", pix, {"duration": "5", "resolution": "1080p"}, "0.45")
        h3 = "minimax/h3/text-to-video"
        self.check("video", "textToVideo", h3, {"duration": "5", "resolution": "768P"}, "0.3")
        self.check("video", "textToVideo", h3, {"duration": "5"}, "0.65")  # fal renders 2K by default
        grok = "xai/grok-imagine-video/text-to-video"
        self.check("video", "textToVideo", grok, {"duration": "6", "resolution": "720p"}, "0.42")
        self.check("video", "textToVideo", grok, {"duration": "6", "resolution": "480p"}, "0.3")
        self.check("video", "imageToVideo", "alibaba/wan-3.0/image-to-video",
                   {"duration": "5", "resolution": "1080p"}, "1")
        self.check("video", "imageToVideo", "minimax/h3-max-turbo/image-to-video", {"duration": "10"}, "0.4")


class MarginFloorTests(TestCase):
    def setUp(self) -> None:
        _reset_cache()
        self.addCleanup(_reset_cache)

    def test_cheapest_credit_is_the_pro_plan_by_default(self) -> None:
        self.assertEqual(pricing.cheapest_credit_value().quantize(Decimal("0.0001")), Decimal("0.6583"))

    def test_top_up_packs_lower_the_floor(self) -> None:
        from admin_panel.models import TopupPack

        TopupPack.objects.create(pack_id="bulk", name="Bulk", credits=Decimal("100"), price_usd=Decimal("40"),
                                 price_pkr=1, sort_order=99, is_public=True)
        self.assertEqual(pricing.cheapest_credit_value(), Decimal("0.4"))
        self.assertEqual(pricing.admart_markup_multiplier("10"), Decimal("1.1") / Decimal("0.4"))

    def test_plan_discount_percent_is_applied(self) -> None:
        from admin_panel.models import PlanDefinition

        pro = PlanDefinition.objects.get(plan_id="pro")
        pro.limits = {**pro.limits, "discount_percent": 50}
        pro.save()
        self.assertEqual(pricing.cheapest_credit_value(), Decimal("79") * Decimal("0.5") / Decimal("120"))

    def test_hidden_plans_that_sell_credits_count(self) -> None:
        from admin_panel.models import PlanDefinition

        PlanDefinition.objects.create(plan_id="legacy", name="Legacy", price_usd=Decimal("10"),
                                      monthly_credits=Decimal("50"), is_public=False, sort_order=99)
        self.assertEqual(pricing.cheapest_credit_value(), Decimal("0.2"))

    def test_a_broken_plan_lookup_uses_the_built_in_plans_not_a_25_percent_markup(self) -> None:
        with patch("users.plans._plans_dict", side_effect=RuntimeError("db down")):
            multiplier = pricing.admart_markup_multiplier("10")
        self.assertGreaterEqual(multiplier * Decimal("79") / Decimal("120"), Decimal("1.1"))


def _image_option_sets(capability: str, model: str) -> list[dict]:
    resolutions = [None, "0.5K", "1K", "2K", "4K"]
    qualities = [None, "auto", "low", "medium", "high"]
    sizes = [None, {"width": 1024, "height": 1024}, {"width": 2048, "height": 2048}, {"width": 3840, "height": 2160}]
    combos = []
    for res, quality, size, count, search in itertools.product(resolutions, qualities, sizes, (1, 4), (False, True)):
        data: dict = {"numImages": count, "imageUrls": ["a"] * (2 if capability == "multiEdit" else 1)}
        if res:
            data["resolution"] = res
        if quality:
            data["quality"] = quality
        if size:
            data["imageSize"] = size
        if search:
            data["enableWebSearch"] = True
        combos.append(data)
    for speed in ("TURBO", "BALANCED", "QUALITY"):
        combos.append({"renderingSpeed": speed})
    for scale in (2, 4):
        combos.append({"scale": scale})
    return combos


def _video_option_sets(entry: dict) -> list[dict]:
    fields = entry.get("fields") or {}
    durations = (fields.get("duration") or [None]) + [None]
    resolutions = (fields.get("resolution") or [None]) + [None]
    audio = (True, False, None) if fields.get("generateAudio") else (None,)
    combos = []
    for duration, res, sound in itertools.product(durations, resolutions, audio):
        data = {k: v for k, v in (("duration", duration), ("resolution", res), ("generateAudio", sound)) if v is not None}
        combos.append(data)
    return combos


@override_settings(FAL_KEY="")
class NoLossRegressionTests(TestCase):
    """Every catalog model, every option: credits x cheapest $/credit >= fal cost x (1 + MIN_PLAN_MARGIN)."""

    def setUp(self) -> None:
        _reset_cache()
        self.addCleanup(_reset_cache)

    def assert_no_loss(self, quote: dict, value: Decimal, label: str) -> None:
        cost = quote["fal_cost_decimal"]
        self.assertGreater(cost, 0, label)
        self.assertGreaterEqual(quote["credits_decimal"] * value, cost * (1 + pricing.MIN_PLAN_MARGIN), label)

    def test_no_model_option_combination_bills_below_cost(self) -> None:
        value = pricing.cheapest_credit_value()
        checked = 0
        for capability, models in MODEL_CATALOG.items():
            for entry in models:
                for data in _image_option_sets(capability, entry["id"]):
                    quote = pricing.quote_image_job(capability, entry["id"], data)
                    self.assert_no_loss(quote, value, f"{entry['id']} {data}")
                    checked += 1
        for capability, models in VIDEO_MODEL_CATALOG.items():
            for entry in models:
                for data in _video_option_sets(entry):
                    quote = pricing.quote_video_job(capability, entry["id"], data)
                    self.assert_no_loss(quote, value, f"{entry['id']} {data}")
                    checked += 1
        self.assertGreater(checked, 1000)

    def test_tiny_jobs_round_up_not_down(self) -> None:
        quote = pricing.quote_image_job("removeBackground", "fal-ai/birefnet/v2", {})
        self.assert_no_loss(quote, pricing.cheapest_credit_value(), "birefnet")


@override_settings(FAL_KEY="")
class AgentImageCostTests(TestCase):
    def setUp(self) -> None:
        _reset_cache()
        self.addCleanup(_reset_cache)

    def test_agent_images_use_the_same_quote_engine(self) -> None:
        from agents.registry import _image_usd

        # 768x1344 is under 1536x1536 (Seedream's lower tier) and inside GPT Image's 1-2 MP bucket.
        self.assertEqual(_image_usd("bytedance/seedream/v5/pro/text-to-image"), Decimal("0.0675"))
        self.assertEqual(_image_usd("openai/gpt-image-2.5/flare/text-to-image"), Decimal("0.0527"))
        self.assertEqual(_image_usd("fal-ai/nano-banana-2"), Decimal("0.08"))

    def test_a_placeholder_snapshot_does_not_reach_agent_quotes(self) -> None:
        from agents.registry import _image_usd

        FalPriceSnapshot.objects.create(endpoint_id="openai/gpt-image-2.5/flare/text-to-image",
                                        unit_price=Decimal("1"), unit="units", fetched_at=timezone.now())
        with patch("content.pricing._start_background_refresh"):
            self.assertEqual(_image_usd("openai/gpt-image-2.5/flare/text-to-image"), Decimal("0.0527"))


class PlanFeatureTextTests(TestCase):
    def test_static_plans_and_packs_name_the_model_versions(self) -> None:
        from users.packs import TOPUP_PACKS
        from users.plans import PLAN_TIERS

        text = " ".join(f for p in [*PLAN_TIERS.values(), *TOPUP_PACKS.values()] for f in p["features"])
        self.assertNotRegex(text, r"Nano Banana images")
        self.assertNotRegex(text, r"Seedance videos")
        # Plans' "≈ N" lines are no longer typed in: users.plans.plan_usage prices them live.
        self.assertNotIn("\u2248", " ".join(f for p in PLAN_TIERS.values() for f in p["features"]))

    def test_migration_renames_only_untouched_feature_lines(self) -> None:
        import importlib

        from django.apps import apps

        from admin_panel.models import PlanDefinition, TopupPack

        migration = importlib.import_module("admin_panel.migrations.0013_feature_text_model_versions")
        basic = PlanDefinition.objects.get(plan_id="basic")
        basic.features = ["8 Admart credits monthly", "≈47 Nano Banana images per month",
                          "≈3 Seedance videos (5s, 720p) per month", "My own Nano Banana images line"]
        basic.save()
        pack = TopupPack.objects.get(pack_id="pack_small")
        pack.features = ["≈30 Nano Banana images or ≈2 Seedance videos"]
        pack.save()

        migration.rename_models(apps, None)
        basic.refresh_from_db()
        pack.refresh_from_db()
        self.assertEqual(basic.features, ["8 Admart credits monthly", "≈47 Nano Banana 2 images per month",
                                          "≈3 Seedance 2.0 videos (5s, 720p) per month",
                                          "My own Nano Banana images line"])
        self.assertEqual(pack.features, ["≈30 Nano Banana 2 images or ≈2 Seedance 2.0 videos"])
