from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from agents import steps
from agents.models import AgentRun
from content.models import LibraryAsset

FINISHED = ("succeeded", "approved", "failed", "discarded")


def in_library(run, rel: str) -> bool:
    """Whether a library item of the run's project still shows this file."""
    return LibraryAsset.objects.filter(
        project_id=run.project_id, deleted_at__isnull=True, source_url__endswith=f"{settings.MEDIA_URL}{rel}"
    ).exists()


class Command(BaseCommand):
    help = ("Delete Clip Maker source videos and audio of runs that ended N days ago (the clips stay). "
            "A source that is a library video stays while it is still in the library. Run daily.")

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=settings.CLIPS_KEEP_SOURCE_DAYS)

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        runs = AgentRun.objects.filter(deployment__agent_type="clip-maker", status__in=FINISHED, finished_at__lt=cutoff)
        freed = 0
        for run in runs.iterator():
            if run.output.get("source_deleted") or run.output.get("source_cleaned"):
                continue
            own = f"projects/{run.project_id}/agents/{run.id}/"
            source = run.output.get("clip_source") or ""
            kept = bool(source) and not source.startswith(own) and in_library(run, source)
            for key in ("clip_audio",) if kept else ("clip_source", "clip_audio"):
                if run.output.get(key):
                    path = steps.media_path(run.output[key])
                    if path.exists():
                        freed += path.stat().st_size
                        path.unlink()
            folder = steps.media_path(own)
            for part in folder.glob("source.*"):  # an unfinished download (.part)
                freed += part.stat().st_size
                part.unlink()
            # A library source stays and is still shown; it's the library's to delete.
            run.output["source_cleaned" if kept else "source_deleted"] = True
            run.save(update_fields=["output", "updated_at"])
        self.stdout.write(f"Freed {freed / 1024**3:.2f} GB")
