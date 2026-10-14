import logging
import time

from django.core.management.base import BaseCommand
from django.db import DatabaseError, close_old_connections

from agents.engine import claim_next, process
from agents.runs import run_due

SCHEDULE_EVERY = 30  # seconds between Autopilot checks

logger = logging.getLogger("agents.worker")


class Command(BaseCommand):
    help = "Process queued agent runs (YouTube Shorts Creator, Script Writer, Voiceover)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process everything queued, then exit.")
        parser.add_argument("--poll", type=float, default=3.0, help="Seconds to wait when the queue is empty.")
        parser.add_argument("--only", nargs="*", default=[], help="Only these agent types (e.g. clip-maker).")
        parser.add_argument("--exclude", nargs="*", default=[], help="Never these agent types.")

    def handle(self, *args, **options):
        last_schedule = 0.0
        while True:
            try:
                if time.monotonic() - last_schedule >= SCHEDULE_EVERY or options["once"]:
                    started = run_due()
                    if started:
                        self.stdout.write(f"Autopilot started {started} run(s)")
                    last_schedule = time.monotonic()
                run = claim_next(only=options["only"], exclude=options["exclude"])
            except DatabaseError as exc:
                # A busy database (e.g. SQLite locked by another process) must not stop the worker.
                logger.warning("Database busy, trying again: %s", exc)
                close_old_connections()
                time.sleep(options["poll"])
                continue
            if run is not None:
                self.stdout.write(f"Agent run {run.id} ({run.deployment.agent_type})")
                process(run)
                continue
            if options["once"]:
                return
            time.sleep(options["poll"])
