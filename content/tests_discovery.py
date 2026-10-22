"""New fal models: the discover_fal_models job lists them for the admin; users never see them until curated."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import Mock, patch

import requests
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from content import fal_models
from content.models import FalModelListing
from users.models import User


def _page(*models: tuple[str, str]) -> Mock:
    response = Mock(status_code=200)
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "models": [{"endpoint_id": mid, "metadata": {"display_name": name, "category": "text-to-image",
                                                     "status": "active", "model_url": f"https://fal.ai/models/{mid}"}}
                   for mid, name in models],
        "next_cursor": None,
        "has_more": False,
    }
    return response


PRICES = {"vendor/new-model": {"unit_price": "0.03", "unit": "images", "currency": "USD"}}


@override_settings(FAL_KEY="test-key")
class DiscoverNewModelsTests(TestCase):
    def setUp(self) -> None:
        fal_models._CACHE.clear()
        self.addCleanup(fal_models._CACHE.clear)

    def discover(self, *models: tuple[str, str]) -> list[str]:
        with patch("content.fal_models.requests.get", return_value=_page(*models)), \
                patch("content.fal_models.get_fal_prices", return_value=PRICES):
            return fal_models.discover_new_models()

    def test_new_models_are_listed_with_their_price_and_curated_ones_are_skipped(self) -> None:
        new = self.discover(("vendor/new-model", "New Model"), ("fal-ai/flux/dev", "Flux Dev"))
        self.assertEqual(new, ["vendor/new-model"])
        listing = FalModelListing.objects.get()
        self.assertEqual((listing.endpoint_id, listing.label, listing.status), ("vendor/new-model", "New Model", "new"))
        self.assertEqual((listing.unit_price, listing.unit), (Decimal("0.03"), "images"))
        self.assertEqual(listing.model_url, "https://fal.ai/models/vendor/new-model")

    def test_a_second_run_reports_nothing_new_and_keeps_the_admins_choice(self) -> None:
        self.discover(("vendor/new-model", "New Model"))
        FalModelListing.objects.update(status="ignored", last_seen=timezone.now() - timedelta(days=3))
        self.assertEqual(self.discover(("vendor/new-model", "New Model")), [])
        listing = FalModelListing.objects.get()
        self.assertEqual(listing.status, "ignored")
        self.assertGreater(listing.last_seen, timezone.now() - timedelta(minutes=1))

    def test_a_listed_model_that_was_since_added_to_admart_is_marked_added(self) -> None:
        FalModelListing.objects.create(endpoint_id="fal-ai/flux/dev", label="Flux Dev", category="text-to-image")
        self.discover(("fal-ai/flux/dev", "Flux Dev"))
        self.assertEqual(FalModelListing.objects.get().status, "added")

    def test_fal_down_keeps_the_list_and_is_logged(self) -> None:
        FalModelListing.objects.create(endpoint_id="vendor/old", label="Old", category="text-to-video")
        with patch("content.fal_models.requests.get", side_effect=requests.ConnectionError("dns")), \
                self.assertLogs("content.fal_models", "WARNING") as logs:
            self.assertEqual(fal_models.discover_new_models(), [])
        self.assertEqual(FalModelListing.objects.count(), 1)
        self.assertIn("dns", "\n".join(logs.output))

    def test_discover_if_stale_runs_once_a_day(self) -> None:
        with patch("content.fal_models.discover_new_models", return_value=[]) as discover:
            fal_models.discover_if_stale()  # nothing listed yet: run
            FalModelListing.objects.create(endpoint_id="vendor/a", label="A", category="text-to-image")
            fal_models.discover_if_stale()  # just seen: skip
            FalModelListing.objects.update(last_seen=timezone.now() - timedelta(days=2))
            fal_models.discover_if_stale()  # stale: run
        self.assertEqual(discover.call_count, 2)

    @override_settings(FAL_KEY="")
    def test_without_a_key_nothing_is_fetched(self) -> None:
        with patch("content.fal_models.requests.get") as get:
            self.assertIsNone(fal_models.discover_if_stale())
        get.assert_not_called()

    def test_management_command_names_the_new_models(self) -> None:
        out = StringIO()
        with patch("content.fal_models.discover_new_models", return_value=["vendor/new-model"]):
            call_command("discover_fal_models", stdout=out)
        self.assertIn("vendor/new-model", out.getvalue())

    def test_celery_task_beat_entry_and_worker_loop(self) -> None:
        from django.conf import settings

        from content import tasks

        with patch("content.tasks.call_command") as command:
            tasks.discover_fal_models()
        command.assert_called_once_with("discover_fal_models", verbosity=0)
        self.assertEqual(settings.CELERY_BEAT_SCHEDULE["fal-model-discovery"]["task"],
                         "content.tasks.discover_fal_models")

        with patch("agents.management.commands.run_agents_worker.fal_models.discover_if_stale") as discover, \
                patch("agents.management.commands.run_agents_worker.pricing.refresh_prices_if_stale"), \
                patch("agents.management.commands.run_agents_worker.beat"), \
                patch("agents.management.commands.run_agents_worker.run_due", return_value=0), \
                patch("agents.management.commands.run_agents_worker.claim_next",
                      side_effect=[None, KeyboardInterrupt]), \
                patch("agents.management.commands.run_agents_worker.time.sleep"):
            with self.assertRaises(KeyboardInterrupt):
                call_command("run_agents_worker", stdout=StringIO())
        discover.assert_called_once()


class FalModelListingAdminTests(TestCase):
    def test_staff_see_new_models_and_can_ignore_them(self) -> None:
        admin = User.objects.create_superuser(email="owner@example.com", password="pass12345")
        self.client.force_login(admin)
        listing = FalModelListing.objects.create(endpoint_id="vendor/new-model", label="New Model",
                                                 category="text-to-video", unit_price=Decimal("0.05"), unit="seconds")
        url = "/admin/content/falmodellisting/"
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "New Model")
        self.client.post(url, {"action": "mark_ignored", "_selected_action": [listing.pk]})
        listing.refresh_from_db()
        self.assertEqual(listing.status, "ignored")
