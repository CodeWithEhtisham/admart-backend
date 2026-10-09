from django.core.management.base import BaseCommand

from content.library import sync_library_from_image_job
from content.models import ImageJob


class Command(BaseCommand):
    help = "Backfill LibraryAsset rows from existing succeeded/failed image jobs."

    def handle(self, *args, **options):
        qs = ImageJob.objects.filter(status__in=["succeeded", "failed"]).order_by("created_at")
        created = 0
        for job in qs.iterator():
            assets = sync_library_from_image_job(job)
            created += len(assets)
        self.stdout.write(self.style.SUCCESS(f"Synced {created} library asset(s) from {qs.count()} job(s)."))
