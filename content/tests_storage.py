"""Storage per plan: measuring an account's files, refusing new files and jobs when full, freeing space
on delete, the extra storage add-on, and the daily cleanup."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from content import storage_quota
from content.models import ImageUpload, LibraryAsset
from content.storage_quota import GB, limit_bytes, storage_problem, used_bytes
from projects.models import Project
from users.models import User
from users.plans import get_plan

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


class StorageTestCase(APITestCase):
    def setUp(self) -> None:
        self.media = tempfile.mkdtemp()
        self.private = tempfile.mkdtemp()
        self.settings_override = override_settings(MEDIA_ROOT=self.media, PRIVATE_MEDIA_ROOT=Path(self.private))
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(shutil.rmtree, self.media, True)
        self.addCleanup(shutil.rmtree, self.private, True)
        cache.clear()
        self.user = User.objects.create_user(email="store@example.com", password="Password123!", plan="free")
        self.project = Project.objects.create(owner=self.user, name="Brand")
        self.client.force_authenticate(self.user)

    def write(self, rel: str, size: int) -> Path:
        path = Path(self.media) / "projects" / str(self.project.id) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"0" * size)
        storage_quota.storage_changed(self.user.pk)
        return path

    def fill(self, limit_fraction: float = 1.0) -> None:
        """Pretend the account uses this share of its limit (without writing GBs)."""
        cache.set(f"storage-used:{self.user.pk}", int(limit_bytes(self.user) * limit_fraction), 60)


class PlanStorageTests(StorageTestCase):
    def test_each_plan_has_its_storage(self) -> None:
        for plan, gb in (("free", 2), ("basic", 15), ("plus", 75), ("pro", 250)):
            self.assertEqual(get_plan(plan)["limits"]["storage_gb"], gb)
            self.assertIn(f"{gb} GB storage", get_plan(plan)["features"])
            self.user.plan = plan
            self.assertEqual(limit_bytes(self.user), gb * GB)

    def test_usage_counts_project_files_and_uploads_but_not_unfinished_downloads(self) -> None:
        self.write("library/a.mp4", 1000)
        self.write("agents/run/clip.mp4", 500)
        self.write("agents/run/source.mp4.part", 9999)
        ImageUpload.objects.create(project=self.project, user=self.user, content_type="image/png",
                                   byte_size=250, file="projects/2026/10/20/uploads/x.png")
        self.assertEqual(used_bytes(self.user), 1750)

    def test_balance_includes_storage(self) -> None:
        self.write("library/a.png", 2048)
        data = self.client.get("/api/credits").data["storage"]
        self.assertEqual((data["usedBytes"], data["limitBytes"], data["full"]), (2048, 2 * GB, False))
        self.assertEqual(data["addon"]["gb"], 50)


class StorageFullTests(StorageTestCase):
    def upload(self, name="a.png", body=PNG, content_type="image/png"):
        return self.client.post(
            f"/api/projects/{self.project.id}/library/uploads",
            {"file": SimpleUploadedFile(name, body, content_type=content_type)},
            format="multipart",
        )

    def test_upload_allowed_with_room_and_counted(self) -> None:
        response = self.upload()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(used_bytes(self.user), len(PNG))

    def test_upload_refused_when_it_does_not_fit(self) -> None:
        cache.set(f"storage-used:{self.user.pk}", limit_bytes(self.user) - 10, 60)
        response = self.upload()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["code"], "STORAGE_FULL")
        self.assertIn("storage left", response.data["message"])
        self.assertFalse(LibraryAsset.objects.exists())

    def test_image_upload_for_edits_refused_when_full(self) -> None:
        self.fill()
        response = self.client.post(
            f"/api/projects/{self.project.id}/images/uploads",
            {"file": SimpleUploadedFile("a.png", PNG, content_type="image/png")},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["code"], "STORAGE_FULL")

    def test_large_upload_refused_up_front(self) -> None:
        self.fill(0.99)
        response = self.client.post(
            f"/api/projects/{self.project.id}/library/uploads/large",
            {"contentType": "video/mp4", "size": GB, "fileName": "talk.mp4"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.data["code"], "STORAGE_FULL")

    def test_new_image_and_video_jobs_refused_when_full_before_charging(self) -> None:
        self.user.credits_remaining = 50
        self.user.save()
        self.fill()
        image = self.client.post(
            f"/api/projects/{self.project.id}/images/jobs",
            {"capability": "textToImage", "model": "fal-ai/nano-banana-2", "prompt": "a cat"},
            format="json",
        )
        video = self.client.post(
            f"/api/projects/{self.project.id}/videos/jobs",
            {"capability": "textToVideo", "model": "fal-ai/kling-video/v2.5-turbo/pro/text-to-video",
             "prompt": "a cat"},
            format="json",
        )
        for response in (image, video):
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.data)
            self.assertEqual(response.data["code"], "STORAGE_FULL")
        self.user.refresh_from_db()
        self.assertEqual(self.user.credits_remaining, 50)

    def test_agent_run_refused_when_full(self) -> None:
        from agents.models import AgentDeployment
        from agents.runs import RunRefused, start_run

        deployment = AgentDeployment.objects.create(project=self.project, user=self.user, agent_type="script-writer")
        self.fill()
        with self.assertRaises(RunRefused) as refused:
            start_run(deployment, {"topic": "cats"})
        self.assertEqual(refused.exception.code, "STORAGE_FULL")

    def test_full_means_at_or_over_the_limit(self) -> None:
        self.fill(0.5)
        self.assertIsNone(storage_problem(self.user))
        self.fill(1.0)
        self.assertIsNotNone(storage_problem(self.user))


class DeleteFreesStorageTests(StorageTestCase):
    def asset(self, path: Path) -> LibraryAsset:
        url = f"http://testserver/media/{path.relative_to(self.media).as_posix()}"
        return LibraryAsset.objects.create(project=self.project, user=self.user, media_type="video",
                                           source_url=url, thumbnail_url=url)

    def test_deleting_from_library_removes_the_file(self) -> None:
        path = self.write("library/a.mp4", 1000)
        asset = self.asset(path)
        self.assertEqual(used_bytes(self.user), 1000)
        response = self.client.delete(f"/api/projects/{self.project.id}/library/{asset.id}")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(path.exists())
        self.assertEqual(used_bytes(self.user), 0)

    def test_file_kept_while_another_item_shows_it(self) -> None:
        path = self.write("library/a.mp4", 1000)
        first, _second = self.asset(path), self.asset(path)
        self.client.delete(f"/api/projects/{self.project.id}/library/{first.id}")
        self.assertTrue(path.exists())

    def test_never_removes_a_file_outside_the_items_project(self) -> None:
        other = Project.objects.create(owner=self.user, name="Other")
        path = self.write("library/a.mp4", 10)
        asset = LibraryAsset.objects.create(project=other, user=self.user, media_type="video",
                                            source_url=f"/media/{path.relative_to(self.media).as_posix()}")
        self.client.delete(f"/api/projects/{other.id}/library/{asset.id}")
        self.assertTrue(path.exists())


class StorageAddonTests(StorageTestCase):
    def test_buy_and_approve_adds_50_gb_for_30_days(self) -> None:
        from admin_panel.models import Payment
        from admin_panel.services import review_payment

        response = self.client.post(
            "/api/credits/payments/submit",
            {"paymentType": "storage", "screenshot": SimpleUploadedFile("p.png", PNG, content_type="image/png"),
             "transactionId": "EP-STORE-1"},
            format="multipart",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual((response.data["amount"], response.data["planName"]), (849, "Extra storage (+50 GB)"))
        admin = User.objects.create_superuser(email="admin@example.com", password="Password123!")
        review_payment(response.data["id"], "approve", admin)
        self.user.refresh_from_db()
        self.assertEqual(limit_bytes(self.user), 52 * GB)
        self.assertAlmostEqual(
            (self.user.extra_storage_until - timezone.now()).total_seconds(), 30 * 86400, delta=60
        )
        self.assertEqual(Payment.objects.get().status, "paid")

    def test_renewing_extends_from_the_current_end_and_lapsing_removes_the_room(self) -> None:
        end = timezone.now() + timedelta(days=10)
        self.user.extra_storage_until = end
        storage_quota.extend_addon(self.user)
        self.assertEqual(self.user.extra_storage_until, end + timedelta(days=30))
        self.user.extra_storage_until = timezone.now() - timedelta(seconds=1)
        self.assertEqual(limit_bytes(self.user), 2 * GB)


class CleanStorageTests(StorageTestCase):
    def run_cleanup(self, *args) -> str:
        out = StringIO()
        call_command("clean_storage", *args, stdout=out)
        return out.getvalue()

    def test_removes_only_old_unfinished_downloads(self) -> None:
        old = self.write("agents/run/source.mp4.part", 100)
        fresh = self.write("agents/run2/source.mp4.part", 100)
        os.utime(old, (time.time() - 2 * 86400,) * 2)
        self.run_cleanup()
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists())

    def test_inactive_free_account_is_warned_then_cleared(self) -> None:
        path = self.write("library/a.mp4", 1000)
        asset = LibraryAsset.objects.create(project=self.project, user=self.user, media_type="video")
        User.objects.filter(pk=self.user.pk).update(last_active_at=timezone.now() - timedelta(days=200))

        self.run_cleanup()
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("removed", mail.outbox[0].subject)
        self.assertTrue(path.exists())

        self.run_cleanup()  # warned already: no second email, files stay until the warning runs out
        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(path.exists())

        User.objects.filter(pk=self.user.pk).update(storage_warned_at=timezone.now() - timedelta(days=31))
        self.run_cleanup()
        self.assertFalse(path.exists())
        asset.refresh_from_db()
        self.assertIsNotNone(asset.deleted_at)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_returning_paid_and_active_accounts_are_left_alone(self) -> None:
        path = self.write("library/a.mp4", 1000)
        long_ago = timezone.now() - timedelta(days=200)
        # Came back after being warned.
        User.objects.filter(pk=self.user.pk).update(
            last_active_at=timezone.now() - timedelta(days=1), storage_warned_at=long_ago
        )
        paid = User.objects.create_user(email="paid@example.com", password="Password123!", plan="plus")
        User.objects.filter(pk=paid.pk).update(last_active_at=long_ago)
        self.run_cleanup()
        self.assertTrue(path.exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_no_file_removed_when_the_warning_email_fails(self) -> None:
        self.write("library/a.mp4", 1000)
        User.objects.filter(pk=self.user.pk).update(last_active_at=timezone.now() - timedelta(days=200))
        with patch("content.management.commands.clean_storage.send_mail", side_effect=OSError):
            self.run_cleanup()
        self.user.refresh_from_db()
        self.assertIsNone(self.user.storage_warned_at)

    def test_dry_run_changes_nothing(self) -> None:
        old = self.write("agents/run/source.mp4.part", 100)
        os.utime(old, (time.time() - 2 * 86400,) * 2)
        User.objects.filter(pk=self.user.pk).update(last_active_at=timezone.now() - timedelta(days=200))
        self.write("library/a.mp4", 1000)
        self.assertIn("1 would be warned", self.run_cleanup("--dry-run"))
        self.assertTrue(old.exists())
        self.assertEqual(len(mail.outbox), 0)


class ClipMakerStorageTests(StorageTestCase):
    """Clip Maker works on a library video in place, so it isn't counted twice."""

    def setUp(self) -> None:
        super().setUp()
        from agents import render
        from agents.models import AgentDeployment

        self.user.plan = "basic"
        self.user.save()
        self.video = self.write("library/talk.mp4", 0)
        render._run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=s=160x120:d=12:r=10", "-f", "lavfi",
                     "-i", "sine=d=12", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest",
                     str(self.video)])
        storage_quota.storage_changed(self.user.pk)
        self.rel = self.video.relative_to(self.media).as_posix()
        self.asset = LibraryAsset.objects.create(project=self.project, user=self.user, media_type="video",
                                                 source_url=f"http://testserver/media/{self.rel}")
        self.deployment = AgentDeployment.objects.create(project=self.project, user=self.user,
                                                         agent_type="clip-maker")

    def run_on_library_video(self, **fields):
        from agents import clips
        from agents.models import AgentRun

        run = AgentRun.objects.create(deployment=self.deployment, project=self.project, user=self.user,
                                      input={"assetId": str(self.asset.id)}, **fields)
        clips.step_get_video(run)
        storage_quota.storage_changed(self.user.pk)
        return run

    def test_library_video_is_used_in_place_not_copied(self) -> None:
        run = self.run_on_library_video()
        self.assertEqual(run.output["clip_source"], self.rel)
        run_folder = Path(self.media) / "projects" / str(self.project.id) / "agents" / str(run.id)
        self.assertEqual(sorted(p.name for p in run_folder.iterdir()), ["audio.mp3"])
        audio = (run_folder / "audio.mp3").stat().st_size
        self.assertEqual(used_bytes(self.user), self.video.stat().st_size + audio)

    def test_cleanup_keeps_a_source_that_is_still_in_the_library(self) -> None:
        from agents.models import AgentRun

        run = self.run_on_library_video()
        AgentRun.objects.filter(pk=run.pk).update(status="succeeded", finished_at=timezone.now() - timedelta(days=8))
        call_command("cleanup_clip_sources", "--days", "7", stdout=StringIO())
        run.refresh_from_db()
        self.assertTrue(self.video.exists())
        self.assertFalse((Path(self.media) / run.output["clip_audio"]).exists())
        self.assertTrue(run.output["source_cleaned"])
        self.assertNotIn("source_deleted", run.output)

    def test_library_delete_waits_for_an_unfinished_run_then_cleanup_removes_it(self) -> None:
        from agents.models import AgentRun

        run = self.run_on_library_video(status="needs_review")
        self.client.delete(f"/api/projects/{self.project.id}/library/{self.asset.id}")
        self.assertTrue(self.video.exists(), "Clip Maker still needs it")

        AgentRun.objects.filter(pk=run.pk).update(status="succeeded", finished_at=timezone.now() - timedelta(days=8))
        call_command("cleanup_clip_sources", "--days", "7", stdout=StringIO())
        self.assertFalse(self.video.exists())
        run.refresh_from_db()
        self.assertTrue(run.output["source_deleted"])

    def test_library_delete_after_the_run_finished_removes_the_file(self) -> None:
        self.run_on_library_video(status="succeeded", finished_at=timezone.now())
        self.client.delete(f"/api/projects/{self.project.id}/library/{self.asset.id}")
        self.assertFalse(self.video.exists())
