"""Daily storage cleanup (Celery beat: content.tasks.clean_storage).

1. Clip Maker source videos of finished runs (cleanup_clip_sources; the clips stay).
2. Unfinished downloads (*.part) left in project folders for over a day.
3. Free accounts inactive for INACTIVE_DAYS: emailed once, then their files are removed WARNING_DAYS later
   if they still haven't come back. The account itself stays.
"""

from __future__ import annotations

import logging
import shutil
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.mail import send_mail
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db.models import F, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from content.models import ImageUpload, LibraryAsset
from content.storage_quota import format_bytes, measure_used_bytes, storage_changed
from users.models import User

logger = logging.getLogger(__name__)

PART_MAX_AGE_SECONDS = 24 * 3600
INACTIVE_DAYS = 180
WARNING_DAYS = 30


def _remove_stale_parts() -> int:
    freed = 0
    cutoff = time.time() - PART_MAX_AGE_SECONDS
    for part in (Path(settings.MEDIA_ROOT) / "projects").glob("**/*.part"):
        try:
            stat = part.stat()
            if stat.st_mtime < cutoff:
                part.unlink()
                freed += stat.st_size
        except OSError:
            continue
    return freed


def _remove_account_files(user) -> None:
    media_root = Path(settings.MEDIA_ROOT)
    for pid in user.projects.values_list("id", flat=True):
        shutil.rmtree(media_root / "projects" / str(pid), ignore_errors=True)
    for upload in ImageUpload.objects.filter(user=user):
        if upload.file:
            (media_root / upload.file.name).unlink(missing_ok=True)
        upload.delete()
    LibraryAsset.objects.filter(user=user, deleted_at__isnull=True).update(deleted_at=timezone.now())
    storage_changed(user.pk)


def _warn(user, used: int) -> None:
    send_mail(
        "Your Admart files will be removed soon",
        f"You haven't used Admart in over {INACTIVE_DAYS // 30} months. Your free account keeps "
        f"{format_bytes(used)} of images and videos.\n\n"
        f"Sign in within {WARNING_DAYS} days to keep them: {settings.FRONTEND_URL.rstrip('/')}/library\n\n"
        "If you don't, we'll remove these files. Your account stays, and you can keep creating.",
        None,
        [user.email],
    )


class Command(BaseCommand):
    help = "Free storage: old Clip Maker sources, stale downloads, files of long-inactive free accounts."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Only report inactive accounts; change nothing.")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        if not dry:
            call_command("cleanup_clip_sources", stdout=self.stdout)
            self.stdout.write(f"Stale downloads: freed {format_bytes(_remove_stale_parts())}")

        now = timezone.now()
        inactive = (
            User.objects.filter(plan="free", is_active=True, is_staff=False)
            .annotate(seen=Coalesce("last_active_at", "created_at"))
            .filter(seen__lt=now - timedelta(days=INACTIVE_DAYS))
        )
        warned = removed = 0
        # Not warned yet, or came back after the last warning: warn (again).
        for user in inactive.filter(Q(storage_warned_at__isnull=True) | Q(storage_warned_at__lt=F("seen"))).iterator():
            used = measure_used_bytes(user)
            if not used:
                continue
            warned += 1
            if dry:
                continue
            try:
                _warn(user, used)
            except Exception:  # noqa: BLE001 — never remove files we couldn't warn about
                logger.exception("Storage warning email failed for user %s", user.pk)
                continue
            User.objects.filter(pk=user.pk).update(storage_warned_at=now)
        # Warned long enough ago and still not back.
        for user in inactive.filter(
            storage_warned_at__lt=now - timedelta(days=WARNING_DAYS),
            storage_warned_at__gte=F("seen"),
        ).iterator():
            removed += 1
            if not dry:
                _remove_account_files(user)
                User.objects.filter(pk=user.pk).update(storage_warned_at=None)
        verb = "would be" if dry else "were"
        self.stdout.write(f"Inactive free accounts: {warned} {verb} warned, {removed} {verb} cleared")
