"""Celery tasks for agents. Beat runs `sweep` every 15 s; new and resumed runs are dispatched at once."""

from celery import shared_task
from django.core.cache import cache

from agents import engine
from agents.runs import run_due

DISPATCH_TTL = 300  # seconds a run counts as "already sent to a worker"


def dispatch(run_id) -> None:
    """Send a run to a worker once; the sweep re-sends it if it is still queued after DISPATCH_TTL."""
    if cache.add(f"agents:dispatched:{run_id}", 1, timeout=DISPATCH_TTL):
        process_run.delay(str(run_id))


@shared_task(ignore_result=True)
def process_run(run_id: str) -> None:
    """Claim the run (atomic: two workers never take the same run) and work through its steps."""
    run = engine.claim(run_id)
    cache.delete(f"agents:dispatched:{run_id}")
    if run is not None:
        engine.process(run)


@shared_task(ignore_result=True)
def sweep() -> None:
    """Recover runs whose worker died, start due Autopilot/report slots, dispatch every due queued run."""
    engine.beat()  # a sweep running means Beat and a Celery worker are both up
    engine.recover_stuck()
    run_due()
    for run_id in engine.due_queued_ids(limit=50):
        dispatch(run_id)
