"""Runs agent steps for queued runs. Used by `manage.py run_agents_worker`."""

from __future__ import annotations

import logging
from datetime import timedelta

import requests
from django.db.models import F
from django.utils import timezone

from agents.models import AgentRun
from agents.registry import AGENTS
from agents.steps import STEPS, NeedsReview
from content.credits import refund_credits

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
}


def claim_next() -> AgentRun | None:
    """Atomically take the oldest queued run (safe with several workers)."""
    now = timezone.now()
    AgentRun.objects.filter(status="running", locked_until__lt=now).update(status="queued")
    for run_id in AgentRun.objects.filter(status="queued").order_by("created_at").values_list("id", flat=True)[:10]:
        taken = AgentRun.objects.filter(id=run_id, status="queued").update(
            status="running", locked_until=now + LEASE, attempts=F("attempts") + 1
        )
        if taken:
            return AgentRun.objects.select_related("deployment", "project", "user").get(id=run_id)
    return None


def process(run: AgentRun) -> None:
    spec = AGENTS.get(run.deployment.agent_type)
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
            STEPS[step](run)
    except NeedsReview as pause:
        # Waiting for a person: nothing failed and no credits move.
        AgentRun.objects.filter(id=run.id, status="running").update(
            status="needs_review", step=pause.gate, locked_until=None
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


def fail(run: AgentRun, message: str) -> None:
    """Mark failed and refund, exactly once even if called twice."""
    updated = AgentRun.objects.filter(id=run.id, status__in=("queued", "running")).update(
        status="failed", error=message, locked_until=None, finished_at=timezone.now()
    )
    if updated and run.credits_reserved > 0:
        refund_credits(run.user, run.credits_reserved, topup=run.topup_reserved)


def _message(exc: Exception, doing: str) -> str:
    """Our own errors are written for users; anything else is logged and summarised."""
    if isinstance(exc, RuntimeError) and not isinstance(exc, requests.RequestException):
        return f"{exc} Your credits were refunded."
    logger.exception("Agent step failed while %s", doing, exc_info=exc)
    if isinstance(exc, requests.RequestException):
        return f"A service needed for {doing} couldn't be reached. Your credits were refunded; please try again."
    return f"Something went wrong while {doing}. Your credits were refunded; please try again."
