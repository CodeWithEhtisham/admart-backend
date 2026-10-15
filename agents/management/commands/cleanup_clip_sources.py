from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from agents import steps
from agents.models import AgentRun

FINISHED = ("succeeded", "approved", "failed", "discarded")


class Command(BaseCommand):
    help = "Delete Clip Maker source videos and audio of runs that ended N days ago (the clips stay). Run daily."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=settings.CLIPS_KEEP_SOURCE_DAYS)

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        runs = AgentRun.objects.filter(deployment__agent_type="clip-maker", status__in=FINISHED, finished_at__lt=cutoff)
        freed = 0
        for run in runs.iterator():
            if run.output.get("source_deleted"):
                continue
            for key in ("clip_source", "clip_audio"):
                if run.output.get(key):
                    path = steps.media_path(run.output[key])
                    if path.exists():
                        freed += path.stat().st_size
                        path.unlink()
            folder = steps.media_path(f"projects/{run.project_id}/agents/{run.id}")
            for part in folder.glob("source.*"):  # an unfinished download (.part)
                freed += part.stat().st_size
                part.unlink()
            run.output["source_deleted"] = True
            run.save(update_fields=["output", "updated_at"])
        self.stdout.write(f"Freed {freed / 1024**3:.2f} GB")
