"""Runs agent steps for queued runs. Used by `manage.py run_agents_worker`."""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

import requests
from django.conf import settings
from django.db import DatabaseError, transaction
from django.db.models import F, Q
from django.utils import timezone

from agents import providers
from agents.models import AgentRun, RunnerHeartbeat
from agents.registry import get_agent
from agents import clips, cross_post, growth, video_edit
from agents.steps import STEPS, NeedsReview, RunCancelled, WaitUntil
from content.credits import refund_credits, reserve_credits

# The Video Editor's and Cross-poster's steps live in their own modules (they import agents.steps).
STEPS.update(video_edit.STEPS)
STEPS.update(cross_post.STEPS)
STEPS.update(clips.STEPS)
STEPS.update(growth.STEPS)

logger = logging.getLogger(__name__)

LEASE = timedelta(minutes=15)  # a run whose worker died is picked up again after this
RUNNER_ONLINE_WITHIN = timedelta(seconds=60)  # a heartbeat older than this means no runner is checking the queue
MAX_ATTEMPTS = 3
STEP_LABELS = {
    "research": "researching the topic",
    "concepts": "proposing concepts",
    "script": "writing the script",
    "voice": "recording the voice",
    "captions": "timing the captions",
    "visuals": "making the visuals",
    "render": "editing the video",
    "finish": "saving the video",
    "prepare": "reading your video",
    "transcribe": "transcribing your video",
    "clean_audio": "cleaning up the audio",
    "plan_edit": "planning the cuts",
    "render_edit": "editing your video",
    "package": "writing the title and thumbnail",
    "trends": "finding trends",
    "collect": "reading your analytics",
    "analyze": "writing the report",
    "deliver": "sending the report",
    "fetch": "reading your video",
    "listen": "transcribing your video",
    "write_post": "writing the posts",
    "post": "posting",
    "get_video": "getting your video",
    "transcribe_long": "transcribing your video",
    "find_clips": "finding the best moments",
    "render_clips": "making the clips",
    "finish_clips": "saving the clips",
}


def recover_stuck(now=None) -> int:
    """Runs whose worker died mid-step (lease expired) go back to the queue; they resume after their last step."""
    return AgentRun.objects.filter(status="running", locked_until__lt=now or timezone.now()).update(status="queued")


def due_queued_ids(now=None, limit: int = 10, only=(), exclude=()) -> list:
    """Queued runs that may start now, oldest first (a scheduled post waits until its time).

    `only` / `exclude` are agent types, so long jobs (Clip Maker) can have their own worker.
    """
    due = Q(locked_until__isnull=True) | Q(locked_until__lte=now or timezone.now())
    queued = AgentRun.objects.filter(due, status="queued")
    if only:
        queued = queued.filter(deployment__agent_type__in=only)
    if exclude:
        queued = queued.exclude(deployment__agent_type__in=exclude)
    return list(queued.order_by("created_at").values_list("id", flat=True)[:limit])


def claim(run_id, now=None) -> AgentRun | None:
    """Atomically take one queued, due run (safe with several workers); None if someone else has it."""
    now = now or timezone.now()
    due = Q(locked_until__isnull=True) | Q(locked_until__lte=now)
    taken = AgentRun.objects.filter(due, id=run_id, status="queued").update(
        status="running", locked_until=now + LEASE, attempts=F("attempts") + 1
    )
    return AgentRun.objects.select_related("deployment", "project", "user").get(id=run_id) if taken else None


def claim_next(only=(), exclude=()) -> AgentRun | None:
    """The oldest due run, for `manage.py run_agents_worker` (servers without Celery)."""
    now = timezone.now()
    recover_stuck(now)
    for run_id in due_queued_ids(now, only=only, exclude=exclude):
        run = claim(run_id, now)
        if run:
            return run
    return None


def beat(now=None) -> None:
    """Record that a runner is checking the queue. A busy database skips this beat instead of stopping the runner."""
    try:
        RunnerHeartbeat.objects.update_or_create(id=1, defaults={"seen_at": now or timezone.now()})
    except DatabaseError as exc:
        logger.warning("Could not record the runner heartbeat: %s", exc)


def runner_online(now=None) -> bool:
    """A recent heartbeat, or a run mid-step (a long render outlasts the heartbeat but keeps its lease fresh)."""
    now = now or timezone.now()
    return (
        RunnerHeartbeat.objects.filter(seen_at__gte=now - RUNNER_ONLINE_WITHIN).exists()
        or AgentRun.objects.filter(status="running", locked_until__gt=now).exists()
    )


def enqueue(run_id) -> None:
    """With Celery, start the run as soon as the database change is saved (Beat's sweep is the safety net)."""
    if settings.USE_CELERY:
        from agents.tasks import dispatch

        transaction.on_commit(lambda: dispatch(run_id))


def process(run: AgentRun) -> None:
    spec = get_agent(run.deployment.agent_type)
    if spec is None:
        fail(run, "This agent is no longer available.")
        return
    if run.attempts > MAX_ATTEMPTS:
        fail(run, "This run kept failing, so it was stopped. Your credits were refunded.")
        return
    try:
        for step in spec.steps:
            if not AgentRun.objects.filter(id=run.id, status="running").exists():
                return  # cancelled between steps
            run.step = step
            run.locked_until = timezone.now() + LEASE
            run.save(update_fields=["step", "locked_until", "updated_at"])
            used, started = providers.track(), timezone.now()
            STEPS[step](run)
            _log(run, step, started, used)
    except RunCancelled:
        logger.info("Run %s was cancelled while working", run.id)
        return
    except NeedsReview as pause:
        # Waiting for a person: nothing failed and no credits move.
        AgentRun.objects.filter(id=run.id, status="running").update(
            status="needs_review", step=pause.gate, locked_until=None
        )
        return
    except WaitUntil as wait:
        AgentRun.objects.filter(id=run.id, status="running").update(
            status="queued", step=run.step, locked_until=wait.when, attempts=0
        )
        return
    except Exception as exc:  # noqa: BLE001 — every failure must end in a refunded, readable state
        fail(run, _message(exc, STEP_LABELS.get(run.step, "running the agent")))
        return
    AgentRun.objects.filter(id=run.id, status="running").update(
        status="needs_review" if spec.review else "succeeded",
        step="final" if spec.review else "",
        locked_until=None,
        finished_at=timezone.now(),
    )


def _log(run: AgentRun, step: str, started, used: list[str]) -> None:
    """When each step ran and which services it used. A skipped (already done) step keeps its entry."""
    log = run.output.setdefault("log", {})
    if step in log and not used:
        return
    log[step] = {"startedAt": started.isoformat(), "finishedAt": timezone.now().isoformat(), "providers": used}
    run.save(update_fields=["output", "updated_at"])


def fail(run: AgentRun, message: str) -> None:
    """Mark failed and refund, exactly once even if called twice."""
    updated = AgentRun.objects.filter(id=run.id, status__in=("queued", "running")).update(
        status="failed", error=message, locked_until=None, finished_at=timezone.now()
    )
    if updated and run.credits_reserved > 0:
        refund_credits(run.user, run.credits_reserved, topup=run.topup_reserved)


def retry(run: AgentRun) -> bool:
    """Queue a failed run again, resuming after its last finished step.

    The credits refunded when it failed are reserved again (raises InsufficientCredits).
    Returns False if the run isn't failed (e.g. someone retried it already).
    """
    if run.status != "failed":
        return False
    topup = reserve_credits(run.user, run.credits_reserved) if run.credits_reserved > 0 else Decimal("0")
    updated = AgentRun.objects.filter(id=run.id, status="failed").update(
        status="queued", error="", attempts=0, locked_until=None, finished_at=None, topup_reserved=topup
    )
    if not updated and run.credits_reserved > 0:  # lost a race with another retry: give the credits back
        refund_credits(run.user, run.credits_reserved, topup=topup)
    if updated:
        enqueue(run.id)
    run.refresh_from_db()
    return bool(updated)


def cancel(run: AgentRun, message: str = "Cancelled by support. Your credits were refunded.") -> bool:
    """Stop a queued, running or paused run and refund it (admin action)."""
    updated = AgentRun.objects.filter(id=run.id, status__in=("queued", "running", "needs_review")).update(
        status="failed", error=message, locked_until=None, finished_at=timezone.now()
    )
    if updated and run.credits_reserved > 0:
        refund_credits(run.user, run.credits_reserved, topup=run.topup_reserved)
    run.refresh_from_db()
    return bool(updated)


def _message(exc: Exception, doing: str) -> str:
    """Our own errors are written for users; anything else is logged and summarised."""
    if isinstance(exc, RuntimeError) and not isinstance(exc, requests.RequestException):
        return f"{exc} Your credits were refunded."
    logger.exception("Agent step failed while %s", doing, exc_info=exc)
    if isinstance(exc, requests.RequestException):
        return f"A service needed for {doing} couldn't be reached. Your credits were refunded; please try again."
    return f"Something went wrong while {doing}. Your credits were refunded; please try again."
