from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.utils import timezone

from content.models import Template, TemplateUseEvent


class Command(BaseCommand):
    help = "Recalculate each template's rolling 7-day usage counter."

    def handle(self, *args, **options):
        since = timezone.now() - timedelta(days=7)
        counts = dict(
            TemplateUseEvent.objects.filter(created_at__gte=since)
            .values_list("template_id")
            .annotate(total=Count("id"))
        )

        updated = 0
        for template in Template.objects.only("id", "uses_last_7d"):
            next_count = int(counts.get(template.id, 0))
            if template.uses_last_7d == next_count:
                continue
            template.uses_last_7d = next_count
            template.save(update_fields=["uses_last_7d", "updated_at"])
            updated += 1

        self.stdout.write(self.style.SUCCESS(f"Template trend counters recalculated: {updated} updated."))
