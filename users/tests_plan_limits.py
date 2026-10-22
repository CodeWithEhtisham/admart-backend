"""The plan lineup (Starter free, Basic, Plus, Pro) and what each plan unlocks: agents, scheduled agents,
video models and quality, Clip Maker length, priority queue, signup credits and the usage estimates."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from agents.models import AgentDeployment
from content.fal_client import FalSubmission
from projects.models import Project
from users import entitlements
from users.models import User
from users.plans import get_plan, serialize_plan


def _user(plan: str, email: str | None = None) -> User:
    return User.objects.create_user(email=email or f"{plan}@example.com", password="Password123!", plan=plan,
                                    credits_remaining=Decimal("50"))


class PlanLineupTests(TestCase):
    def test_starter_is_the_free_plan(self) -> None:
        starter = get_plan("free")
        self.assertEqual(starter["name"], "Starter")
        self.assertEqual(starter["price_usd"], Decimal("0"))
        limits = starter["limits"]
        self.assertEqual((limits["max_projects"], limits["max_social_connections_per_project"]), (1, 2))
        self.assertTrue(limits["can_auto_publish"])
        self.assertFalse(limits["can_schedule_publishing"])

    def test_the_old_5_dollar_starter_is_hidden_and_templates_are_gone(self) -> None:
        from users.plans import get_public_plan_ids

        self.assertEqual(get_public_plan_ids(), ("free", "basic", "plus", "pro"))
        for plan_id in ("free", "basic", "plus", "pro"):
            text = " ".join(get_plan(plan_id)["features"]).lower()
            self.assertNotIn("template", text, plan_id)

    def test_agents_and_schedules_grow_with_the_plan(self) -> None:
        agents = {p: set(get_plan(p)["limits"]["agents"]) for p in ("free", "basic", "plus", "pro")}
        self.assertEqual(agents["free"], {"youtube-shorts", "script-writer", "voiceover", "trend-finder"})
        self.assertEqual(agents["basic"] - agents["free"], {"cross-poster", "clip-maker", "video-editor"})
        self.assertEqual(agents["plus"] - agents["basic"], {"growth-report"})
        self.assertEqual(agents["pro"], agents["plus"])
        self.assertEqual([get_plan(p)["limits"]["max_scheduled_agents"] for p in ("free", "basic", "plus", "pro")],
                         [0, 1, 3, 10])

    def test_signup_gives_5_trial_credits(self) -> None:
        from admin_panel.services import free_signup_credits

        self.assertEqual(free_signup_credits(), Decimal("5"))

    @override_settings(FAL_KEY="")
    def test_plans_list_how_many_images_videos_and_shorts_the_credits_buy(self) -> None:
        basic = serialize_plan("basic")["features"]
        self.assertIn("≈47 Nano Banana 2 images per month", basic)
        self.assertIn("≈3 Seedance 2.0 videos (5s, 720p) per month", basic)
        self.assertTrue(any(line.startswith("≈") and "YouTube Shorts" in line for line in basic))
        starter = serialize_plan("free")["features"]
        self.assertIn("≈29 Nano Banana 2 images with the trial credits", starter)
        # Starter can't use Seedance 2.0, so its video line is a model it can use.
        self.assertTrue(any("Hailuo 02" in line for line in starter))
        self.assertIn("usage", serialize_plan("pro"))


class AgentPlanTests(APITestCase):
    def setUp(self) -> None:
        self.user = _user("free")
        self.client.force_authenticate(user=self.user)
        self.project = Project.objects.create(owner=self.user, name="Brand")
        self.url = reverse("agent_deployments", kwargs={"project_id": self.project.id})


    def set_plan(self, plan: str) -> None:
        User.objects.filter(id=self.user.id).update(plan=plan)
        self.user.refresh_from_db()
        self.client.force_authenticate(user=self.user)
    def test_starter_can_start_its_agents_but_not_basic_ones(self) -> None:
        self.assertEqual(self.client.post(self.url, {"agentType": "youtube-shorts"}, format="json").status_code, 201)
        response = self.client.post(self.url, {"agentType": "clip-maker"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual((response.data["code"], response.data["requiredPlan"]), ("PLAN_REQUIRED", "basic"))
        self.assertIn("Basic", response.data["message"])

    def test_catalog_marks_locked_agents_with_the_plan_they_need(self) -> None:
        catalog = {a["slug"]: a for a in self.client.get(reverse("agent_catalog")).data}
        self.assertIsNone(catalog["youtube-shorts"]["requiredPlan"])
        self.assertEqual(catalog["growth-report"]["requiredPlan"], {"id": "plus", "name": "Plus"})

    def test_an_agent_left_after_a_downgrade_cannot_run(self) -> None:
        from agents.runs import RunRefused, start_run

        deployment = AgentDeployment.objects.create(project=self.project, user=self.user, agent_type="clip-maker")
        with self.assertRaises(RunRefused) as refused:
            start_run(deployment, {"assetId": "x"})
        self.assertEqual(refused.exception.code, "PLAN_REQUIRED")

    def _schedule(self, deployment, days=(0,), mode=None):
        url = reverse("agent_deployment", kwargs={"project_id": self.project.id, "deployment_id": deployment.id})
        schedule = {"days": list(days), "time": "09:00", "tz": "UTC", "dayOfMonth": 1, **({"mode": mode} if mode else {})}
        return self.client.patch(url, {"autopilot": True, "schedule": schedule, "topicQueue": ["a topic"]}, format="json")

    def test_scheduled_agents_are_limited_by_plan(self) -> None:
        shorts = AgentDeployment.objects.create(project=self.project, user=self.user, agent_type="youtube-shorts")
        response = self._schedule(shorts)
        self.assertEqual((response.status_code, response.data["requiredPlan"]), (403, "basic"))

        self.set_plan("basic")
        self.assertEqual(self._schedule(shorts, mode="weekly").status_code, 200)
        writer = AgentDeployment.objects.create(project=self.project, user=self.user, agent_type="script-writer")
        second = self._schedule(writer, mode="weekly")
        self.assertEqual((second.status_code, second.data["requiredPlan"]), (403, "plus"))

    def test_basic_schedules_weekly_and_plus_daily(self) -> None:
        self.set_plan("basic")
        shorts = AgentDeployment.objects.create(project=self.project, user=self.user, agent_type="youtube-shorts")
        daily = self._schedule(shorts, days=range(7), mode="daily")
        self.assertEqual((daily.status_code, daily.data["requiredPlan"]), (403, "plus"))
        self.assertEqual(self._schedule(shorts, mode="monthly").status_code, 200)
        self.set_plan("plus")
        self.assertEqual(self._schedule(shorts, days=range(7), mode="daily").status_code, 200)

    def test_schedules_over_the_plan_after_a_downgrade_are_skipped_with_a_note(self) -> None:
        from agents.runs import run_due

        deployment = AgentDeployment.objects.create(
            project=self.project, user=self.user, agent_type="youtube-shorts", autopilot=True,
            schedule={"days": [0], "time": "09:00", "tz": "UTC", "mode": "weekly"}, topic_queue=["a"],
            next_run_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(run_due(), 0)
        deployment.refresh_from_db()
        self.assertIn("plan", deployment.autopilot_note.lower())

    def test_clip_maker_length_follows_the_plan(self) -> None:
        self.assertEqual(entitlements.clip_max_seconds(User(plan="basic")), 60 * 60)
        self.assertEqual(entitlements.clip_max_seconds(User(plan="plus")), 120 * 60)

    def test_pro_runs_go_first_in_the_agent_queue(self) -> None:
        from agents.engine import due_queued_ids
        from agents.runs import start_run

        self.set_plan("plus")
        plus_run = start_run(AgentDeployment.objects.create(project=self.project, user=self.user,
                                                            agent_type="script-writer"), {"topic": "a"})
        pro = _user("pro")
        pro_project = Project.objects.create(owner=pro, name="Pro brand")
        pro_run = start_run(AgentDeployment.objects.create(project=pro_project, user=pro, agent_type="script-writer"),
                            {"topic": "b"})
        self.assertTrue(pro_run.priority)
        self.assertEqual(due_queued_ids()[:2], [pro_run.id, plus_run.id])


@override_settings(FAL_KEY="test-key")
class ModelPlanTests(APITestCase):
    def setUp(self) -> None:
        self.user = _user("free")
        self.client.force_authenticate(user=self.user)
        self.project = Project.objects.create(owner=self.user, name="Brand")


    def set_plan(self, plan: str) -> None:
        User.objects.filter(id=self.user.id).update(plan=plan)
        self.user.refresh_from_db()
        self.client.force_authenticate(user=self.user)
    def video(self, model, **extra):
        url = reverse("video_job_list_create", kwargs={"project_id": self.project.id})
        return self.client.post(url, {"capability": "textToVideo", "prompt": "a cat", "model": model, **extra}, format="json")

    def image(self, **extra):
        url = reverse("image_job_list_create", kwargs={"project_id": self.project.id})
        return self.client.post(url, {"capability": "textToImage", "prompt": "a cat", **extra}, format="json")

    def assert_needs(self, response, plan_id: str) -> None:
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.data)
        self.assertEqual((response.data["code"], response.data["requiredPlan"]), ("PLAN_REQUIRED", plan_id))

    def test_video_models_by_plan(self) -> None:
        self.assert_needs(self.video("fal-ai/veo3.1/fast"), "basic")
        self.assert_needs(self.video("fal-ai/veo3.1"), "plus")
        submission = FalSubmission(request_id="r1", status_url="https://queue.fal.run/x/requests/r1/status",
                                   response_url="https://queue.fal.run/x/requests/r1")
        with patch("content.video_views.fal_client.submit", return_value=submission):
            self.assertEqual(self.video("fal-ai/minimax/hailuo-02/standard/text-to-video").status_code, 202)

    def test_video_quality_by_plan(self) -> None:
        self.assert_needs(self.video("google/gemini-omni-flash/v1.1/text-to-video", resolution="1080p"), "plus")
        self.set_plan("basic")
        # MiniMax H3 renders 2K when no resolution is sent: that is above Basic's 720p.
        self.assert_needs(self.video("minimax/h3/text-to-video"), "pro")
        self.set_plan("plus")
        self.assert_needs(self.video("fal-ai/veo3.1", resolution="4k"), "pro")

    def test_4k_images_are_pro_only(self) -> None:
        self.assert_needs(self.image(model="fal-ai/nano-banana-pro", resolution="4K"), "pro")
        self.assert_needs(self.image(model="openai/gpt-image-2", imageSize={"width": 3840, "height": 2160}), "pro")

    def test_catalogs_mark_locked_models_and_the_plan_limits(self) -> None:
        catalog = self.client.get("/api/videos/models").data
        veo = next(m for m in catalog["textToVideo"] if m["id"] == "fal-ai/veo3.1")
        hailuo = next(m for m in catalog["textToVideo"] if m["id"] == "fal-ai/minimax/hailuo-02/standard/text-to-video")
        self.assertEqual(veo["requiredPlan"], {"id": "plus", "name": "Plus"})
        self.assertIsNone(hailuo["requiredPlan"])
        self.assertEqual(catalog["_plan"]["videoMaxResolution"], "720p")
        self.assertEqual(self.client.get("/api/images/models").data["_plan"]["imageMaxResolution"], "2k")
