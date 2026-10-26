import logging
import threading
import time

from django.core.management.base import BaseCommand
from django.db import DatabaseError, close_old_connections, connection

from agents.engine import beat, claim_next, process
from agents.runs import run_due
from content import fal_models, pricing

SCHEDULE_EVERY = 30  # seconds between Autopilot checks
PRICES_EVERY = 30 * 60  # seconds between checks that fal's price snapshot is fresh (refreshed when 6 h old)
# and that the list of new fal models is fresh (checked once a day)
BEAT_EVERY = 10  # seconds between heartbeats (the page shows the runner offline after 60 s without one)

logger = logging.getLogger("agents.worker")


def refresh_fal_catalog() -> None:
    """fal's prices and new models. After a long break both are stale and fal can take minutes to answer."""
    try:
        pricing.refresh_prices_if_stale()
    except Exception as exc:  # prices must never stop the worker
        logger.warning("fal price refresh failed, keeping the last known prices: %s", exc)
    try:
        fal_models.discover_if_stale()
    except Exception as exc:  # nor must the new-model check
        logger.warning("fal new-model check failed: %s", exc)
    finally:
        connection.close()  # this thread's own database connection


class Command(BaseCommand):
    help = "Process queued agent runs (YouTube Shorts Creator, Script Writer, Voiceover)."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process everything queued, then exit.")
        parser.add_argument("--poll", type=float, default=3.0, help="Seconds to wait when the queue is empty.")
        parser.add_argument("--only", nargs="*", default=[], help="Only these agent types (e.g. clip-maker).")
        parser.add_argument("--exclude", nargs="*", default=[], help="Never these agent types.")

    def handle(self, *args, **options):
        last_schedule = last_beat = 0.0
        last_prices = float("-inf")
        refresher = None
        while True:
            if not options["once"] and time.monotonic() - last_prices >= PRICES_EVERY \
                    and not (refresher and refresher.is_alive()):
                last_prices = time.monotonic()
                # In the background, so the heartbeat and queued runs never wait for fal.
                refresher = threading.Thread(target=refresh_fal_catalog, name="fal-catalog-refresh", daemon=True)
                refresher.start()
            if time.monotonic() - last_beat >= BEAT_EVERY:
                beat()
                last_beat = time.monotonic()
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
