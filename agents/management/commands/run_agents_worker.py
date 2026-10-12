import time

from django.core.management.base import BaseCommand

from agents.engine import claim_next, process


class Command(BaseCommand):
    help = "Process queued agent runs (YouTube Shorts Creator, Script Writer, Voiceover)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process everything queued, then exit.")
        parser.add_argument("--poll", type=float, default=3.0, help="Seconds to wait when the queue is empty.")

    def handle(self, *args, **options):
        while True:
            run = claim_next()
            if run is not None:
                self.stdout.write(f"Agent run {run.id} ({run.deployment.agent_type})")
                process(run)
                continue
            if options["once"]:
                return
            time.sleep(options["poll"])
