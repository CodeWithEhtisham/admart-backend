import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from agents import engine, providers, render, steps
from agents.models import AgentDeployment, AgentRun
from agents.registry import BUILTIN_AGENTS, estimate_credits, validate_recipe
from projects.models import Project

User = get_user_model()
NO_PRICES = patch("agents.registry.get_fal_prices", return_value={})
# Tests never depend on the developer's .env. Real (non-dry) mode with one paid provider per job
# (fake keys, every HTTP call is patched), no local models, no stock, no music.
HERMETIC = {
    "AGENTS_DRY_RUN": False, "OPENAI_API_KEY": "k", "GEMINI_API_KEY": "k", "FAL_KEY": "k", "GROQ_API_KEY": "",
    "PEXELS_API_KEY": "", "CLOUDFLARE_ACCOUNT_ID": "", "CLOUDFLARE_API_TOKEN": "",
    "AGENTS_LLM_PROVIDERS": "gemini", "AGENTS_TTS_PROVIDERS": "openai", "AGENTS_IMAGE_PROVIDERS": "fal",
    "AGENTS_CAPTION_PROVIDERS": "openai", "AGENTS_KOKORO_DIR": "/nonexistent-kokoro",
    "AGENTS_MUSIC_DIR": "/nonexistent-agent-music",
}
FREE_PROVIDERS = {
    "AGENTS_LLM_PROVIDERS": "groq", "GROQ_API_KEY": "g", "AGENTS_TTS_PROVIDERS": "gemini",
    "AGENTS_IMAGE_PROVIDERS": "cloudflare", "CLOUDFLARE_ACCOUNT_ID": "a", "CLOUDFLARE_API_TOKEN": "t",
    "AGENTS_CAPTION_PROVIDERS": "",
}


class CleanScriptTests(SimpleTestCase):
    def test_bounds_and_adds_shorts_tag(self) -> None:
        raw = {
            "title": "T" * 200,
            "description": "About coffee.",
            "tags": "#coffee, beans, ",
            "scenes": [{"narration": f"line {i}", "image_prompt": f"pic {i}"} for i in range(10)] + ["junk"],
        }
        out = steps.clean_script(raw, "coffee")
        self.assertEqual(len(out["title"]), 90)
        self.assertTrue(out["description"].endswith("#Shorts"))
        self.assertEqual(out["tags"], ["coffee", "beans"])
        self.assertEqual(len(out["scenes"]), 7)

    def test_rejects_script_without_enough_scenes(self) -> None:
        with self.assertRaises(RuntimeError):
            steps.clean_script({"scenes": [{"narration": "a", "image_prompt": "b"}]}, "x")

    def test_estimated_word_times_cover_the_scene(self) -> None:
        words = render.estimate_word_times("one two three four", 4.0)
        self.assertEqual([w["word"] for w in words], ["one", "two", "three", "four"])
        self.assertAlmostEqual(words[0]["start"], 0.0)
        self.assertAlmostEqual(words[-1]["end"], 4.0, places=2)

    def test_captions_highlight_the_spoken_word_and_strip_ass_codes(self) -> None:
        scenes = [{"duration": 2.0, "words": render.estimate_word_times("hi {bad} there", 2.0)},
                  {"duration": 1.0, "words": [{"word": "next", "start": 0.0, "end": 1.0}]}]
        ass = render.build_captions(scenes, "#FF5500")
        self.assertIn("{\\c&H000055FF}hi{\\c&H00FFFFFF&} bad there", ass)
        self.assertNotIn("{bad}", ass)
        self.assertIn("Dialogue: 0,0:00:02.00,", ass)  # second scene is offset by the first

    def test_clean_concepts_keeps_known_styles(self) -> None:
        out = steps.clean_concepts({"concepts": [{"title": "A", "hook": "h", "angle": "a", "style": "weird"},
                                                 {"title": "", "hook": "x"}]})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["style"], "cinematic")


@override_settings(**HERMETIC)
class EstimateTests(SimpleTestCase):
    @NO_PRICES
    def test_real_runs_cost_credits_and_dry_runs_are_free(self, _prices) -> None:
        shorts = estimate_credits(BUILTIN_AGENTS["youtube-shorts"], {})
        script = estimate_credits(BUILTIN_AGENTS["script-writer"], {})
        self.assertGreater(shorts, script)
        self.assertGreater(script, 0)
        with override_settings(AGENTS_DRY_RUN=True):
            self.assertEqual(estimate_credits(BUILTIN_AGENTS["youtube-shorts"], {}), 0)

    @NO_PRICES
    def test_free_providers_only_charge_for_text(self, _prices) -> None:
        with override_settings(**FREE_PROVIDERS, AGENTS_LLM_USD_PER_RUN="0"):
            self.assertEqual(estimate_credits(BUILTIN_AGENTS["youtube-shorts"], {}), 0)


class _AgentAPITestCase(APITestCase):
    dry_run = False

    def setUp(self) -> None:
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        media = override_settings(
            MEDIA_ROOT=self.media, MEDIA_BASE_URL="http://testserver", **{**HERMETIC, "AGENTS_DRY_RUN": self.dry_run}
        )
        media.enable()
        self.addCleanup(media.disable)
        prices = NO_PRICES.start()
        self.addCleanup(NO_PRICES.stop)
        self.assertIsNotNone(prices)
        self.user = User.objects.create_user(
            email="agent@example.com", password="Password123!", first_name="A", last_name="G", plan="plus"
        )
        self.client.force_authenticate(user=self.user)
        self.project = Project.objects.create(owner=self.user, name="Brand", brand_name="Bean Co")

    def deploy(self, agent_type="youtube-shorts", **extra) -> AgentDeployment:
        response = self.client.post(
            reverse("agent_deployments", kwargs={"project_id": self.project.id}),
            {"agentType": agent_type, **extra},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return AgentDeployment.objects.get(id=response.data["id"])

    def runs_url(self, deployment) -> str:
        return reverse("agent_runs", kwargs={"project_id": self.project.id, "deployment_id": deployment.id})

    def start(self, deployment, **payload):
        return self.client.post(self.runs_url(deployment), payload or {"topic": "coffee facts"}, format="json")


class DryRunPipelineTests(_AgentAPITestCase):
    """The whole Shorts pipeline, including a real FFmpeg render, at zero cost."""

    dry_run = True

    def _action(self, deployment, run_id, action, payload=None):
        url = reverse(
            "agent_run_action",
            kwargs={"project_id": self.project.id, "deployment_id": deployment.id, "run_id": run_id, "action": action},
        )
        return self.client.post(url, payload or {}, format="json")

    def _work(self):
        call_command("run_agents_worker", "--once", stdout=MagicMock())

    def test_shorts_run_with_every_checkpoint(self) -> None:
        deployment = self.deploy(config={"style": "anime"})
        response = self.start(deployment)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["credits"], "0")
        run_id = response.data["id"]

        self._work()
        run = AgentRun.objects.get(id=run_id)
        self.assertEqual((run.status, run.step), ("needs_review", "concept"), run.error)
        self.assertEqual(len(run.output["concepts"]), 3)
        self.assertIn("research", run.output)

        self.assertEqual(self._action(deployment, run_id, "continue", {"index": 7}).status_code, 400)
        self._action(deployment, run_id, "continue", {"index": 1, "hook": "My own hook."})
        self._work()
        run.refresh_from_db()
        self.assertEqual((run.status, run.step), ("needs_review", "script"))
        self.assertEqual(run.output["concept"]["hook"], "My own hook.")

        edited = {
            "title": "Edited title",
            "description": "Edited.",
            "tags": ["coffee"],
            "scenes": [{"narration": f"Edited line {i}.", "image_prompt": f"picture {i}"} for i in range(3)],
        }
        self._action(deployment, run_id, "continue", edited)
        self._work()
        run.refresh_from_db()
        self.assertEqual((run.status, run.step), ("needs_review", "storyboard"))
        self.assertEqual(len(run.output["scenes"]), 3)
        self.assertTrue(all(s["image"] and s["audio"] and s["words"] for s in run.output["scenes"]))
        first_image = run.output["scenes"][0]["image"]

        self.assertEqual(self._action(deployment, run_id, "regenerate", {"scene": 0, "prompt": "a red cup"}).status_code, 200)
        self._work()
        run.refresh_from_db()
        self.assertEqual(run.step, "storyboard")
        self.assertEqual(run.output["scenes"][0]["image_prompt"], "a red cup")
        self.assertTrue(run.output["scenes"][0]["image"])

        self._action(deployment, run_id, "continue")
        self._work()
        run.refresh_from_db()
        self.assertEqual((run.status, run.step), ("needs_review", "final"), run.error)
        self.assertLess(run.attempts, 2)  # checkpoint resumes don't count as retries
        video = Path(self.media) / run.output["video"]
        self.assertGreater(render.duration_of(video), 3)
        self.assertIn("No black frames", run.output["checks"])
        self.assertEqual(run.output["title"], "Edited title")
        self.assertEqual(run.library_asset.media_type, "video")
        self.assertIsNotNone(first_image)

        detail = self.client.get(
            reverse("agent_run", kwargs={"project_id": self.project.id, "deployment_id": deployment.id, "run_id": run_id})
        ).data
        self.assertTrue(detail["videoUrl"].startswith("http"))
        self.assertEqual(len(detail["concepts"]), 3)
        self.assertEqual(self._action(deployment, run_id, "approve").data["status"], "approved")

    def test_final_review_only_runs_straight_through(self) -> None:
        deployment = self.deploy(config={"checkpoints": "final"})
        run_id = self.start(deployment).data["id"]
        self._work()
        run = AgentRun.objects.get(id=run_id)
        self.assertEqual((run.status, run.step), ("needs_review", "final"), run.error)
        self.assertEqual(run.output["concept"], run.output["concepts"][0])

    def test_voiceover_run_produces_audio(self) -> None:
        deployment = self.deploy("voiceover")
        response = self.start(deployment, text="Hello there, this is a short test voiceover.")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        call_command("run_agents_worker", "--once", stdout=MagicMock())
        run = AgentRun.objects.get(id=response.data["id"])
        self.assertEqual(run.status, "succeeded", run.error)
        self.assertTrue((Path(self.media) / run.output["scenes"][0]["audio"]).exists())
        self.assertIsNone(run.library_asset)

    def test_discard_hides_the_library_video(self) -> None:
        deployment = self.deploy(config={"checkpoints": "final"})
        run_id = self.start(deployment).data["id"]
        call_command("run_agents_worker", "--once", stdout=MagicMock())
        url = reverse(
            "agent_run_action",
            kwargs={"project_id": self.project.id, "deployment_id": deployment.id, "run_id": run_id, "action": "discard"},
        )
        self.assertEqual(self.client.post(url).data["status"], "discarded")
        self.assertIsNotNone(AgentRun.objects.get(id=run_id).library_asset.deleted_at)


class ProviderStepTests(_AgentAPITestCase):
    """Real-mode steps with Gemini, fal and OpenAI faked (no paid calls)."""

    def _run(self, agent_type="youtube-shorts", run_input=None) -> AgentRun:
        deployment = self.deploy(agent_type)
        return AgentRun.objects.create(
            deployment=deployment, project=self.project, user=self.user, input=run_input or {"topic": "coffee"}
        )

    @patch("agents.providers.requests.post")
    def test_script_uses_gemini_and_brand(self, post) -> None:
        post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": '{"title":"Coffee","description":"Facts.","tags":["coffee"],'
                                    '"scenes":[{"narration":"a","image_prompt":"b"},{"narration":"c","image_prompt":"d"},'
                                    '{"narration":"e","image_prompt":"f"}]}'
                                }
                            ]
                        }
                    }
                ]
            },
        )
        run = self._run()
        run.output = {"concept": {"title": "C", "hook": "Did you know?", "angle": "facts"}, "research": {"notes": "n"}}
        steps.step_script(run)
        self.assertEqual(len(run.output["scenes"]), 3)
        self.assertIn("Did you know?", post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"])
        self.assertIn("Bean Co", post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"])
        steps.step_script(run)  # already done: no second paid call
        self.assertEqual(post.call_count, 1)

    @patch("agents.providers.requests.post")
    def test_research_uses_search_grounding_and_keeps_sources(self, post) -> None:
        post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "- Fact one\n- Fact two"}]},
                        "groundingMetadata": {"groundingChunks": [{"web": {"uri": "https://x.org", "title": "X"}}]},
                    }
                ]
            },
        )
        run = self._run()
        steps.step_research(run)
        self.assertEqual(run.output["research"]["sources"], [{"title": "X", "uri": "https://x.org"}])
        self.assertIn("google_search", post.call_args.kwargs["json"]["tools"][0])

    @override_settings(PEXELS_API_KEY="p")
    @patch("agents.steps.requests.get")
    def test_visuals_use_stock_footage_when_it_fits(self, get) -> None:
        search = MagicMock(json=lambda: {"videos": [{
            "duration": 9, "url": "https://pexels.com/v/1", "user": {"name": "Ana"},
            "video_files": [{"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "https://cdn/clip.mp4"}],
        }]})
        get.side_effect = [search, MagicMock(content=b"mp4 bytes")]
        run = self._run()
        run.output = {"scenes": [{"narration": "a", "image_prompt": "b", "visual": "stock", "stock_query": "coffee beans",
                                  "duration": 3}]}
        steps.step_visuals(run)
        scene = run.output["scenes"][0]
        self.assertTrue(scene["clip"].endswith("clip-0.mp4"))
        self.assertEqual(scene["credit"]["by"], "Ana")

    @patch("agents.providers.requests.get")
    @patch("agents.providers.fal_client")
    def test_images_step_saves_each_scene_once(self, fal, get) -> None:
        fal.submit.return_value = MagicMock(status_url="s", response_url="r")
        fal.status.return_value = {"status": "COMPLETED"}
        fal.result.return_value = {"images": [{"url": "https://cdn/x.png"}]}
        get.return_value = MagicMock(content=b"\x89PNG fake", headers={"Content-Type": "image/png"})
        run = self._run()
        run.output = {"scenes": [{"narration": "a", "image_prompt": "b"}, {"narration": "c", "image_prompt": "d"}]}
        steps.step_visuals(run)
        steps.step_visuals(run)
        self.assertEqual(fal.submit.call_count, 2)
        self.assertTrue((Path(self.media) / run.output["scenes"][1]["image"]).exists())

    @patch("agents.providers.requests.post")
    def test_voice_step_records_duration(self, post) -> None:
        sample = Path(self.media) / "sample.mp3"
        render.silent_audio(sample, 2.0)
        post.return_value = MagicMock(status_code=200, content=sample.read_bytes())
        run = self._run("voiceover", {"text": "Hello world"})
        steps.step_voice(run)
        self.assertAlmostEqual(run.output["scenes"][0]["duration"], 2.0, delta=0.2)
        self.assertEqual(post.call_args.kwargs["json"]["input"], "Hello world")

    @patch("agents.providers.requests.post")
    def test_captions_use_word_timings_or_fall_back(self, post) -> None:
        audio = Path(self.media) / "a.mp3"
        render.silent_audio(audio, 2.0)
        post.return_value = MagicMock(json=lambda: {"words": [{"word": "Hello", "start": 0.1, "end": 0.6}]})
        run = self._run("voiceover", {"text": "Hello"})
        run.output = {"scenes": [{"narration": "Hello world", "audio": "a.mp3", "duration": 2.0}]}
        steps.step_captions(run)
        self.assertEqual(run.output["scenes"][0]["words"], [{"word": "Hello", "start": 0.1, "end": 0.6}])
        import requests as real_requests
        post.side_effect = real_requests.ConnectionError("down")
        del run.output["scenes"][0]["words"]
        with self.assertLogs("agents.providers", "WARNING"):
            steps.step_captions(run)
        self.assertEqual([w["word"] for w in run.output["scenes"][0]["words"]], ["Hello", "world"])

    def test_music_track_is_picked_from_the_folder(self) -> None:
        folder = Path(self.media) / "music"
        folder.mkdir()
        (folder / "calm.mp3").write_bytes(b"x")
        run = self._run()
        with override_settings(AGENTS_MUSIC_DIR=str(folder)):
            self.assertEqual(steps._music_track(run).name, "calm.mp3")
            run.deployment.config = {"music": False}
            self.assertIsNone(steps._music_track(run))

    def test_quality_check_rejects_black_video(self) -> None:
        clip = Path(self.media) / "black.mp4"
        render._run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=3", "-f", "lavfi",
                     "-i", "anullsrc=r=44100:cl=mono", "-t", "3", "-c:v", "libx264", "-c:a", "aac", str(clip)])
        with self.assertRaisesMessage(render.RenderError, "black"):
            render.check_video(clip, expect_sound=False)

    def test_voice_step_without_key_has_a_clear_error(self) -> None:
        run = self._run("voiceover", {"text": "Hi"})
        with override_settings(OPENAI_API_KEY=""), self.assertRaisesMessage(RuntimeError, "No voice service is set up"):
            steps.step_voice(run)


class ProviderChainTests(_AgentAPITestCase):
    """Free-first provider lists: skip what isn't set up, fall through on failure."""

    @override_settings(AGENTS_LLM_PROVIDERS="gemini,groq", GROQ_API_KEY="g")
    @patch("agents.providers.requests.post")
    def test_text_falls_back_to_groq_when_gemini_fails(self, post) -> None:
        import requests as real_requests

        groq = MagicMock(json=lambda: {"choices": [{"message": {"content": '{"ok": true}'}}]})
        post.side_effect = [real_requests.HTTPError("429 free tier used up"), groq]
        with self.assertLogs("agents.providers", "WARNING"):
            self.assertEqual(providers.text("sys", "user"), {"ok": True})
        self.assertIn("groq.com", post.call_args.args[0])
        self.assertEqual(post.call_args.kwargs["json"]["response_format"], {"type": "json_object"})

    @override_settings(AGENTS_TTS_PROVIDERS="kokoro,gemini")
    @patch("agents.providers.requests.post")
    def test_gemini_voice_is_converted_to_mp3_and_missing_kokoro_is_skipped(self, post) -> None:
        import base64

        pcm = b"\x00\x00" * 24000  # one second of 24 kHz silence
        post.return_value = MagicMock(json=lambda: {"candidates": [{"content": {"parts": [
            {"inlineData": {"data": base64.b64encode(pcm).decode()}}]}}]})
        audio = Path(self.media) / "g.mp3"
        audio.write_bytes(providers.speech("Hello"))
        self.assertAlmostEqual(render.duration_of(audio), 1.0, delta=0.15)
        self.assertEqual(post.call_count, 1)  # Kokoro had no model files, so it was never tried

    @override_settings(AGENTS_IMAGE_PROVIDERS="cloudflare,fal", CLOUDFLARE_ACCOUNT_ID="a", CLOUDFLARE_API_TOKEN="t")
    @patch("agents.providers.requests.post")
    def test_cloudflare_image_is_decoded(self, post) -> None:
        import base64

        post.return_value = MagicMock(json=lambda: {"result": {"image": base64.b64encode(b"jpegbytes").decode()}})
        self.assertEqual(providers.image("a cat", 768, 1344), (b"jpegbytes", ".jpg"))
        self.assertIn("/accounts/a/ai/run/", post.call_args.args[0])

    @override_settings(AGENTS_IMAGE_PROVIDERS="cloudflare", AGENTS_TTS_PROVIDERS="")
    def test_nothing_set_up_gives_a_clear_message(self) -> None:
        with self.assertRaisesMessage(providers.ProviderUnavailable, "No image service is set up"):
            providers.image("x", 10, 10)
        with self.assertRaisesMessage(providers.ProviderUnavailable, "No voice service is set up"):
            providers.speech("x")


class EngineTests(_AgentAPITestCase):
    def _queued(self, credits="1.5") -> AgentRun:
        self.user.refresh_from_db()
        deployment = self.deploy("script-writer")
        return AgentRun.objects.create(
            deployment=deployment, project=self.project, user=self.user, input={"topic": "x"},
            credits_reserved=Decimal(credits),
        )

    def test_failure_refunds_once_and_shows_message(self) -> None:
        run = self._queued()
        before = self.user.credits_remaining
        with patch.dict(steps.STEPS, {"script": MagicMock(side_effect=RuntimeError("The script writer is down."))}):
            engine.process(engine.claim_next())
        engine.fail(run, "again")  # second call must not refund twice
        run.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(run.status, "failed")
        self.assertIn("The script writer is down.", run.error)
        self.assertIn("refunded", run.error)
        self.assertEqual(self.user.credits_remaining, before + Decimal("1.5"))

    def test_unexpected_errors_are_summarised(self) -> None:
        run = self._queued()
        with patch.dict(steps.STEPS, {"script": MagicMock(side_effect=KeyError("secret internals"))}), \
                self.assertLogs("agents.engine", "ERROR"):
            engine.process(engine.claim_next())
        run.refresh_from_db()
        self.assertNotIn("secret", run.error)
        self.assertIn("writing the script", run.error)

    def test_paused_run_does_not_fail_or_refund(self) -> None:
        run = self._queued()
        from agents.steps import NeedsReview
        with patch.dict(steps.STEPS, {"script": MagicMock(side_effect=NeedsReview("script"))}):
            engine.process(engine.claim_next())
        run.refresh_from_db()
        self.assertEqual((run.status, run.step, run.error), ("needs_review", "script", ""))

    def test_stale_running_run_is_picked_up_again(self) -> None:
        run = self._queued()
        AgentRun.objects.filter(id=run.id).update(status="running", locked_until=timezone.now() - timedelta(minutes=1))
        claimed = engine.claim_next()
        self.assertEqual(claimed.id, run.id)
        self.assertEqual(claimed.attempts, 1)
        self.assertIsNone(engine.claim_next())  # now leased


class AgentAPITests(_AgentAPITestCase):
    def test_catalog_lists_small_and_large_agents(self) -> None:
        data = self.client.get(reverse("agent_catalog")).data
        kinds = {a["slug"]: a["kind"] for a in data}
        self.assertEqual(kinds["youtube-shorts"], "large")
        self.assertEqual(kinds["script-writer"], "small")
        shorts = next(a for a in data if a["slug"] == "youtube-shorts")
        self.assertIn("Script Writer", shorts["uses"])

    def test_unknown_agent_and_bad_limit_are_rejected(self) -> None:
        url = reverse("agent_deployments", kwargs={"project_id": self.project.id})
        self.assertEqual(self.client.post(url, {"agentType": "hack"}, format="json").status_code, 400)
        bad = self.client.post(url, {"agentType": "voiceover", "monthlyCreditLimit": "-1"}, format="json")
        self.assertEqual(bad.status_code, 400)

    def test_other_users_cannot_see_or_run(self) -> None:
        deployment = self.deploy()
        other = User.objects.create_user(email="o@example.com", password="Password123!", first_name="O", last_name="O")
        self.client.force_authenticate(user=other)
        self.assertEqual(self.client.get(self.runs_url(deployment)).status_code, 404)
        self.assertEqual(self.start(deployment).status_code, 404)

    def test_run_reserves_credits_and_validates_input(self) -> None:
        deployment = self.deploy()
        self.assertEqual(self.start(deployment, topic="").status_code, 400)
        before = self.user.credits_remaining
        response = self.start(deployment)
        self.assertEqual(response.status_code, 201)
        self.user.refresh_from_db()
        self.assertEqual(self.user.credits_remaining, before - Decimal(response.data["credits"]))

    def test_blank_topic_uses_an_auto_topic_when_there_is_a_niche(self) -> None:
        deployment = self.deploy(config={"niche": "coffee facts"})
        response = self.start(deployment, topic="  ")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(AgentRun.objects.get(id=response.data["id"]).input, {"topic": "", "auto": True})

    def test_insufficient_credits_returns_402(self) -> None:
        self.user.credits_remaining = Decimal("0")
        self.user.save(update_fields=["credits_remaining"])
        response = self.start(self.deploy())
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.data["code"], "INSUFFICIENT_CREDITS")

    def test_paused_agent_cannot_run(self) -> None:
        deployment = self.deploy()
        url = reverse("agent_deployment", kwargs={"project_id": self.project.id, "deployment_id": deployment.id})
        self.assertEqual(self.client.patch(url, {"status": "paused"}, format="json").data["status"], "paused")
        self.assertEqual(self.start(deployment).data["code"], "AGENT_PAUSED")

    def test_monthly_limit_and_open_run_cap(self) -> None:
        deployment = self.deploy(monthlyCreditLimit="0.0001")
        self.assertEqual(self.start(deployment).data["code"], "AGENT_MONTHLY_LIMIT")
        deployment.monthly_credit_limit = None
        deployment.save()
        for _ in range(3):
            self.assertEqual(self.start(deployment).status_code, 201)
        self.assertEqual(self.start(deployment).data["code"], "AGENT_BUSY")

    def test_cannot_remove_agent_with_open_runs(self) -> None:
        deployment = self.deploy()
        self.start(deployment)
        url = reverse("agent_deployment", kwargs={"project_id": self.project.id, "deployment_id": deployment.id})
        self.assertEqual(self.client.delete(url).data["code"], "AGENT_BUSY")

    def test_discard_at_an_early_checkpoint_refunds(self) -> None:
        deployment = self.deploy()
        response = self.start(deployment)
        run = AgentRun.objects.get(id=response.data["id"])
        self.user.refresh_from_db()
        before = self.user.credits_remaining
        AgentRun.objects.filter(id=run.id).update(status="needs_review", step="script")
        url = reverse("agent_run_action", kwargs={"project_id": self.project.id, "deployment_id": deployment.id,
                                                  "run_id": run.id, "action": "discard"})
        self.assertEqual(self.client.post(url).data["status"], "discarded")
        self.user.refresh_from_db()
        self.assertEqual(self.user.credits_remaining, before + Decimal(response.data["credits"]))

    def test_actions_only_at_the_right_checkpoint(self) -> None:
        deployment = self.deploy()
        run_id = self.start(deployment).data["id"]
        for action in ("continue", "regenerate", "approve", "discard"):
            url = reverse("agent_run_action", kwargs={"project_id": self.project.id, "deployment_id": deployment.id,
                                                      "run_id": run_id, "action": action})
            self.assertEqual(self.client.post(url, {}, format="json").status_code, 400, action)

    def test_voiceover_text_limit(self) -> None:
        deployment = self.deploy("voiceover")
        self.assertEqual(self.start(deployment, text="x" * 3001).status_code, 400)
        self.assertEqual(self.start(deployment, text="Hello").status_code, 201)


class RecipeValidationTests(SimpleTestCase):
    base = {"kind": "small", "input_kind": "topic", "review": False, "needs": [], "prompts": {}}

    def check(self, **overrides):
        return validate_recipe({**self.base, **overrides})

    def test_valid_recipes(self) -> None:
        self.assertIsNone(self.check(steps=["script"]))
        self.assertIsNone(self.check(steps=["research", "script", "voice"]))
        self.assertIsNone(self.check(steps=["voice"], input_kind="text"))
        shorts = BUILTIN_AGENTS["youtube-shorts"]
        self.assertIsNone(self.check(steps=list(shorts.steps), kind="large", review=True, needs=["youtube"]))

    def test_invalid_recipes_explain_why(self) -> None:
        self.assertIn("at least one", self.check(steps=[]))
        self.assertIn("Unknown step", self.check(steps=["hack"]))
        self.assertIn("only be used once", self.check(steps=["script", "script"]))
        self.assertIn("needs voice", self.check(steps=["captions", "voice"]))
        self.assertIn("need a topic", self.check(steps=["script"], input_kind="text"))
        self.assertIn("needs a script", self.check(steps=["voice"]))
        self.assertIn("Final approval", self.check(steps=["script"], review=True))
        self.assertIn("platform", self.check(steps=["script"], needs=["myspace"]))
        self.assertIn("Prompts", self.check(steps=["script"], prompts={"evil": "x"}))


class RecipeTests(_AgentAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.owner = User.objects.create_superuser(email="boss@example.com", password="Password123!",
                                                   first_name="B", last_name="O")
        self.staff = User.objects.create_user(email="staff@example.com", password="Password123!",
                                              first_name="S", last_name="T", is_staff=True)

    def test_builtin_recipes_are_seeded_and_listed(self) -> None:
        slugs = [a["slug"] for a in self.client.get(reverse("agent_catalog")).data]
        self.assertEqual(slugs, ["youtube-shorts", "script-writer", "voiceover"])

    def test_owner_creates_an_agent_that_users_can_deploy_and_run(self) -> None:
        self.client.force_authenticate(self.owner)
        payload = {"slug": "hook-writer", "name": "Hook Writer", "kind": "small", "inputKind": "topic",
                   "steps": ["research", "script"], "description": "Researched scripts.",
                   "prompts": {"script": "Write only a punchy script. Return JSON."}}
        response = self.client.post(reverse("admin_agent_recipes"), payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.client.force_authenticate(self.user)
        self.assertIn("hook-writer", [a["slug"] for a in self.client.get(reverse("agent_catalog")).data])
        deployment = self.deploy("hook-writer")
        self.assertEqual(self.start(deployment).status_code, 201)

    @patch("agents.providers.requests.post")
    def test_edited_prompt_is_used_by_the_step(self, post) -> None:
        self.client.force_authenticate(self.owner)
        url = reverse("admin_agent_recipe", kwargs={"slug": "script-writer"})
        self.assertEqual(self.client.put(url, {"prompts": {"script": "CUSTOM SCRIPT PROMPT"}}, format="json").status_code, 200)
        self.client.force_authenticate(self.user)
        post.return_value = MagicMock(json=lambda: {"candidates": [{"content": {"parts": [{"text":
            '{"title":"T","scenes":[{"narration":"a","image_prompt":"b"},{"narration":"c","image_prompt":"d"},'
            '{"narration":"e","image_prompt":"f"}]}'}]}}]})
        deployment = self.deploy("script-writer")
        run = AgentRun.objects.create(deployment=deployment, project=self.project, user=self.user, input={"topic": "x"})
        steps.step_script(run)
        self.assertEqual(post.call_args.kwargs["json"]["systemInstruction"]["parts"][0]["text"], "CUSTOM SCRIPT PROMPT")

    def test_invalid_edit_is_rejected_and_staff_cannot_edit(self) -> None:
        url = reverse("admin_agent_recipe", kwargs={"slug": "voiceover"})
        self.client.force_authenticate(self.staff)
        self.assertEqual(self.client.get(reverse("admin_agent_recipes")).status_code, 200)
        self.assertEqual(self.client.put(url, {"name": "X"}, format="json").status_code, 403)
        self.client.force_authenticate(self.owner)
        bad = self.client.put(url, {"steps": ["captions"]}, format="json")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("needs voice", bad.data["message"])
        self.client.force_authenticate(self.user)
        self.assertEqual(self.client.get(reverse("admin_agent_recipes")).status_code, 403)

    def test_hidden_agent_leaves_catalog_but_existing_deployments_work(self) -> None:
        deployment = self.deploy("voiceover")
        self.client.force_authenticate(self.owner)
        self.client.put(reverse("admin_agent_recipe", kwargs={"slug": "voiceover"}), {"isActive": False}, format="json")
        self.client.force_authenticate(self.user)
        self.assertNotIn("voiceover", [a["slug"] for a in self.client.get(reverse("agent_catalog")).data])
        self.assertEqual(self.start(deployment, text="Still works").status_code, 201)


class RetryAndAdminRunTests(_AgentAPITestCase):
    def _failed_run(self) -> AgentRun:
        deployment = self.deploy("script-writer")
        run_id = self.start(deployment).data["id"]
        run = AgentRun.objects.get(id=run_id)
        engine.fail(run, "Broke.")  # refunds
        run.refresh_from_db()
        return run

    def test_user_retry_charges_again_and_requeues(self) -> None:
        run = self._failed_run()
        self.user.refresh_from_db()
        before = self.user.credits_remaining
        url = reverse("agent_run_action", kwargs={"project_id": self.project.id, "deployment_id": run.deployment_id,
                                                  "run_id": run.id, "action": "retry"})
        self.assertEqual(self.client.post(url).data["status"], "queued")
        self.user.refresh_from_db()
        self.assertEqual(self.user.credits_remaining, before - run.credits_reserved)
        self.assertEqual(self.client.post(url).status_code, 400)  # not failed any more

    def test_admin_sees_runs_and_can_cancel_with_refund(self) -> None:
        deployment = self.deploy("script-writer")
        run_id = self.start(deployment).data["id"]
        self.user.refresh_from_db()
        before = self.user.credits_remaining
        owner = User.objects.create_superuser(email="boss@example.com", password="Password123!",
                                              first_name="B", last_name="O")
        self.client.force_authenticate(owner)
        data = self.client.get(reverse("admin_agent_runs")).data
        self.assertEqual(data["summary"]["inProgress"], 1)
        self.assertEqual(data["runs"][0]["user"], "agent@example.com")
        cancel = reverse("admin_agent_run_action", kwargs={"run_id": run_id, "action": "cancel"})
        self.assertEqual(self.client.post(cancel).data["status"], "failed")
        self.assertEqual(self.client.post(cancel).status_code, 400)
        self.user.refresh_from_db()
        self.assertGreater(self.user.credits_remaining, before)


class ScheduleTests(SimpleTestCase):
    def test_next_slot_respects_days_time_and_timezone(self) -> None:
        from datetime import datetime, timezone as dt_tz

        from agents.runs import next_slot

        sched = {"days": [0, 2], "time": "09:00", "tz": "Asia/Karachi"}  # Mon & Wed 09:00 PKT (UTC+5)
        tue_noon_utc = datetime(2026, 10, 13, 12, 0, tzinfo=dt_tz.utc)  # Tuesday
        self.assertEqual(next_slot(sched, tue_noon_utc), datetime(2026, 10, 14, 4, 0, tzinfo=dt_tz.utc))
        wed_slot = datetime(2026, 10, 14, 4, 0, tzinfo=dt_tz.utc)
        self.assertEqual(next_slot(sched, wed_slot), datetime(2026, 10, 19, 4, 0, tzinfo=dt_tz.utc))  # next Monday
        self.assertIsNone(next_slot({}, tue_noon_utc))

    def test_clean_schedule_rejects_bad_values(self) -> None:
        from agents.runs import clean_schedule

        self.assertEqual(clean_schedule({"days": [4, 0, 0], "time": "18:30", "tz": "Europe/London"}),
                         {"days": [0, 4], "time": "18:30", "tz": "Europe/London"})
        for bad in ({"days": [], "time": "09:00"}, {"days": [7], "time": "09:00"}, {"days": [1], "time": "9am"},
                    {"days": [1], "time": "09:00", "tz": "Mars/Base"}):
            with self.assertRaises(ValueError):
                clean_schedule(bad)


class AutopilotTests(_AgentAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.deployment = self.deploy(config={"niche": "coffee facts"})
        self.url = reverse("agent_deployment", kwargs={"project_id": self.project.id, "deployment_id": self.deployment.id})

    def enable(self, **extra):
        payload = {"autopilot": True, "schedule": {"days": [0, 1, 2, 3, 4, 5, 6], "time": "09:00", "tz": "UTC"}, **extra}
        return self.client.patch(self.url, payload, format="json")

    def make_due(self):
        AgentDeployment.objects.filter(id=self.deployment.id).update(next_run_at=timezone.now() - timedelta(minutes=1))

    def test_enabling_plans_the_next_run(self) -> None:
        response = self.enable(topicQueue=["first topic", "second topic"])
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["autopilot"])
        self.assertIsNotNone(response.data["nextRunAt"])
        off = self.client.patch(self.url, {"autopilot": False}, format="json").data
        self.assertIsNone(off["nextRunAt"])

    def test_autopilot_needs_topics_or_a_niche_and_a_topic_agent(self) -> None:
        self.deployment.config = {}
        self.deployment.save()
        self.assertIn("niche", self.enable().data["message"])
        self.assertEqual(self.enable(topicQueue=["a topic"]).status_code, 200)
        voice = self.deploy("voiceover")
        url = reverse("agent_deployment", kwargs={"project_id": self.project.id, "deployment_id": voice.id})
        bad = self.client.patch(url, {"autopilot": True, "schedule": {"days": [1], "time": "09:00"}}, format="json")
        self.assertIn("topic", bad.data["message"])

    def test_due_slot_starts_one_run_using_the_queue(self) -> None:
        from agents.runs import run_due

        self.enable(topicQueue=["first topic", "second topic"])
        self.make_due()
        self.assertEqual(run_due(), 1)
        self.assertEqual(run_due(), 0)  # slot already taken and re-planned into the future
        run = AgentRun.objects.get(deployment=self.deployment)
        self.assertEqual(run.input, {"topic": "first topic"})
        self.deployment.refresh_from_db()
        self.assertEqual(self.deployment.topic_queue, ["second topic"])
        self.assertGreater(self.deployment.next_run_at, timezone.now())

    def test_empty_queue_runs_with_an_auto_topic(self) -> None:
        from agents.runs import run_due

        self.enable()
        self.make_due()
        run_due()
        run = AgentRun.objects.get(deployment=self.deployment)
        self.assertEqual(run.input, {"topic": "", "auto": True})
        with override_settings(AGENTS_DRY_RUN=True):
            self.assertEqual(steps._topic(run), "coffee facts #1")
        run.refresh_from_db()
        self.assertEqual(run.input["topic"], "coffee facts #1")  # picked once, then kept

    @patch("agents.providers.requests.post")
    def test_auto_topic_avoids_recent_topics(self, post) -> None:
        AgentRun.objects.create(deployment=self.deployment, project=self.project, user=self.user,
                                input={"topic": "Why espresso has crema"})
        run = AgentRun.objects.create(deployment=self.deployment, project=self.project, user=self.user,
                                      input={"topic": "", "auto": True})
        post.return_value = MagicMock(json=lambda: {"candidates": [{"content": {"parts": [{"text": '{"topic": "Decaf myths"}'}]}}]})
        self.assertEqual(steps._topic(run), "Decaf myths")
        self.assertIn("Why espresso has crema", post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"])

    def test_skipped_slot_leaves_a_note(self) -> None:
        from agents.runs import run_due

        self.enable()
        self.user.credits_remaining = Decimal("0")
        self.user.save(update_fields=["credits_remaining"])
        self.make_due()
        self.assertEqual(run_due(), 0)
        self.deployment.refresh_from_db()
        self.assertIn("not enough credits", self.deployment.autopilot_note)
        self.assertGreater(self.deployment.next_run_at, timezone.now())  # tries again next slot

    def test_paused_agent_is_not_scheduled(self) -> None:
        from agents.runs import run_due

        self.enable()
        self.make_due()
        AgentDeployment.objects.filter(id=self.deployment.id).update(status="paused")
        self.assertEqual(run_due(), 0)

    def test_inbox_lists_runs_waiting_for_the_user(self) -> None:
        AgentRun.objects.create(deployment=self.deployment, project=self.project, user=self.user,
                                input={"topic": "t"}, status="needs_review", step="script")
        AgentRun.objects.create(deployment=self.deployment, project=self.project, user=self.user,
                                input={"topic": "u"}, status="failed", error="Broke.", finished_at=timezone.now())
        AgentRun.objects.create(deployment=self.deployment, project=self.project, user=self.user,
                                input={"topic": "v"}, status="approved")
        data = self.client.get(reverse("agent_inbox", kwargs={"project_id": self.project.id})).data
        self.assertEqual(data["waiting"], 1)
        self.assertEqual({i["status"] for i in data["items"]}, {"needs_review", "failed"})
