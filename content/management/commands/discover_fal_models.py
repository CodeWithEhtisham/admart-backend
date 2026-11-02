from django.core.management.base import BaseCommand

from content.fal_models import discover_new_models


class Command(BaseCommand):
    help = "List fal image/video models Admart doesn't offer yet, for staff to review in the admin."

    def handle(self, *args, **options):
        new_ids = discover_new_models()
        for endpoint_id in new_ids:
            self.stdout.write(f"  new: {endpoint_id}")
        self.stdout.write(self.style.SUCCESS(
            f"fal model check done: {len(new_ids)} new model(s). Review them in the admin under 'Fal model listings'."
        ))
