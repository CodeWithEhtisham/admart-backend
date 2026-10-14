"""Permanently delete a user account and everything it owns.

Deleted: the user, projects (with jobs, library assets, publish/ad jobs and the
connected social/ad accounts holding OAuth tokens), uploads, subscriptions,
credit history, and all their media files on disk.

Kept: payment rows (amount, plan/pack, transaction ID, dates) for accounting,
with the user link cleared and payer_email recorded. Their screenshots (customer
financial details) are deleted. Matches the Privacy Policy "data deletion" section.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)


def delete_account(user) -> None:
    from admin_panel.models import Payment, private_storage
    from content.models import ImageUpload

    media_root = Path(settings.MEDIA_ROOT)
    project_dirs = [media_root / "projects" / str(pid) for pid in user.projects.values_list("id", flat=True)]
    upload_files = [name for name in ImageUpload.objects.filter(user=user).values_list("file", flat=True) if name]
    payments = Payment.objects.filter(user=user)
    screenshots = [name for name in payments.values_list("screenshot", flat=True) if name]

    with transaction.atomic():
        payments.update(user=None, payer_email=user.email, screenshot="")
        user.delete()  # cascades to projects, jobs, assets, social/ad accounts, subscriptions...

        # Files go only once the rows are really gone (a rollback keeps both).
        def remove_files():
            storage = private_storage()
            for name in screenshots:
                storage.delete(name)
            for name in upload_files:
                (media_root / name).unlink(missing_ok=True)
            for directory in project_dirs:
                shutil.rmtree(directory, ignore_errors=True)

        transaction.on_commit(remove_files)
    logger.info("Deleted account and %s project folder(s)", len(project_dirs))
