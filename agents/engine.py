"""Runs agent steps for queued runs. Used by `manage.py run_agents_worker`."""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

import requests
from django.db.models import F, Q
from django.utils import timezone

from agents import providers
from agents.models import AgentRun
from agents.registry import get_agent
from agents import cross_post, video_edit
from agents.steps import STEPS, NeedsReview, WaitUntil
from content.credits import refund_credits, reserve_credits

# The Video Editor's and Cross-poster's steps live in their own modules (they import agents.steps).
STEPS.update(video_edit.STEPS)
STEPS.update(cross_post.STEPS)

logger = logging.getLogger(__name__)

LEASE = timedelta(minutes=15)  # a run whose worker died is picked up again after this
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
    "fetch": "reading your video",
    "listen": "transcribing your video",
    "write_post": "writing the posts",
    "post": "posting",
}


def claim_next() -> AgentRun | None:
    """Atomically take the oldest queued run (safe with several workers)."""
    now = timezone.now()
    AgentRun.objects.filter(status="running", locked_until__lt=now).update(status="queued")
    due = Q(locked_until__isnull=True) | Q(locked_until__lte=now)  # a scheduled post waits until its time
    for run_id in AgentRun.objects.filter(due, status="queued").order_by("created_at").values_list("id", flat=True)[:10]:
        taken = AgentRun.objects.filter(id=run_id, status="queued").update(
            status="running", locked_until=now + LEASE, attempts=F("attempts") + 1
        )
        if taken:
            return AgentRun.objects.select_related("deployment", "project", "user").get(id=run_id)
    return None


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
            run.step = step
            run.locked_until = timezone.now() + LEASE
            run.save(update_fields=["step", "locked_until", "updated_at"])
            used, started = providers.track(), timezone.now()
            STEPS[step](run)
            _log(run, step, started, used)
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
