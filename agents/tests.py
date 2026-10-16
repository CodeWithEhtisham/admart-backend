import json
import re
import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

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
# Tests never depend on the developer's .env. Real (non-dry) mode with fake keys (every HTTP call
# is patched), no stock, no music.
HERMETIC = {
    "AGENTS_DRY_RUN": False, "OPENROUTER_API_KEY": "k", "FAL_KEY": "k", "PEXELS_API_KEY": "",
    "AGENTS_OPENROUTER_MODELS": "m:free", "AGENTS_LLM_USD_PER_RUN": "0.002",
    "AGENTS_MUSIC_DIR": "/nonexistent-agent-music", "GEMINI_API_KEY": "",
}


def chat(content, annotations=None):
    """A fake OpenRouter chat completion."""
    message = {"content": content, "annotations": annotations or []}
    return MagicMock(ok=True, status_code=200, json=lambda: {"choices": [{"message": message}]})


def fake_fal(fal, result):
    fal.submit.return_value = MagicMock(status_url="s", response_url="r")
    fal.status.return_value = {"status": "COMPLETED"}
    fal.result.return_value = result


SCRIPT_JSON = ('{"title":"T","description":"Facts.","tags":["coffee"],"scenes":[{"narration":"a","image_prompt":"b"},'
               '{"narration":"c","image_prompt":"d"},{"narration":"e","image_prompt":"f"}]}')


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

    def test_stock_scene_without_a_picture_idea_falls_back_to_its_search(self) -> None:
        scenes = [{"narration": f"line {i}", "visual": "stock", "stock_query": f"query {i}", "image_prompt": ""} for i in range(3)]
        out = steps.clean_script({"scenes": scenes}, "x")
        self.assertEqual([s["image_prompt"] for s in out["scenes"]], ["query 0", "query 1", "query 2"])

    def test_script_gets_thumbnail_text_and_a_title_check(self) -> None:
        scenes = [{"narration": f"line {i}", "image_prompt": "p"} for i in range(3)]
        out = steps.clean_script({"title": "The most amazing crema facts you will ever hear today",
                                  "thumbnail_text": "crema facts revealed now today", "scenes": scenes}, "x")
        self.assertEqual(out["thumbnail_text"], "crema facts revealed now")
        checks = " ".join(out["title_check"])
        self.assertIn("amazing", checks)
        self.assertIn("repeats the title", checks)

    def test_concepts_keep_their_best_hook_best_concept_first(self) -> None:
        weak, strong = "Today we talk about coffee.", "Your espresso is lying to you: crema hides a stale bean for 25 seconds."
        out = steps.clean_concepts({"concepts": [
            {"title": "A", "hooks": [weak], "formula": "Made Up"},
            {"title": "B", "hooks": [weak, strong], "formula": "The Mistake"},
        ]})
        self.assertEqual([c["title"] for c in out], ["B", "A"])
        self.assertEqual(out[0]["hook"], strong)
        self.assertEqual((out[0]["formula"], out[1]["formula"]), ("The Mistake", ""))
        self.assertGreater(out[0]["score"], out[1]["score"])
        self.assertTrue(out[1]["fix"])

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
    def test_paid_text_models_raise_the_quote(self, _prices) -> None:
        free = estimate_credits(BUILTIN_AGENTS["script-writer"], {})
        with override_settings(AGENTS_LLM_USD_PER_RUN="0.05"):
            self.assertGreater(estimate_credits(BUILTIN_AGENTS["script-writer"], {}), free)


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
        self.assertIn("score", run.output["concept"])  # rewritten hooks are scored again

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
    """Real-mode steps with OpenRouter and fal faked (no paid calls)."""

    def _run(self, agent_type="youtube-shorts", run_input=None) -> AgentRun:
        deployment = self.deploy(agent_type)
        return AgentRun.objects.create(
            deployment=deployment, project=self.project, user=self.user, input=run_input or {"topic": "coffee"}
        )

    @patch("agents.providers.requests.post")
    def test_script_uses_openrouter_and_brand(self, post) -> None:
        post.return_value = chat(SCRIPT_JSON)
        run = self._run()
        run.output = {"concept": {"title": "C", "hook": "Did you know?", "angle": "facts"}, "research": {"notes": "n"}}
        steps.step_script(run)
        self.assertEqual(len(run.output["scenes"]), 3)
        body = post.call_args.kwargs["json"]
        self.assertIn("openrouter.ai", post.call_args.args[0])
        self.assertEqual(body["models"], ["m:free"])
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertIn("Did you know?", body["messages"][1]["content"])
        self.assertIn("Bean Co", body["messages"][1]["content"])
        steps.step_script(run)  # already done: no second call
        self.assertEqual(post.call_count, 1)

    @patch("agents.providers.requests.post")
    def test_garbled_json_is_retried_once(self, post) -> None:
        post.side_effect = [chat("not json"), chat('```json\n{"ok": true}\n```')]
        self.assertEqual(providers.text("sys", "user"), {"ok": True})
        post.side_effect = [chat("nope"), chat("still nope")]
        with self.assertLogs("agents.providers", "WARNING"), self.assertRaisesMessage(RuntimeError, "AI writer service"):
            providers.text("sys", "user")

    @patch("agents.providers.requests.post")
    def test_research_uses_web_search_and_keeps_sources(self, post) -> None:
        post.return_value = chat("- Fact one\n- Fact two", [{"type": "url_citation", "url_citation": {"url": "https://x.org", "title": "X"}}])
        run = self._run()
        steps.step_research(run)
        self.assertEqual(run.output["research"]["sources"], [{"title": "X", "uri": "https://x.org"}])
        self.assertEqual(post.call_args.kwargs["json"]["plugins"][0]["id"], "web")  # always searches

    @patch("agents.providers.requests.post")
    def test_research_without_search_credit_still_runs(self, post) -> None:
        post.side_effect = [MagicMock(ok=False, status_code=402), chat("- Fact")]
        run = self._run()
        with self.assertLogs("agents.providers", "WARNING"):
            steps.step_research(run)
        self.assertEqual(run.output["research"]["notes"], "- Fact")
        self.assertNotIn("plugins", post.call_args.kwargs["json"])

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
        fake_fal(fal, {"images": [{"url": "https://cdn/x.png"}]})
        get.return_value = MagicMock(content=b"\x89PNG fake", headers={"Content-Type": "image/png"})
        run = self._run()
        run.output = {"scenes": [{"narration": "a", "image_prompt": "b"}, {"narration": "c", "image_prompt": "d"}]}
        steps.step_visuals(run)
        steps.step_visuals(run)
        self.assertEqual(fal.submit.call_count, 2)
        self.assertTrue((Path(self.media) / run.output["scenes"][1]["image"]).exists())

    @patch("agents.providers.requests.get")
    @patch("agents.providers.fal_client")
    def test_voice_uses_the_chosen_kokoro_voice_and_records_duration(self, fal, get) -> None:
        sample = Path(self.media) / "sample.mp3"
        render.silent_audio(sample, 2.0)
        fake_fal(fal, {"audio": {"url": "https://cdn/a.wav"}})
        get.return_value = MagicMock(content=sample.read_bytes())
        run = self._run("voiceover", {"text": "Hello world"})
        run.deployment.config = {"voice": "george", "pace": "calm"}
        steps.step_voice(run)
        self.assertAlmostEqual(run.output["scenes"][0]["duration"], 2.0, delta=0.2)
        model, args = fal.submit.call_args.args
        self.assertEqual(model, "fal-ai/kokoro/british-english")
        self.assertEqual(args, {"prompt": "Hello world", "voice": "bm_george", "speed": 0.9})

    @patch("agents.providers.fal_client")
    def test_captions_use_whisper_word_timings_or_fall_back(self, fal) -> None:
        audio = Path(self.media) / "a.mp3"
        render.silent_audio(audio, 2.0)
        fake_fal(fal, {"chunks": [{"text": " Hello", "timestamp": [0.1, 0.6]}, {"text": "world", "timestamp": [0.6, None]}]})
        run = self._run("voiceover", {"text": "Hello"})
        run.output = {"scenes": [{"narration": "Hello world", "audio": "a.mp3", "duration": 2.0}]}
        steps.step_captions(run)
        self.assertEqual(run.output["scenes"][0]["words"], [{"word": "Hello", "start": 0.1, "end": 0.6},
                                                            {"word": "world", "start": 0.6, "end": 0.6}])
        self.assertEqual(fal.submit.call_args.args[1]["chunk_level"], "word")
        fal.submit.side_effect = RuntimeError("down")
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

    def test_missing_keys_give_a_clear_message(self) -> None:
        run = self._run("voiceover", {"text": "Hi"})
        with override_settings(FAL_KEY=""), self.assertRaisesMessage(RuntimeError, "No voice service is set up"):
            steps.step_voice(run)
        with override_settings(OPENROUTER_API_KEY=""), self.assertRaisesMessage(RuntimeError, "No AI writer service"):
            providers.text("sys", "user")

    def test_style_settings_feed_the_script(self) -> None:
        from agents.registry import VOICES, voice_settings

        config = {"voice": "fenrir", "pace": "calm", "tone": "fun", "length": 30}
        self.assertEqual(voice_settings(config), (VOICES["fenrir"], 0.9))
        self.assertEqual(voice_settings({"voice": "nope"}), (VOICES["heart"], 1.0))
        lines = steps._style_lines(MagicMock(deployment=MagicMock(config=config)))
        self.assertIn("playful", lines)
        self.assertIn("at most 65 words", lines)
        self.assertIn("about 45 seconds", steps._style_lines(MagicMock(deployment=MagicMock(config={}))))


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

    def test_each_step_logs_time_and_services(self) -> None:
        from agents import providers

        run = self._queued()
        with patch.dict(steps.STEPS, {"script": MagicMock(side_effect=lambda r: providers.note("openrouter"))}):
            engine.process(engine.claim_next())
        run.refresh_from_db()
        entry = run.output["log"]["script"]
        self.assertEqual(entry["providers"], ["openrouter"])
        self.assertLessEqual(entry["startedAt"], entry["finishedAt"])
        engine._log(run, "script", timezone.now(), [])  # a skipped (already done) step keeps its entry
        self.assertEqual(run.output["log"]["script"], entry)

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
        for action in ("continue", "regenerate", "approve"):
            url = reverse("agent_run_action", kwargs={"project_id": self.project.id, "deployment_id": deployment.id,
                                                      "run_id": run_id, "action": action})
            self.assertEqual(self.client.post(url, {}, format="json").status_code, 400, action)
        url = reverse("agent_run_action", kwargs={"project_id": self.project.id, "deployment_id": deployment.id,
                                                  "run_id": run_id, "action": "discard"})
        self.assertEqual(self.client.post(url, {}, format="json").data["status"], "discarded", "a queued run is cancelled")

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
        self.assertIn("finish' needs render", self.check(steps=["script", "finish"]))
        self.assertIn("Video steps", self.check(steps=["prepare", "transcribe"]))
        self.assertIn("Video steps", self.check(steps=["prepare", "script"], input_kind="video"))

    def test_video_editor_recipe_is_valid(self) -> None:
        editor = BUILTIN_AGENTS["video-editor"]
        self.assertIsNone(self.check(steps=list(editor.steps), kind="large", review=True, input_kind="video"))


class RecipeTests(_AgentAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.owner = User.objects.create_superuser(email="boss@example.com", password="Password123!",
                                                   first_name="B", last_name="O")
        self.staff = User.objects.create_user(email="staff@example.com", password="Password123!",
                                              first_name="S", last_name="T", is_staff=True)

    def test_builtin_recipes_are_seeded_and_listed(self) -> None:
        slugs = [a["slug"] for a in self.client.get(reverse("agent_catalog")).data]
        self.assertEqual(slugs, ["youtube-shorts", "trend-finder", "growth-report", "video-editor", "cross-poster", "clip-maker", "script-writer", "voiceover"])
        editor = next(a for a in self.client.get(reverse("agent_catalog")).data if a["slug"] == "video-editor")
        self.assertEqual((editor["inputKind"], editor["creditUnit"], len(editor["audioLevels"])), ("video", "minute", 3))
        clip = next(a for a in self.client.get(reverse("agent_catalog")).data if a["slug"] == "clip-maker")
        self.assertEqual([c["id"] for c in clip["captionStyles"]], ["classic", "bold", "boxed", "minimal"])
        self.assertEqual(clip["clipLanguages"][0], {"id": "auto", "label": "Detect automatically"})
        self.assertIn({"id": "ur", "label": "Urdu"}, clip["clipLanguages"])
        self.assertEqual(clip["layouts"][0]["id"], "auto")

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
        post.return_value = chat(SCRIPT_JSON)
        deployment = self.deploy("script-writer")
        run = AgentRun.objects.create(deployment=deployment, project=self.project, user=self.user, input={"topic": "x"})
        steps.step_script(run)
        self.assertEqual(post.call_args.kwargs["json"]["messages"][0]["content"], "CUSTOM SCRIPT PROMPT")

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
        post.return_value = chat('{"topic": "Decaf myths"}')
        self.assertEqual(steps._topic(run), "Decaf myths")
        self.assertIn("Why espresso has crema", post.call_args.kwargs["json"]["messages"][1]["content"])

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


# ── Video Editor ──────────────────────────────────────────────────────────

from agents import video_edit  # noqa: E402


class CutPlanningTests(SimpleTestCase):
    def test_overlapping_cuts_merge_and_slivers_are_absorbed(self) -> None:
        cuts = [{"start": 1.0, "end": 2.0, "reasons": ["pause"]}, {"start": 1.8, "end": 2.5, "reasons": ["filler"]},
                {"start": 2.6, "end": 3.0, "reasons": ["retake"]}, {"start": 0.0, "end": 0.01, "reasons": ["pause"]},
                {"start": 9.8, "end": 9.9, "reasons": ["pause"]}]
        out = video_edit.merge_cuts(cuts, 10.0)
        self.assertEqual([(c["start"], c["end"]) for c in out], [(1.0, 3.0), (9.8, 10.0)])  # 0.1 s gaps absorbed
        self.assertEqual(out[0]["reasons"], ["filler", "pause", "retake"])
        self.assertFalse(out[0]["keep"])

    def test_kept_segments_skip_cuts_and_snap_to_frames(self) -> None:
        cuts = [{"start": 1.01, "end": 2.0, "keep": False}, {"start": 3.0, "end": 4.0, "keep": True}]
        self.assertEqual(video_edit.kept_segments(cuts, 5.0), [(0.0, 1.0), (2.0, 5.0)])

    def test_words_are_retimed_to_the_edit(self) -> None:
        words = [{"word": "a", "start": 0.2, "end": 0.5}, {"word": "cut", "start": 1.2, "end": 1.5},
                 {"word": "b", "start": 2.1, "end": 2.4}]
        out = video_edit.retime(words, [(0.0, 1.0), (2.0, 3.0)])
        self.assertEqual(out, [{"word": "a", "start": 0.2, "end": 0.5}, {"word": "b", "start": 1.1, "end": 1.4}])

    def test_fillers_never_clip_neighbouring_words(self) -> None:
        words = [{"word": "so", "start": 0.0, "end": 0.3}, {"word": "Um,", "start": 0.32, "end": 0.6},
                 {"word": "like", "start": 0.62, "end": 0.8}]
        self.assertEqual(video_edit.filler_cuts(words, "normal", 1.0), [{"start": 0.3, "end": 0.62, "reasons": ["filler"]}])
        self.assertEqual(len(video_edit.filler_cuts(words, "tight", 1.0)), 2)

    @patch("agents.video_edit.providers.text")
    def test_ai_review_validates_retakes_and_fixes(self, text) -> None:
        words = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4} for i, w in enumerate("I went I went to Admrt".split())]
        text.return_value = {"retakes": [{"from": 0, "to": 1}, {"from": 4, "to": 99}, {"from": "x"}],
                             "fixes": [{"index": 5, "word": "Admart"}, {"index": 50, "word": "no"}, {"index": 2, "word": "I"}]}
        run = MagicMock(project=MagicMock(brand_settings={}, brand_name="Admart", brand_industry=""),
                        deployment=MagicMock(config={}))
        cuts, fixes = video_edit.ai_review(run, words, "tight", 20.0)
        self.assertEqual([(c["start"], round(c["end"], 3)) for c in cuts], [(0.0, 0.94)])
        self.assertEqual(fixes, [{"index": 5, "from": "Admrt", "to": "Admart"}])


@override_settings(**HERMETIC)
class VideoEstimateTests(SimpleTestCase):
    @NO_PRICES
    def test_video_price_follows_length_and_audio_level(self, _prices) -> None:
        editor = BUILTIN_AGENTS["video-editor"]
        one, three = ({"seconds": s} for s in (60, 180))
        self.assertGreater(estimate_credits(editor, three), estimate_credits(editor, one))
        basic, standard, studio = (estimate_credits(editor, three, {"audio": a}) for a in ("basic", "standard", "studio"))
        self.assertLess(basic, standard)
        self.assertLess(standard, studio)


class VideoEditorPipelineTests(_AgentAPITestCase):
    """Upload → plan → review → render, with a real FFmpeg render at zero cost."""

    dry_run = True
    _action = DryRunPipelineTests._action
    _work = DryRunPipelineTests._work

    def _upload(self, seconds=6, size="1280x720") -> "LibraryAsset":
        from content.models import LibraryAsset

        folder = Path(self.media) / "projects" / str(self.project.id) / "library"
        folder.mkdir(parents=True)
        clip = folder / "clip.mp4"
        # Tone with a 2-second silent gap in the middle (2 s to 4 s).
        render._run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc2=s={size}:d={seconds}:r=30", "-f", "lavfi",
                     "-i", f"aevalsrc='if(between(t,2,4),0,0.5*sin(440*2*PI*t))':s=44100:d={seconds}",
                     "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(clip)])
        return LibraryAsset.objects.create(
            project=self.project, user=self.user, media_type="video", title="My clip", status="ready",
            source_url=f"http://testserver/media/projects/{self.project.id}/library/clip.mp4", capability="upload",
        )

    def test_review_keep_a_cut_then_render(self) -> None:
        asset = self._upload()
        deployment = self.deploy("video-editor", config={"format": "1:1", "audio": "basic"})
        response = self.start(deployment, assetId=str(asset.id))
        self.assertEqual(response.status_code, 201, response.data)
        run_id = response.data["id"]

        self._work()
        run = AgentRun.objects.get(id=run_id)
        self.assertEqual((run.status, run.step), ("needs_review", "edit"), run.error)
        pause = next(c for c in run.output["cuts"] if "pause" in c["reasons"])
        self.assertAlmostEqual(pause["start"], 2.2, delta=0.15)
        self.assertAlmostEqual(pause["end"], 3.8, delta=0.15)
        detail = self.client.get(self.runs_url(deployment)).data[0]
        self.assertTrue(detail["sourceUrl"].endswith(".mp4"))
        self.assertEqual(detail["audioLevelUsed"], "basic")

        cuts = [{**c, "keep": True} for c in run.output["cuts"]]  # keep everything: no cuts
        self.assertEqual(self._action(deployment, run_id, "continue", {"cuts": [{"start": 9, "end": 99}]}).status_code, 400)
        self._action(deployment, run_id, "continue", {"cuts": cuts, "captions": [{"index": 0, "word": "Hello"}]})
        self._work()
        run.refresh_from_db()
        self.assertEqual((run.status, run.step), ("needs_review", "final"), run.error)
        self.assertEqual((run.output["width"], run.output["height"]), (1080, 1080))
        self.assertAlmostEqual(run.output["duration"], 6.0, delta=0.2)
        self.assertEqual(run.output["captions"][0]["word"], "Hello")
        self.assertTrue(run.output["thumbnail"].endswith("thumb.jpg"))
        self.assertEqual((run.library_asset.width, run.library_asset.height), (1080, 1080))

    def test_cuts_shorten_the_video(self) -> None:
        asset = self._upload()
        deployment = self.deploy("video-editor", config={"checkpoints": "final", "audio": "basic"})
        run_id = self.start(deployment, assetId=str(asset.id)).data["id"]
        self._work()
        run = AgentRun.objects.get(id=run_id)
        self.assertEqual((run.status, run.step), ("needs_review", "final"), run.error)
        self.assertEqual((run.output["width"], run.output["height"]), (1080, 1920))
        self.assertAlmostEqual(run.output["duration"], 6.0 - 1.6, delta=0.25)  # the 2 s pause kept to 0.4 s
        self.assertAlmostEqual(run.output["removed_seconds"], 1.6, delta=0.25)

    def test_only_this_projects_short_videos(self) -> None:
        deployment = self.deploy("video-editor")
        self.assertEqual(self.start(deployment, assetId="not-a-uuid").status_code, 400)
        other = Project.objects.create(owner=self.user, name="Other")
        from content.models import LibraryAsset

        foreign = LibraryAsset.objects.create(project=other, user=self.user, media_type="video", source_url="x")
        self.assertEqual(self.start(deployment, assetId=str(foreign.id)).status_code, 400)
        asset = self._upload()
        with patch("agents.views.probe", return_value={"duration": 240}):
            response = self.start(deployment, assetId=str(asset.id))
        self.assertEqual(response.data["code"], "VIDEO_TOO_LONG")


class VideoCleanAudioTests(_AgentAPITestCase):
    @patch("agents.video_edit.providers.clean_audio", side_effect=RuntimeError("fal down"))
    def test_paid_cleanup_falls_back_to_the_free_filter(self, _clean) -> None:
        deployment = self.deploy("video-editor", config={"audio": "studio"})
        run = AgentRun.objects.create(deployment=deployment, project=self.project, user=self.user, input={})
        folder, rel = steps.media_dir(run)
        render.silent_audio(folder / "audio.mp3", 1.0)
        run.output = {"audio": f"{rel}/audio.mp3"}
        with self.assertLogs("agents.video_edit", "WARNING"):
            video_edit.step_clean_audio(run)
        self.assertEqual((run.output["audio_level"], run.output["audio_level_used"]), ("studio", "basic"))
        self.assertTrue(run.output["audio_fallback"])
        self.assertTrue((folder / "audio-clean.mp3").exists())


from agents import cross_post  # noqa: E402
from projects.models import PublishJob, SocialAccount  # noqa: E402


class CrossPosterTests(_AgentAPITestCase):
    """Library video → posts → review → post, with the platform publishers mocked."""

    dry_run = True
    _action = DryRunPipelineTests._action
    _work = DryRunPipelineTests._work
    _upload = VideoEditorPipelineTests._upload

    def setUp(self) -> None:
        super().setUp()
        for platform in ("youtube", "instagram"):
            SocialAccount.objects.create(project=self.project, platform=platform)
        self.calls = []
        fake = lambda name: lambda account, **kw: self.calls.append((name, kw)) or {"status": "succeeded"}  # noqa: E731
        publishers = patch.dict(cross_post.PUBLISHERS, {"youtube": fake("youtube"), "instagram": fake("instagram")})
        publishers.start()
        self.addCleanup(publishers.stop)

    def _to_review(self, size="720x1280"):
        asset = self._upload(size=size)
        deployment = self.deploy("cross-poster")
        response = self.start(deployment, assetId=str(asset.id))
        self.assertEqual(response.status_code, 201, response.data)
        self._work()
        run = AgentRun.objects.get(id=response.data["id"])
        self.assertEqual((run.status, run.step), ("needs_review", "post"), run.error)
        return deployment, run

    def test_review_then_post_to_the_chosen_platforms(self) -> None:
        deployment, run = self._to_review()
        self.assertEqual(run.output["platforms"], ["youtube", "instagram"])
        self.assertTrue(run.output["short"])
        self.assertIn("#Shorts", run.output["posts"]["youtube"]["description"])
        self.assertTrue(run.output["thumbnail"].endswith("thumb.jpg"))
        detail = self.client.get(self.runs_url(deployment)).data[0]
        self.assertEqual(detail["posts"]["instagram"]["caption"], "My clip")

        self.assertEqual(self._action(deployment, run.id, "continue", {"platforms": []}).status_code, 400)
        self._action(deployment, run.id, "continue", {
            "platforms": ["youtube", "facebook"],  # facebook isn't connected: ignored
            "posts": {"youtube": {"title": "My new title", "privacy": "unlisted", "tags": ["#coffee"]}},
        })
        self._work()
        run.refresh_from_db()
        self.assertEqual(run.status, "succeeded", run.error)
        self.assertEqual([name for name, _ in self.calls], ["youtube"])
        sent = self.calls[0][1]
        self.assertEqual((sent["title"], sent["privacy"], sent["tags"]), ("My new title", "unlisted", ["coffee"]))
        self.assertFalse(sent["synthetic_media"])  # an upload, not AI-made
        job = PublishJob.objects.get(id=run.output["publish_job"])
        self.assertEqual((job.status, job.platforms), ("succeeded", ["youtube"]))

    def test_retry_reposts_only_what_failed_and_never_an_interrupted_upload(self) -> None:
        deployment, run = self._to_review(size="1280x720")
        self.assertFalse(run.output["short"])
        self._action(deployment, run.id, "continue", {"platforms": ["youtube", "instagram"]})
        run.refresh_from_db()
        run.output["posted"] = {"youtube": {"status": "running"}}  # the worker died mid-upload
        run.save()
        with patch.dict(cross_post.PUBLISHERS, {"instagram": MagicMock(side_effect=RuntimeError("IG down"))}):
            self._work()
        run.refresh_from_db()
        self.assertEqual(run.status, "failed")  # nothing confirmed posted: refunded
        self.assertEqual(run.output["posted"]["youtube"]["status"], "unknown")
        self.assertEqual(run.output["posted"]["instagram"]["error"], "IG down")

        self._action(deployment, run.id, "retry")
        self._work()
        run.refresh_from_db()
        self.assertEqual(run.status, "succeeded", run.error)
        self.assertEqual([name for name, _ in self.calls], ["instagram"])  # youtube never re-uploaded
        self.assertEqual(PublishJob.objects.get(id=run.output["publish_job"]).status, "partial")

    def test_scheduled_post_waits_and_can_be_cancelled(self) -> None:
        deployment, run = self._to_review()
        past = (timezone.now() - timedelta(hours=1)).isoformat()
        self.assertEqual(self._action(deployment, run.id, "continue",
                                      {"platforms": ["youtube"], "postAt": past}).status_code, 400)
        at = timezone.now() + timedelta(days=1)
        self._action(deployment, run.id, "continue", {"platforms": ["youtube"], "postAt": at.isoformat()})
        self._work()
        run.refresh_from_db()
        self.assertEqual((run.status, run.step), ("queued", "wait"))
        self.assertEqual(run.locked_until, at)
        self._work()  # not due yet: nothing happens
        self.assertEqual(self.calls, [])
        self.assertEqual(self.start(deployment, assetId=run.input["assetId"]).status_code, 201)  # not "busy"

        self.assertEqual(self._action(deployment, run.id, "discard").status_code, 200)
        run.refresh_from_db()
        self.assertEqual(run.status, "discarded")

    def test_scheduled_post_goes_out_when_due(self) -> None:
        deployment, run = self._to_review()
        self._action(deployment, run.id, "continue", {"platforms": ["instagram"],
                                                      "postAt": (timezone.now() + timedelta(minutes=5)).isoformat()})
        self._work()
        AgentRun.objects.filter(id=run.id).update(locked_until=timezone.now() - timedelta(seconds=1))
        run.output["post_at"] = (timezone.now() - timedelta(seconds=1)).isoformat()
        AgentRun.objects.filter(id=run.id).update(output=run.output | {"chosen": ["instagram"], "post_ok": True})
        self._work()
        run.refresh_from_db()
        self.assertEqual(run.status, "succeeded", run.error)
        self.assertEqual(self.calls[0][1]["caption"], "My clip")

    def test_scheduling_needs_the_plan(self) -> None:
        self.user.plan = "basic"
        self.user.save()
        deployment, run = self._to_review()
        response = self._action(deployment, run.id, "continue", {
            "platforms": ["youtube"], "postAt": (timezone.now() + timedelta(days=1)).isoformat()})
        self.assertEqual(response.status_code, 400)
        self.assertIn("plan", response.data["message"])

    def test_needs_a_connected_platform(self) -> None:
        SocialAccount.objects.all().delete()
        asset = self._upload()
        response = self.start(self.deploy("cross-poster"), assetId=str(asset.id))
        self.assertEqual(response.data["code"], "NOT_CONNECTED")


@override_settings(**HERMETIC)
class ScriptLengthTests(_AgentAPITestCase):
    @patch("agents.providers.requests.post")
    def test_a_long_script_is_rewritten_once(self, post) -> None:
        def script(words):
            return chat(json.dumps({"title": "T", "scenes": [{"narration": " ".join(["word"] * words), "visual": "image",
                                                              "image_prompt": "x"}] * 3}))
        post.side_effect = [script(40), script(20)]  # 120 words for a 30 s Short (limit 65), then 60
        deployment = self.deploy(config={"length": 30})
        run = AgentRun.objects.create(deployment=deployment, project=self.project, user=self.user, input={"topic": "t"})
        steps.step_script(run)
        self.assertEqual(post.call_count, 2)
        self.assertIn("at most 65 words", post.call_args.kwargs["json"]["messages"][1]["content"])
        self.assertEqual(sum(len(s["narration"].split()) for s in run.output["scenes"]), 60)


class TrendFinderTests(_AgentAPITestCase):
    def test_dry_run_lists_trends_with_scored_hooks(self) -> None:
        with override_settings(AGENTS_DRY_RUN=True):
            deployment = self.deploy("trend-finder")
            run_id = self.start(deployment, topic="home coffee brewing").data["id"]
            call_command("run_agents_worker", "--once", stdout=MagicMock())
        run = AgentRun.objects.get(id=run_id)
        self.assertEqual(run.status, "succeeded", run.error)
        detail = self.client.get(self.runs_url(deployment)).data[0]
        self.assertEqual(len(detail["trends"]), 5)
        self.assertIn("band", detail["trends"][0])
        self.assertEqual(detail["title"], "Trends in home coffee brewing")

    @patch("agents.providers.requests.post")
    def test_keeps_only_sources_the_search_returned(self, post) -> None:
        AgentRun.objects.create(deployment=self.deploy("youtube-shorts"), project=self.project, user=self.user,
                                input={"topic": "cold brew at home"})
        answer = {"trends": [
            {"topic": "Cloud coffee", "why_now": "Viral this week.", "hook": "You can make cloud coffee in 2 minutes.",
             "source": "https://real.example/cloud"},
            {"topic": "Bean prices", "why_now": "Up again.", "hook": "Your coffee costs more this month.",
             "source": "https://made-up.example/x"},
            "not a trend",
        ]}
        post.return_value = chat(json.dumps(answer), [{"type": "url_citation", "url_citation": {
            "url": "https://real.example/cloud", "title": "Cloud coffee"}}])
        deployment = self.deploy("trend-finder")
        run = AgentRun.objects.create(deployment=deployment, project=self.project, user=self.user,
                                      input={"topic": "home coffee"})
        steps.step_trends(run)
        trends = run.output["trends"]
        self.assertEqual([t["topic"] for t in trends], ["Cloud coffee", "Bean prices"])
        self.assertEqual(trends[0]["source"]["uri"], "https://real.example/cloud")
        self.assertIsNone(trends[1]["source"])  # a link the search didn't return is dropped
        sent = post.call_args.kwargs["json"]
        self.assertEqual(sent["plugins"][0]["id"], "web")
        self.assertIn("- cold brew at home", sent["messages"][1]["content"])  # avoids covered topics


class WorkerTests(_AgentAPITestCase):
    def _run_for(self, agent_type) -> AgentRun:
        deployment = self.deploy(agent_type)
        return AgentRun.objects.create(deployment=deployment, project=self.project, user=self.user, input={"topic": "x"})

    def test_worker_survives_a_locked_database(self) -> None:
        from django.db import OperationalError

        claim = MagicMock(side_effect=[OperationalError("database is locked"), None])
        with patch("agents.management.commands.run_agents_worker.claim_next", claim), \
                patch("agents.management.commands.run_agents_worker.run_due", return_value=0), \
                patch("agents.management.commands.run_agents_worker.time.sleep"), \
                self.assertLogs("agents.worker", "WARNING"):
            call_command("run_agents_worker", "--once")
        self.assertEqual(claim.call_count, 2)

    def test_claim_only_and_exclude_agent_types(self) -> None:
        script = self._run_for("script-writer")
        voice = self._run_for("voiceover")
        self.assertEqual(engine.claim_next(only=("voiceover",)).id, voice.id)
        self.assertIsNone(engine.claim_next(exclude=("script-writer",)))
        self.assertEqual(engine.claim_next().id, script.id)

    def test_worker_passes_its_agent_filter(self) -> None:
        claim = MagicMock(return_value=None)
        with patch("agents.management.commands.run_agents_worker.claim_next", claim), \
                patch("agents.management.commands.run_agents_worker.run_due", return_value=0):
            call_command("run_agents_worker", "--once", "--only", "clip-maker", "--exclude", "voiceover")
        claim.assert_called_with(only=["clip-maker"], exclude=["voiceover"])

    def test_keep_alive_extends_the_lease(self) -> None:
        run = self._run_for("script-writer")
        AgentRun.objects.filter(id=run.id).update(status="running", locked_until=timezone.now())
        steps.keep_alive(run)
        run.refresh_from_db()
        self.assertGreater(run.locked_until, timezone.now() + timedelta(minutes=14))


def _w(text: str, start: float, step: float = 0.5) -> list[dict]:
    """Words of `text`, one every `step` seconds from `start`."""
    return [{"word": w, "start": round(start + i * step, 3), "end": round(start + i * step + step * 0.8, 3)}
            for i, w in enumerate(text.split())]


class ClipHelperTests(SimpleTestCase):
    def test_youtube_links_are_normalised(self) -> None:
        from agents import clips

        canonical = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        for link in ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s", "youtu.be/dQw4w9WgXcQ?si=x",
                     "https://m.youtube.com/watch?v=dQw4w9WgXcQ", "https://youtube.com/shorts/dQw4w9WgXcQ",
                     "https://www.youtube.com/live/dQw4w9WgXcQ", " https://www.youtube.com/embed/dQw4w9WgXcQ "):
            self.assertEqual(clips.parse_youtube_url(link), canonical, link)
        for bad in ("https://vimeo.com/123", "https://www.youtube.com/playlist?list=PL1", "file:///etc/passwd",
                    "https://evil.com/watch?v=dQw4w9WgXcQ", "https://www.youtube.com.evil.com/watch?v=dQw4w9WgXcQ",
                    "https://www.youtube.com/watch?v=short", ""):
            self.assertIsNone(clips.parse_youtube_url(bad), bad)

    def test_long_audio_is_split_at_the_silence_nearest_each_mark(self) -> None:
        from agents import clips

        self.assertEqual(clips.chunk_bounds(500, []), [(0, 500)])
        bounds = clips.chunk_bounds(1500, [100.0, 590.0, 615.0, 1195.0], target=600, window=30)
        self.assertEqual(bounds, [(0, 590.0), (590.0, 1195.0), (1195.0, 1500)])
        self.assertEqual(clips.chunk_bounds(1300, [5.0], target=600, window=30), [(0, 600), (600, 1200), (1200, 1300)])

    def test_sentences_split_on_punctuation_and_long_gaps(self) -> None:
        from agents import clips

        words = _w("Coffee is great. Why? Because", 0) + _w("it wakes you up", 10)
        out = clips.sentences(words)
        self.assertEqual([s["text"] for s in out], ["Coffee is great.", "Why?", "Because", "it wakes you up"])
        self.assertEqual((out[0]["first"], out[0]["last"], out[0]["start"]), (0, 2, 0))
        self.assertEqual(out[3]["start"], 10)

    def test_clip_grows_to_the_minimum_and_ends_on_a_sentence(self) -> None:
        from agents import clips

        sents = [{"start": i * 5.0, "end": i * 5.0 + 4.5, "text": f"s{i}."} for i in range(20)]
        clip = clips.fit_clip(2, 3, sents, 15, 30, 100)  # 10 s of speech: too short
        self.assertEqual((clip["from"], clip["to"]), (2, 5))
        self.assertAlmostEqual(clip["start"], 9.75)  # 0.25 s lead-in, after the previous sentence
        self.assertAlmostEqual(clip["end"], 29.85)  # 0.35 s tail, before the next sentence
        clip = clips.fit_clip(0, 19, sents, 15, 30, 100)  # far too long: trimmed to whole sentences
        self.assertEqual((clip["from"], clip["to"]), (0, 5))
        self.assertEqual(clip["start"], 0)
        self.assertIsNone(clips.fit_clip(0, 0, [{"start": 0, "end": 50, "text": "x"}], 15, 30, 50))

    def test_overlapping_moments_keep_the_higher_score(self) -> None:
        from agents import clips

        kept = clips.dedupe([
            {"start": 0, "end": 30, "score": 60}, {"start": 10, "end": 40, "score": 90},
            {"start": 35, "end": 60, "score": 50}, {"start": 100, "end": 130, "score": 10},
        ])
        self.assertEqual([c["score"] for c in kept], [90, 50, 10])

    def test_punctuation_from_segments_is_put_back_on_words(self) -> None:
        from agents import clips

        words = _w("hello there how are you", 0)
        segments = [{"start": 0, "end": 1, "text": " Hello there."}, {"start": 1, "end": 3, "text": " How are you?"}]
        self.assertEqual([w["word"] for w in clips.punctuate(words, segments)],
                         ["Hello", "there.", "How", "are", "you?"])
        odd = [{"start": 0, "end": 3, "text": " Hello there, how are you doing?"}]  # counts differ: mark the end
        self.assertEqual(clips.punctuate(_w("hello there how are you", 0), odd)[-1]["word"], "you?")

    def test_length_limit_depends_on_the_plan(self) -> None:
        from agents import clips

        self.assertEqual(clips.max_seconds(MagicMock(plan="free")), 30 * 60)
        self.assertEqual(clips.max_seconds(MagicMock(plan="plus")), 2 * 60 * 60)


@override_settings(**HERMETIC, GROQ_API_KEY="g", CLIPS_TRANSCRIBE_PROVIDERS="groq,local,fal")
class ClipTranscribeTests(SimpleTestCase):
    def setUp(self) -> None:
        self.audio = Path(tempfile.mkdtemp()) / "chunk.mp3"
        self.addCleanup(shutil.rmtree, self.audio.parent, ignore_errors=True)
        self.audio.write_bytes(b"x")

    @patch("agents.clips.requests.post")
    def test_groq_words_are_punctuated_and_offset(self, post) -> None:
        from agents import clips

        post.return_value = MagicMock(status_code=200, json=lambda: {
            "words": [{"word": "Hi", "start": 0.0, "end": 0.4}, {"word": "there", "start": 0.5, "end": 0.9}],
            "segments": [{"start": 0, "end": 1, "text": " Hi there."}]})
        words, used, _heard = clips.transcribe_chunk(self.audio, offset=600, language="en")
        self.assertEqual(used, "groq")
        self.assertEqual(words, [{"word": "Hi", "start": 600.0, "end": 600.4}, {"word": "there.", "start": 600.5, "end": 600.9}])
        self.assertEqual(post.call_args.kwargs["data"]["timestamp_granularities[]"], ["word", "segment"])
        self.assertEqual(post.call_args.kwargs["data"]["language"], "en")  # one language for every piece

    @patch("agents.clips._local_words", return_value=None)
    @patch("agents.clips.providers._fal", return_value={"chunks": [{"text": "Yo.", "timestamp": [1.0, 1.5]}]})
    @patch("agents.clips.requests.post", side_effect=requests.ConnectionError("down"))
    def test_falls_back_to_the_next_service(self, _post, _fal, _local) -> None:
        from agents import clips

        with self.assertLogs("agents.clips", "WARNING"):
            words, used, _heard = clips.transcribe_chunk(self.audio, offset=0, language="en")
        self.assertEqual((words, used), ([{"word": "Yo.", "start": 1.0, "end": 1.5}], "fal"))

    @override_settings(GROQ_API_KEY="", FAL_KEY="", CLIPS_TRANSCRIBE_PROVIDERS="groq,fal")
    def test_no_service_is_a_clear_error(self) -> None:
        from agents import clips

        with self.assertRaisesMessage(RuntimeError, "No transcription service"):
            clips.transcribe_chunk(self.audio, offset=0)

    @patch("agents.clips.requests.post")
    def test_auto_language_is_detected_by_the_service(self, post) -> None:
        """An Urdu video forced to English came out as wrong English: with no language set, the service detects it."""
        from agents import clips

        post.return_value = MagicMock(status_code=200, json=lambda: {
            "language": "Urdu", "words": [{"word": "سلام", "start": 0.0, "end": 0.4}], "segments": []})
        words, used, heard = clips.transcribe_chunk(self.audio, offset=0, language=None)
        self.assertNotIn("language", post.call_args.kwargs["data"])
        self.assertEqual((used, heard), ("groq", "ur"))
        self.assertEqual(words[0]["word"], "سلام")

    def test_spoken_language_setting(self) -> None:
        from agents import clips

        self.assertIsNone(clips.clip_language({}))  # detect automatically
        self.assertIsNone(clips.clip_language({"language": "auto"}))
        self.assertEqual(clips.clip_language({"language": "ur"}), "ur")
        self.assertIsNone(clips.clip_language({"language": "../x"}))
        self.assertEqual(clips.language_code("urdu"), "ur")
        self.assertEqual(clips.language_code("English"), "en")
        self.assertEqual(clips.language_code("ur"), "ur")
        self.assertIsNone(clips.language_code("klingon"))

    @override_settings(AGENTS_DRY_RUN=False)
    def test_the_detected_language_is_used_for_every_later_piece(self) -> None:
        """Detecting per piece mistook music for Welsh, so the first piece decides for the whole video."""
        from agents import clips

        run = MagicMock()
        run.deployment.config = {}
        run.output = {"clip_info": {"duration": 1300}, "clip_audio": "a.mp3"}
        heard = [([{"word": "w", "start": float(i), "end": i + 0.5} for i in range(15)], "groq", "ur"),
                 ([{"word": "w", "start": 700.0 + i, "end": 700.5 + i} for i in range(15)], "groq", None)]
        with patch("agents.clips.base.media_dir", return_value=(self.audio.parent, "rel")), \
                patch("agents.clips.base.media_path", return_value=self.audio), \
                patch("agents.clips.base._save"), patch("agents.clips.base.keep_alive"), \
                patch("agents.clips.silences", return_value=[]), \
                patch("agents.clips.chunk_bounds", return_value=[(0, 650), (650, 1300)]), \
                patch("agents.clips.render._run"), \
                patch("agents.clips.transcribe_chunk", side_effect=heard) as chunk:
            clips.step_transcribe_long(run)
        self.assertEqual([c.kwargs["language"] for c in chunk.call_args_list], [None, "ur"])
        self.assertEqual(run.output["language"], "ur")
        self.assertEqual(len(run.output["words"]), 30)


class ClipMakerPipelineTests(_AgentAPITestCase):
    """Upload → transcript → moments → pick → real FFmpeg render of vertical clips, at zero cost."""

    dry_run = True
    _action = DryRunPipelineTests._action
    _work = DryRunPipelineTests._work

    def _upload(self, seconds=40) -> "LibraryAsset":
        from content.models import LibraryAsset

        folder = Path(self.media) / "projects" / str(self.project.id) / "library"
        folder.mkdir(parents=True)
        clip = folder / "talk.mp4"
        render._run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc2=s=640x360:d={seconds}:r=30", "-f", "lavfi",
                     "-i", f"sine=f=330:d={seconds}", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
                     "-shortest", str(clip)])
        return LibraryAsset.objects.create(
            project=self.project, user=self.user, media_type="video", title="My podcast", status="ready",
            source_url=f"http://testserver/media/projects/{self.project.id}/library/talk.mp4", capability="upload",
        )

    def test_pick_two_moments_and_get_vertical_clips(self) -> None:
        asset = self._upload()
        deployment = self.deploy("clip-maker", config={"clipLength": "short", "clipCount": 3, "layout": "fit"})
        response = self.start(deployment, assetId=str(asset.id))
        self.assertEqual(response.status_code, 201, response.data)
        run_id = response.data["id"]

        self._work()
        run = AgentRun.objects.get(id=run_id)
        self.assertEqual((run.status, run.step), ("needs_review", "clips"), run.error)
        moments = run.output["moments"]
        self.assertGreaterEqual(len(moments), 2)
        for m in moments:
            self.assertTrue(15 <= m["end"] - m["start"] <= 30.5, m)
        detail = self.client.get(self.runs_url(deployment)).data[0]
        self.assertEqual(detail["sourceSeconds"], run.output["clip_info"]["duration"])
        self.assertEqual(len(detail["moments"]), len(moments))

        bad = self._action(deployment, run_id, "continue", {"clips": [{"index": 0, "keep": True, "start": 5, "end": 999}]})
        self.assertEqual(bad.status_code, 400)
        picks = [{"index": 0, "keep": True, "hook": "Watch this"}, {"index": 1, "keep": True, "start": 20, "end": 36}]
        picks += [{"index": i, "keep": False} for i in range(2, len(moments))]
        self.assertEqual(self._action(deployment, run_id, "continue", {"clips": picks}).status_code, 200)
        self._work()
        run.refresh_from_db()
        self.assertEqual(run.status, "succeeded", run.error)
        made = run.output["clips"]
        self.assertEqual(len(made), 2)
        self.assertEqual(made[0]["hook"], "Watch this")
        self.assertAlmostEqual(made[1]["duration"], 16, delta=0.3)
        for clip in made:
            self.assertTrue((Path(self.media) / clip["video"]).exists())
            self.assertTrue(clip["thumbnail"].endswith(".jpg"))
        from content.models import LibraryAsset

        assets = LibraryAsset.objects.filter(model="agent:clip-maker")
        self.assertEqual(assets.count(), 2)
        self.assertEqual({(a.width, a.height) for a in assets}, {(1080, 1920)})
        self.assertEqual(run.library_asset_id, made[0]["assetId"] and assets.get(id=made[0]["assetId"]).id)
        detail = self.client.get(self.runs_url(deployment)).data[0]
        self.assertTrue(detail["clips"][0]["videoUrl"].endswith(".mp4"))

    def test_youtube_link_needs_rights_and_fits_the_plan(self) -> None:
        deployment = self.deploy("clip-maker")
        link = "https://youtu.be/dQw4w9WgXcQ"
        self.assertEqual(self.start(deployment, url=link).data["code"], "RIGHTS_REQUIRED")
        self.assertEqual(self.start(deployment, url="https://vimeo.com/1", rights=True).status_code, 400)
        info = {"title": "Talk", "duration": 3 * 60 * 60, "live": False}
        with patch("agents.views.youtube_info", return_value=info):
            self.assertEqual(self.start(deployment, url=link, rights=True).data["code"], "VIDEO_TOO_LONG")
        with patch("agents.views.youtube_info", return_value={**info, "duration": 600, "live": True}):
            self.assertEqual(self.start(deployment, url=link, rights=True).status_code, 400)
        with patch("agents.views.youtube_info", return_value={**info, "duration": 600}):
            response = self.start(deployment, url=link, rights=True)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["input"], {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                                                  "seconds": 600, "title": "Talk", "rights": True})

    def test_youtube_video_is_downloaded_by_the_first_step(self) -> None:
        from agents import clips

        deployment = self.deploy("clip-maker")
        run = AgentRun.objects.create(deployment=deployment, project=self.project, user=self.user,
                                      input={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "seconds": 40})

        def fake_download(url, folder, run=None):
            target = folder / "source.mp4"
            render._run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:d=12:r=30", "-f", "lavfi",
                         "-i", "sine=d=12", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
                         str(target)])
            return target

        with patch("agents.clips.download_youtube", side_effect=fake_download) as download:
            clips.step_get_video(run)
        download.assert_called_once()
        self.assertEqual(download.call_args.args[0], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertAlmostEqual(run.output["clip_info"]["duration"], 12, delta=0.2)
        self.assertTrue(run.output["clip_audio"].endswith("audio.mp3"))


class ClipRecipeValidationTests(SimpleTestCase):
    def test_clip_steps_need_a_video_and_cannot_mix_with_other_video_steps(self) -> None:
        clip = {"kind": "large", "input_kind": "video", "steps": list(BUILTIN_AGENTS["clip-maker"].steps)}
        self.assertIsNone(validate_recipe(clip))
        self.assertIn("need a video", validate_recipe({**clip, "input_kind": "topic"}))
        self.assertIn("can't be mixed", validate_recipe({**clip, "steps": ["get_video", "transcribe_long", "prepare"]}))
        self.assertIn("needs transcribe_long", validate_recipe({**clip, "steps": ["get_video", "find_clips"]}))


class ClipLocalWhisperTests(SimpleTestCase):
    def test_local_whisper_gets_decoded_samples_not_a_file(self) -> None:
        """faster-whisper's own file decoding breaks with PyAV 19, so we decode with FFmpeg."""
        import numpy

        from agents import clips

        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        audio = folder / "a.mp3"
        render._run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=d=2", "-ac", "1", str(audio)])
        word = MagicMock(word=" Hi.", start=0.1, end=0.4)
        model = MagicMock()
        model.transcribe.return_value = ([MagicMock(words=[word])], None)
        with patch("agents.clips._local_model", return_value=model):
            self.assertEqual(clips._local_words(audio, "en"), ([{"word": "Hi.", "start": 0.1, "end": 0.4}], None))
        self.assertEqual(model.transcribe.call_args.kwargs["language"], "en")
        samples = model.transcribe.call_args.args[0]
        self.assertIsInstance(samples, numpy.ndarray)
        self.assertEqual(samples.dtype, numpy.float32)
        self.assertAlmostEqual(len(samples) / 16000, 2, delta=0.1)


@override_settings(**{**HERMETIC, "OPENROUTER_API_KEY": "", "GEMINI_API_KEY": "g",
                      "AGENTS_GEMINI_MODELS": "busy-model,good-model"})
class GeminiTextTests(SimpleTestCase):
    @patch("agents.providers.requests.post")
    def test_gemini_writes_when_there_is_no_openrouter_key(self, post) -> None:
        busy = MagicMock(ok=False, status_code=503)
        good = MagicMock(ok=True, status_code=200, json=lambda: {
            "candidates": [{"content": {"parts": [{"text": '{"clips": []}'}]}}]})
        post.side_effect = [busy, good]
        used = providers.track()
        self.assertEqual(providers.text("sys", "user"), {"clips": []})
        self.assertEqual(used, ["gemini"])
        self.assertIn("good-model", post.call_args.args[0])  # the busy model was skipped
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["systemInstruction"]["parts"][0]["text"], "sys")
        self.assertEqual(body["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], "g")


def _face(cx, w=100, cy=200, score=0.9):
    return [cx - w / 2, cy - w / 2, w, w * 1.3, score]


def _samples(faces_at, seconds=4.0, fps=10, cut_at=None):
    """Analysis samples: faces_at(t) -> list of faces; a camera cut at `cut_at` seconds."""
    out = []
    for i in range(int(seconds * fps)):
        t = round(i / fps, 3)
        out.append({"t": t, "faces": faces_at(t), "cut": cut_at is not None and abs(t - cut_at) < 1e-6})
    return out


class ReframeTests(SimpleTestCase):
    W, H = 1920, 1080  # source; a 9:16 crop is 608 wide

    def test_camera_holds_still_while_the_speaker_sways(self) -> None:
        from agents import reframe

        times = [i / 10 for i in range(50)]
        targets = [960 + (25 if i % 2 else -25) for i in range(50)]
        path = reframe.camera_path(times, targets, crop_w=608, frame_w=self.W)
        self.assertEqual({x for _t, x in path}, {960 - 304})

    def test_camera_follows_a_big_move_smoothly_and_settles(self) -> None:
        from agents import reframe

        times = [i / 10 for i in range(60)]
        targets = [600] * 20 + [1300] * 40
        xs = [x for _t, x in reframe.camera_path(times, targets, crop_w=608, frame_w=self.W)]
        self.assertEqual(xs[0], 600 - 304)
        self.assertTrue(all(b >= a for a, b in zip(xs, xs[1:])), "moves one way, no shaking")
        self.assertLess(max(b - a for a, b in zip(xs, xs[1:])), 300, "eases over, no jump cut")
        self.assertAlmostEqual(xs[-1], 1300 - 304, delta=25)

    def test_camera_never_leaves_the_picture(self) -> None:
        from agents import reframe

        path = reframe.camera_path([0, 0.1], [5, 5], crop_w=608, frame_w=self.W)
        self.assertEqual(path[0][1], 0)
        path = reframe.camera_path([0, 0.1], [1915, 1915], crop_w=608, frame_w=self.W)
        self.assertEqual(path[0][1], self.W - 608)

    def test_shot_layouts_follow_the_faces(self) -> None:
        from agents import reframe

        one = reframe.plan_shots(_samples(lambda t: [_face(700)]), self.W, self.H, 4.0)
        self.assertEqual([s["layout"] for s in one], ["track"])
        none = reframe.plan_shots(_samples(lambda t: []), self.W, self.H, 4.0)
        self.assertEqual([s["layout"] for s in none], ["fit"])
        crowd = reframe.plan_shots(_samples(lambda t: [_face(300), _face(900), _face(1500)]), self.W, self.H, 4.0)
        self.assertEqual([s["layout"] for s in crowd], ["fit"])
        tiny = reframe.plan_shots(_samples(lambda t: [_face(900, w=30)]), self.W, self.H, 4.0)  # a far-away face
        self.assertEqual([s["layout"] for s in tiny], ["fit"])

    def test_two_people_far_apart_get_a_split_screen(self) -> None:
        from agents import reframe

        shots = reframe.plan_shots(_samples(lambda t: [_face(1500), _face(400)]), self.W, self.H, 4.0)
        self.assertEqual([s["layout"] for s in shots], ["split"])
        top, bottom = shots[0]["regions"]
        self.assertLess(top[0], bottom[0], "left person on top")
        for x, y, w, h in (top, bottom):
            self.assertAlmostEqual(w / h, 1080 / 960, delta=0.02)
            self.assertTrue(0 <= x and x + w <= self.W and 0 <= y and y + h <= self.H)
        close = reframe.plan_shots(_samples(lambda t: [_face(850), _face(1050)]), self.W, self.H, 4.0)
        self.assertEqual([s["layout"] for s in close], ["track"], "both fit in one vertical crop")

    def test_camera_cuts_split_shots_and_slivers_are_merged(self) -> None:
        from agents import reframe

        shots = reframe.plan_shots(_samples(lambda t: [_face(700)] if t < 2 else [], cut_at=2.0), self.W, self.H, 4.0)
        self.assertEqual([(s["layout"], s["start"], s["end"]) for s in shots], [("track", 0, 1.95), ("fit", 1.95, 4.0)])
        flash = reframe.plan_shots([{**s, "cut": s["t"] in (1.0, 1.2)} for s in _samples(lambda t: [_face(700)])],
                                   self.W, self.H, 4.0)
        self.assertEqual(len(flash), 2, "a 0.2 s shot is merged into its neighbour")

    def test_scene_cut_detection(self) -> None:
        import numpy

        from agents import reframe

        red = numpy.zeros((90, 160, 3), numpy.uint8)
        red[:] = (0, 0, 220)
        blue = numpy.zeros((90, 160, 3), numpy.uint8)
        blue[:] = (220, 60, 0)
        noisy = numpy.clip(red.astype(int) + numpy.random.default_rng(1).integers(-6, 6, red.shape), 0, 255).astype(numpy.uint8)
        self.assertTrue(reframe.is_cut(red, blue))
        self.assertFalse(reframe.is_cut(red, noisy))

    def test_filter_graph_joins_each_shot_in_its_layout(self) -> None:
        from agents import reframe

        work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        shots = [
            {"start": 0, "end": 2.0, "layout": "track", "path": [(0, 100), (1.0, 100), (1.5, 160)]},
            {"start": 2.0, "end": 4.0, "layout": "split", "regions": [(0, 0, 540, 480), (1000, 0, 540, 480)]},
            {"start": 4.0, "end": 6.0, "layout": "fit"},
        ]
        graph = reframe.video_filter(shots, self.W, self.H, work)
        self.assertIn("split=3", graph)
        self.assertIn("vstack", graph)
        self.assertIn("boxblur", graph)
        self.assertIn("concat=n=3:v=1:a=0[vr]", graph)
        commands = (work / "crop-0.txt").read_text()
        self.assertIn("crop@c0 x 160", commands)
        self.assertEqual(commands.count("x 100"), 1, "no repeated commands while the camera is still")

    def test_captions_move_to_the_seam_during_split_shots(self) -> None:
        from agents import reframe

        ass = ("[Events]\nDialogue: 0,0:00:01.00,0:00:01.50,Cap,,0,0,0,,hello\n"
               "Dialogue: 0,0:00:03.00,0:00:03.50,Cap,,0,0,0,,world\n")
        out = reframe.seam_captions(ass, [(2.0, 4.0)])
        self.assertIn(",,hello", out)
        self.assertIn(",,{\\an5\\pos(540,960)}world", out)

    def test_auto_layout_render_without_faces_falls_back_to_fit(self) -> None:
        from agents import clips

        work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        src = work / "src.mp4"
        render._run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:d=4:r=30", "-f", "lavfi", "-i", "sine=d=4",
                     "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(src)])
        out = work / "clip.mp4"
        clips.render_clip(src, {"start": 0.5, "end": 3.5, "hook": "Hi"}, _w("one two three", 0.6), "auto", "#FFD400", out, work)
        info = render.check_video(out, expect_sound=True)
        self.assertAlmostEqual(info["duration"], 3.0, delta=0.15)


class YoutubeRobustnessTests(SimpleTestCase):
    def test_slow_connections_get_patience_and_resume(self) -> None:
        from agents import clips

        options = clips._ytdlp_options()
        self.assertGreaterEqual(options["retries"], 10)
        self.assertGreaterEqual(options["fragment_retries"], 10)
        self.assertGreaterEqual(options["socket_timeout"], 60)
        self.assertTrue(options["continuedl"], "Try again resumes the half-done download")

    def test_a_timeout_is_explained_as_a_slow_connection(self) -> None:
        from agents import clips

        with self.assertLogs("agents.clips", "WARNING"):
            error = clips._youtube_error(Exception("[download] Got error: HTTPSConnectionPool(host='x.googlevideo.com', "
                                                   "port=443): Read timed out.. Giving up after 3 retries"))
        self.assertIn("slow", str(error))
        self.assertIn("Try again", str(error))


class CaptionStyleTests(SimpleTestCase):
    WORDS = _w("so here is the one thing nobody tells you", 0, 0.4)

    @staticmethod
    def _lines(ass):
        return [line.split(",,", 1)[1] for line in ass.splitlines() if line.startswith("Dialogue:") and ",Cap," in line]

    def test_classic_is_the_shorts_caption_look(self) -> None:
        from agents import clips

        self.assertEqual(clips.clip_ass(self.WORDS, "", 4.0, "#FFD400", "classic"),
                         render.build_captions([{"words": self.WORDS, "duration": 4.0}], "#FFD400"))

    def test_bold_is_big_uppercase_two_words_at_a_time(self) -> None:
        from agents import clips

        lines = self._lines(clips.clip_ass(self.WORDS, "", 4.0, "#FFD400", "bold"))
        plain = [re.sub(r"\{[^}]*\}", "", t) for t in lines]
        self.assertTrue(all(t == t.upper() for t in plain))
        self.assertTrue(all(len(t.split()) <= 2 for t in plain))
        self.assertIn("NOBODY", " ".join(plain))

    def test_boxed_puts_the_spoken_word_in_a_brand_box(self) -> None:
        from agents import clips

        lines = self._lines(clips.clip_ass(self.WORDS, "", 4.0, "#FF0000", "boxed"))
        self.assertTrue(all("\\3c&H000000FF&" in t and "\\bord" in t for t in lines))

    def test_minimal_has_no_highlight(self) -> None:
        from agents import clips

        lines = self._lines(clips.clip_ass(self.WORDS, "", 4.0, "#FFD400", "minimal"))
        self.assertTrue(lines)
        self.assertFalse(any("\\c" in t for t in lines))

    def test_hook_box_works_with_every_style(self) -> None:
        from agents import clips

        for style in clips.CAPTION_STYLES:
            ass = clips.clip_ass(self.WORDS, "Watch this", 4.0, "#FFD400", style)
            self.assertIn("Style: Hook,", ass, style)
            self.assertIn(",Hook,,0,0,0,,Watch this", ass, style)

    def test_unknown_style_falls_back_to_classic(self) -> None:
        from agents import clips

        self.assertEqual(clips.caption_style({"captionStyle": "nope"}), "classic")
        self.assertEqual(clips.caption_style({"captionStyle": "bold"}), "bold")


class CaptionEditTests(SimpleTestCase):
    WORDS = _w("I bring you frank sent this um she said", 0)

    def test_edits_line_up_with_the_spoken_words(self) -> None:
        from agents import clips

        fix = lambda text: clips.caption_fixes(self.WORDS, 0, len(self.WORDS) - 1, text)
        self.assertEqual(fix("I bring you frank sent this um she said"), {})
        self.assertEqual(fix("I bring you frank sent this um she said!"), {8: "said!"})
        self.assertEqual(fix("I bring you frankincense um she said"), {3: "frankincense", 4: "", 5: ""})
        self.assertEqual(fix("I bring you frank sent this she said"), {6: ""}, "a deleted word is hidden")
        self.assertEqual(fix("I bring you frank sent this um, she said"), {6: "um,"})
        self.assertEqual(fix("I really bring you frank sent this um she said"), {0: "I really"}, "an added word joins the one before")

    def test_check_in_saves_caption_fixes_for_the_render(self) -> None:
        from agents.views import RunActionView

        out = {"words": self.WORDS, "clip_info": {"duration": 10},
               "moments": [{"start": 0, "end": 4.5, "keep": True, "hook": "", "title": "t", "w": [0, 8],
                            "text": " ".join(w["word"] for w in self.WORDS)}]}
        problem = RunActionView._apply_clips(out, {"clips": [{"index": 0, "keep": True,
                                                              "captions": "I bring you frankincense um she said"}]})
        self.assertIsNone(problem)
        self.assertEqual(out["caption_fixes"], {"3": "frankincense", "4": "", "5": ""})
        self.assertIn("frankincense", out["moments"][0]["text"])
        self.assertIsNotNone(RunActionView._apply_clips(out, {"clips": [{"index": 0, "keep": True, "captions": "x" * 5001}]}))

    def test_render_uses_the_fixed_words(self) -> None:
        from agents import clips

        fixed = clips.fixed_words(self.WORDS, {"3": "frankincense", "4": "", "5": ""})
        self.assertEqual([w["word"] for w in fixed][2:6], ["you", "frankincense", "", ""])
        self.assertEqual(fixed[3]["start"], self.WORDS[3]["start"])


class TightenTests(SimpleTestCase):
    def test_long_pauses_and_ums_are_cut(self) -> None:
        from agents import clips

        words = _w("hello there friend", 0.2) + _w("um so the point is", 4.0)  # 2.6 s pause, then an "um"
        cuts = clips.tight_cuts(words, 7.0)
        pause = next(c for c in cuts if "pause" in c["reasons"])
        self.assertAlmostEqual(pause["start"], 1.6 + 0.2, delta=0.01)  # "friend" ends at 1.6 s
        self.assertGreaterEqual(pause["end"], 3.8 - 0.01)
        self.assertTrue(any("filler" in c["reasons"] for c in cuts) or pause["end"] >= 4.4)
        self.assertEqual(clips.tight_cuts(_w("no gaps at all here", 0), 3.0), [])

    def test_times_map_onto_the_tightened_clip(self) -> None:
        from agents import clips

        segments = [(0.0, 2.0), (5.0, 7.0)]
        self.assertEqual(clips.map_time(1.0, segments), 1.0)
        self.assertEqual(clips.map_time(3.0, segments), 2.0)  # inside a cut: where the cut is
        self.assertEqual(clips.map_time(6.0, segments), 3.0)

    def test_tightened_render_is_shorter_and_keeps_sound(self) -> None:
        from agents import clips

        work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, work, ignore_errors=True)
        src = work / "src.mp4"
        render._run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=s=640x360:d=8:r=30", "-f", "lavfi",
                     "-i", "aevalsrc='if(between(t,2,5),0,0.5*sin(440*2*PI*t))':s=44100:d=8",
                     "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(src)])
        words = _w("one two three", 0.5) + _w("four five six", 5.2)  # 3.3 s pause between them
        out = work / "clip.mp4"
        length = clips.render_clip(src, {"start": 0, "end": 7.5, "hook": "Hi"}, words, "fit", "#FFD400", out, work,
                                   tighten=True)
        info = render.check_video(out, expect_sound=True)
        self.assertLess(info["duration"], 5.5)
        self.assertAlmostEqual(info["duration"], length, delta=0.15)


class ClipServerTests(_AgentAPITestCase):
    def test_po_token_provider_is_passed_to_ytdlp(self) -> None:
        from agents import clips

        with override_settings(CLIPS_YTDLP_POT_URL=""):
            self.assertNotIn("extractor_args", clips._ytdlp_options())
        with override_settings(CLIPS_YTDLP_POT_URL="http://127.0.0.1:4416"):
            self.assertEqual(clips._ytdlp_options()["extractor_args"],
                             {"youtubepot-bgutilhttp": {"base_url": ["http://127.0.0.1:4416"]}})

    def test_old_sources_are_deleted_and_clips_kept(self) -> None:
        deployment = self.deploy("clip-maker")
        old = AgentRun.objects.create(deployment=deployment, project=self.project, user=self.user, input={},
                                      status="succeeded", finished_at=timezone.now() - timedelta(days=8))
        new = AgentRun.objects.create(deployment=deployment, project=self.project, user=self.user, input={},
                                      status="succeeded", finished_at=timezone.now() - timedelta(days=1))
        busy = AgentRun.objects.create(deployment=deployment, project=self.project, user=self.user, input={},
                                       status="needs_review", updated_at=timezone.now() - timedelta(days=30))
        folders = {}
        for run in (old, new, busy):
            folder, rel = steps.media_dir(run)
            for name in ("source.mp4", "audio.mp3", "clip-1.mp4", "clip-1.jpg"):
                (folder / name).write_bytes(b"x")
            run.output = {"clip_source": f"{rel}/source.mp4", "clip_audio": f"{rel}/audio.mp3"}
            run.save(update_fields=["output"])
            folders[run.id] = folder
        AgentRun.objects.filter(id=busy.id).update(updated_at=timezone.now() - timedelta(days=30))
        call_command("cleanup_clip_sources", "--days", "7")
        self.assertEqual(sorted(p.name for p in folders[old.id].iterdir()), ["clip-1.jpg", "clip-1.mp4"])
        self.assertEqual(len(list(folders[new.id].iterdir())), 4, "kept: finished recently")
        self.assertEqual(len(list(folders[busy.id].iterdir())), 4, "kept: still waiting for the user")
        old.refresh_from_db()
        self.assertTrue(old.output["source_deleted"])
        detail = self.client.get(self.runs_url(deployment)).data
        self.assertIsNone(next(r for r in detail if r["id"] == str(old.id))["sourceUrl"])


class DownloadProgressTests(_AgentAPITestCase):
    def test_download_progress_is_saved_for_the_screen(self) -> None:
        from agents import clips

        deployment = self.deploy("clip-maker")
        run = AgentRun.objects.create(deployment=deployment, project=self.project, user=self.user,
                                      input={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}, status="running")
        hook = clips.progress_hook(run, every=0)
        hook({"status": "downloading", "downloaded_bytes": 50_000_000, "total_bytes": 200_000_000, "speed": 45_000,
              "eta": 3333, "info_dict": {"vcodec": "avc1", "acodec": "none"}})
        run.refresh_from_db()
        self.assertEqual(run.output["download"], {"part": "video", "percent": 25, "speed": 45000, "eta": 3333})
        hook({"status": "downloading", "downloaded_bytes": 10, "total_bytes_estimate": 40, "speed": None, "eta": None,
              "info_dict": {"vcodec": "none", "acodec": "opus"}})
        run.refresh_from_db()
        self.assertEqual(run.output["download"], {"part": "sound", "percent": 25, "speed": 0, "eta": None})
        detail = self.client.get(self.runs_url(deployment)).data[0]
        self.assertEqual(detail["download"]["part"], "sound")


class CancelRunTests(_AgentAPITestCase):
    def _running(self, agent="clip-maker") -> AgentRun:
        self.user.refresh_from_db()
        deployment = self.deploy(agent)
        return AgentRun.objects.create(deployment=deployment, project=self.project, user=self.user,
                                       input={"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}, status="running",
                                       step="get_video", credits_reserved=Decimal("1.5"))

    def _cancel(self, run):
        url = reverse("agent_run_action", kwargs={"project_id": self.project.id, "deployment_id": run.deployment_id,
                                                  "run_id": run.id, "action": "discard"})
        return self.client.post(url, {}, format="json")

    def test_user_cancels_a_running_job_and_gets_the_credits_back(self) -> None:
        run = self._running()
        before = self.user.credits_remaining
        response = self._cancel(run)
        self.assertEqual(response.status_code, 200, response.data)
        run.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual(run.status, "discarded")
        self.assertIn("Cancelled", run.error)
        self.assertEqual(self.user.credits_remaining, before + Decimal("1.5"))
        self.assertEqual(self._cancel(run).status_code, 400, "only once")
        delete = self.client.delete(reverse("agent_deployment", kwargs={"project_id": self.project.id,
                                                                          "deployment_id": run.deployment_id}))
        self.assertIn(delete.status_code, (200, 204), "the agent can be removed now")

    def test_the_worker_stops_at_its_next_check(self) -> None:
        run = self._running()
        AgentRun.objects.filter(id=run.id).update(status="discarded")
        with self.assertRaises(steps.RunCancelled):
            steps.keep_alive(run)
        from agents import clips

        with self.assertRaises(steps.RunCancelled):
            clips.progress_hook(run, every=0)({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 2})

    def test_engine_ends_quietly_when_a_run_is_cancelled_mid_step(self) -> None:
        run = self._running(agent="script-writer")
        AgentRun.objects.filter(id=run.id).update(status="queued", step="")

        def cancelled_mid_step(r):
            AgentRun.objects.filter(id=r.id).update(status="discarded", error="Cancelled.")
            steps.keep_alive(r)

        before = self.user.credits_remaining
        with patch.dict(steps.STEPS, {"script": cancelled_mid_step}):
            engine.process(engine.claim_next())
        run.refresh_from_db()
        self.user.refresh_from_db()
        self.assertEqual((run.status, run.error), ("discarded", "Cancelled."))
        self.assertEqual(self.user.credits_remaining, before, "no second refund from the engine")


from django.core import mail  # noqa: E402
from agents import growth, runs  # noqa: E402

YT_SCOPES = f"{growth.ANALYTICS_SCOPE} {growth.MONEY_SCOPE}"


def yt(rows, headers):
    return MagicMock(ok=True, json=lambda: {"columnHeaders": [{"name": h} for h in headers], "rows": rows},
                     raise_for_status=lambda: None)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", FRONTEND_URL="https://app.example")
class GrowthReportTests(_AgentAPITestCase):
    dry_run = True

    def test_dry_run_report_is_written_and_emailed(self) -> None:
        SocialAccount.objects.create(project=self.project, platform="youtube", scope=YT_SCOPES)
        deployment = self.deploy("growth-report", config={
            "period": 15, "posts_per_week": 3, "goal": {"metric": "views", "target": 1000},
            "emails": ["team@example.com", "not-an-email", "agent@example.com"]})
        run_id = self.start(deployment).data["id"]
        call_command("run_agents_worker", "--once", stdout=MagicMock())
        run = AgentRun.objects.get(id=run_id)
        self.assertEqual(run.status, "succeeded", run.error)
        self.assertEqual(run.input, {"period": 15})
        report = run.output["report"]
        self.assertEqual(len(report["plan"]), 6)  # 3 a week for 15 days
        self.assertEqual(report["mood"], "better")  # views 900 -> 1200
        self.assertEqual((report["goal"]["value"], report["goal"]["pct"]), (1200, 120))
        self.assertEqual(run.output["sent_to"], ["agent@example.com", "team@example.com"])  # invalid and duplicate dropped
        self.assertIn(f"https://app.example/agents/{deployment.id}?run={run.id}", mail.outbox[0].alternatives[0][0])
        detail = self.client.get(self.runs_url(deployment)).data[0]
        self.assertEqual(detail["report"]["mood"], "better")

    @override_settings(AGENTS_DRY_RUN=False)
    @patch("agents.growth.ensure_fresh_access_token", return_value="t")
    @patch("agents.growth.requests.get")
    def test_youtube_analytics_both_periods_revenue_and_top_videos(self, get, _token) -> None:
        account = SocialAccount.objects.create(project=self.project, platform="youtube", scope=YT_SCOPES)
        metrics = list(growth.YT_METRICS)
        get.side_effect = [
            yt([[500, 600, 50, 10, 1, 20, 3, 1]], metrics), yt([[250, 300, 40, 5, 1, 10, 1, 0]], metrics),
            yt([[3.5]], ["estimatedRevenue"]), yt([[1.0]], ["estimatedRevenue"]),
            yt([["v1", 300, 55, 10, 2, 4]], ["video", "views", "averageViewPercentage", "likes", "comments", "subscribersGained"]),
            MagicMock(ok=True, json=lambda: {"items": [{"id": "v1", "snippet": {"title": "Best", "publishedAt": "2026-10-07T10:00:00Z"}}]}),
            MagicMock(ok=True, json=lambda: {"items": [{"statistics": {"subscriberCount": "1500"}}]}),
        ]
        out = growth.youtube_numbers(account, (timezone.localdate(), timezone.localdate()), (timezone.localdate(), timezone.localdate()))
        self.assertEqual((out["now"]["views"], out["before"]["views"]), (500, 250))
        self.assertEqual((out["revenue_now"], out["revenue_before"]), (3.5, 1.0))
        self.assertEqual((out["top"][0]["title"], out["subscribers_total"]), ("Best", 1500))
        self.assertEqual(growth.change(500, 250), 100)
        self.assertEqual(get.call_args_list[0].kwargs["params"]["ids"], "channel==MINE")

    @override_settings(AGENTS_DRY_RUN=False)
    def test_old_youtube_connection_asks_to_reconnect(self) -> None:
        SocialAccount.objects.create(project=self.project, platform="youtube", scope="youtube.upload")
        run = AgentRun.objects.create(deployment=self.deploy("growth-report"), project=self.project, user=self.user,
                                      input={"period": 7})
        growth.step_collect(run)
        self.assertIsNone(run.output["numbers"]["youtube"])
        self.assertIn("reconnect_youtube", run.output["numbers"]["notes"])

    def test_disconnecting_youtube_removes_its_numbers_from_reports(self) -> None:
        SocialAccount.objects.create(project=self.project, platform="youtube", scope=YT_SCOPES)
        run = AgentRun.objects.create(deployment=self.deploy("growth-report"), project=self.project, user=self.user,
                                      output={"numbers": {"youtube": {"now": {"views": 1}}}})
        self.client.delete(reverse("project_social_disconnect", kwargs={"project_id": self.project.id, "platform": "youtube"}))
        run.refresh_from_db()
        self.assertIsNone(run.output["numbers"]["youtube"])

    def test_report_every_15_days(self) -> None:
        deployment = self.deploy("growth-report", config={"period": 15})
        slot = timezone.now() - timedelta(minutes=1)
        AgentDeployment.objects.filter(id=deployment.id).update(
            autopilot=True, schedule={"days": [0], "time": "09:00", "tz": "UTC"}, next_run_at=slot)
        self.assertEqual(runs.run_due(), 1)
        deployment.refresh_from_db()
        self.assertEqual(deployment.next_run_at, slot + timedelta(days=15))
        self.assertEqual(deployment.runs.get().input, {"period": 15})

    def test_goal_progress_and_mood(self) -> None:
        numbers = {"youtube": None, "posts": {"count": 2, "count_before": 4}}
        self.assertEqual(growth.mood(numbers), "worse")
        self.assertEqual(growth.goal_progress({"metric": "posts", "target": 4}, numbers)["pct"], 50)
        self.assertIsNone(growth.goal_progress({"metric": "posts", "target": "x"}, numbers))
        self.assertIsNone(growth.goal_progress({"metric": "nope", "target": 5}, numbers))

    def test_model_text_loses_citations(self) -> None:
        self.assertEqual(growth.plain("Do it [developers.google.cn].", 300), "Do it.")
        self.assertEqual(growth.plain("See [a guide](https://x.com) now", 300), "See a guide now")
        self.assertEqual(growth.plain("Post 3 [times] a week", 300), "Post 3 [times] a week")


from django.core.cache import cache  # noqa: E402

from agents import tasks  # noqa: E402
from config.celery import app as celery_app  # noqa: E402


@override_settings(USE_CELERY=True)
class CeleryTaskTests(_AgentAPITestCase):
    """Celery path (Docker): runs start at once, Beat's sweep is the safety net, nothing runs twice."""

    dry_run = True

    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        celery_app.conf.task_always_eager = True  # .delay() runs inline, no broker needed
        self.addCleanup(setattr, celery_app.conf, "task_always_eager", False)

    def test_a_new_run_is_processed_by_celery_right_away(self) -> None:
        deployment = self.deploy("script-writer")
        with self.captureOnCommitCallbacks(execute=True):
            run_id = self.start(deployment, topic="coffee").data["id"]
        run = AgentRun.objects.get(id=run_id)
        self.assertEqual(run.status, "succeeded", run.error)
        self.assertTrue(run.output["scenes"])

    def test_sweep_recovers_stuck_runs_and_waits_for_scheduled_ones(self) -> None:
        deployment = self.deploy("script-writer")
        stuck = AgentRun.objects.create(deployment=deployment, project=self.project, user=self.user, input={"topic": "a"},
                                        status="running", locked_until=timezone.now() - timedelta(minutes=1))
        later = AgentRun.objects.create(deployment=deployment, project=self.project, user=self.user, input={"topic": "b"},
                                        status="queued", locked_until=timezone.now() + timedelta(hours=1))
        tasks.sweep()
        stuck.refresh_from_db()
        later.refresh_from_db()
        self.assertEqual(stuck.status, "succeeded", stuck.error)  # resumed and finished
        self.assertEqual(later.status, "queued")  # its time hasn't come

    def test_a_run_is_sent_to_a_worker_once(self) -> None:
        with patch.object(tasks.process_run, "delay") as delay:
            tasks.dispatch("abc")
            tasks.dispatch("abc")
        delay.assert_called_once_with("abc")

    def test_two_claims_cannot_both_win(self) -> None:
        run = AgentRun.objects.create(deployment=self.deploy("script-writer"), project=self.project, user=self.user,
                                      input={"topic": "a"})
        self.assertIsNotNone(engine.claim(run.id))
        self.assertIsNone(engine.claim(run.id))
