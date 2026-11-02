from django.core.management.base import BaseCommand

from content.pricing import refresh_price_snapshot


class Command(BaseCommand):
    help = "Fetch fal's current unit prices for the catalog into the shared price snapshot."

    def add_arguments(self, parser):
        parser.add_argument("--timeout", type=float, default=20.0, help="Seconds to wait per fal request.")

    def handle(self, *args, **options):
        summary = refresh_price_snapshot(timeout=options["timeout"])
        for change in summary["changed"]:
            self.stdout.write(f"  {change['endpoint_id']}: {change['from']} -> {change['to']} per {change['unit']}")
        self.stdout.write(self.style.SUCCESS(
            f"fal prices refreshed: {summary['fetched']} of {summary['requested']} models, "
            f"{len(summary['changed'])} moved more than 20%, {summary['failed']} kept their last known price."
        ))
