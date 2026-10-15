"""Starting runs (Run now and Autopilot) and Autopilot scheduling."""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Sum
from django.utils import timezone

from agents.models import AgentDeployment, AgentRun
from agents.registry import estimate_credits, get_agent
from content.credits import InsufficientCredits, reserve_credits

OPEN_STATUSES = ("queued", "running")
MAX_OPEN_RUNS = 3  # per deployment, so a double-click can't queue (and charge) a pile of runs
MAX_QUEUED_TOPICS = 50
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class RunRefused(Exception):
    """A run can't start; message is safe to show users."""

    def __init__(self, message: str, code: str = "INVALID", credits: Decimal | None = None):
        super().__init__(message)
        self.message, self.code, self.credits = message, code, credits


def month_spend(deployment: AgentDeployment) -> Decimal:
    start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = (
        deployment.runs.filter(created_at__gte=start)
        .exclude(status="failed")  # failed runs were refunded
        .aggregate(total=Sum("credits_reserved"))["total"]
    )
    return total or Decimal("0")


def start_run(deployment: AgentDeployment, run_input: dict) -> AgentRun:
    """Check limits, reserve credits and queue a run. Raises RunRefused."""
    spec = get_agent(deployment.agent_type)
    if spec is None:
        raise RunRefused("This agent is no longer available.")
    if deployment.status != "active":
        raise RunRefused("This agent is paused. Resume it to run.", "AGENT_PAUSED")
    open_runs = deployment.runs.filter(status__in=OPEN_STATUSES).exclude(status="queued", step="wait")  # scheduled
    if open_runs.count() >= MAX_OPEN_RUNS:
        raise RunRefused("This agent already has jobs in progress. Wait for one to finish.", "AGENT_BUSY")
    credits = estimate_credits(spec, run_input, deployment.config)
    limit = deployment.monthly_credit_limit
    if limit is not None and month_spend(deployment) + credits > limit:
        raise RunRefused("This run would go over the agent's monthly credit limit.", "AGENT_MONTHLY_LIMIT")
    try:
        topup = reserve_credits(deployment.user, credits)
    except InsufficientCredits:
        raise RunRefused("Insufficient credits", "INSUFFICIENT_CREDITS", credits) from None
    return AgentRun.objects.create(
        deployment=deployment,
        project=deployment.project,
        user=deployment.user,
        input=run_input,
        credits_reserved=credits,
        topup_reserved=topup,
    )


# ── schedule ──────────────────────────────────────────────────────────────


def clean_schedule(raw) -> dict:
    """Validate {"days": [0-6], "time": "HH:MM", "tz": "Area/City"}. Raises ValueError."""
    if not isinstance(raw, dict):
        raise ValueError("Schedule must be an object.")
    days = raw.get("days")
    if not isinstance(days, list) or not days or any(not isinstance(d, int) or not 0 <= d <= 6 for d in days):
        raise ValueError("Pick at least one day.")
    at = str(raw.get("time", ""))
    if not TIME_RE.match(at):
        raise ValueError("Time must be HH:MM (24-hour).")
    tz = str(raw.get("tz") or "UTC")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Unknown time zone.") from None
    return {"days": sorted(set(days)), "time": at, "tz": tz}


def clean_topics(raw) -> list[str]:
    if not isinstance(raw, list):
        raise ValueError("Topics must be a list.")
    topics = [" ".join(str(t).split())[:200] for t in raw if str(t).strip()]
    if len(topics) > MAX_QUEUED_TOPICS:
        raise ValueError(f"Up to {MAX_QUEUED_TOPICS} queued topics.")
    return topics


def next_slot(schedule: dict, after: datetime) -> datetime | None:
    """The first scheduled moment strictly after `after` (aware), or None without a schedule."""
    if not schedule.get("days") or not TIME_RE.match(str(schedule.get("time", ""))):
        return None
    tz = ZoneInfo(schedule.get("tz") or "UTC")
    hour, minute = map(int, schedule["time"].split(":"))
    local = after.astimezone(tz)
    for offset in range(8):
        day = local.date() + timedelta(days=offset)
        if day.weekday() in schedule["days"]:
            candidate = datetime.combine(day, time(hour, minute), tzinfo=tz)
            if candidate > after:
                return candidate
    return None


def run_due(now: datetime | None = None) -> int:
    """Start the Autopilot runs that are due. Safe with several workers (each slot is claimed once)."""
    now = now or timezone.now()
    started = 0
    due = AgentDeployment.objects.filter(autopilot=True, status="active", next_run_at__lte=now).select_related(
        "user", "project"
    )
    for deployment in due[:50]:
        spec = get_agent(deployment.agent_type)
        report = bool(spec and spec.input_kind == "report")
        every = (deployment.config or {}).get("period") if report else None
        # Reports every 15 or 30 days: the next one is that many days after this slot.
        upcoming = deployment.next_run_at + timedelta(days=every) if every in (15, 30) else next_slot(deployment.schedule, now)
        claimed = AgentDeployment.objects.filter(id=deployment.id, next_run_at=deployment.next_run_at).update(
            next_run_at=upcoming
        )
        if not claimed:
            continue  # another worker took this slot
        deployment.refresh_from_db()
        queue = [] if report else list(deployment.topic_queue or [])
        run_input = {"period": every or 7} if report else {"topic": queue[0]} if queue else {"topic": "", "auto": True}
        try:
            start_run(deployment, run_input)
        except RunRefused as refused:
            note = "not enough credits" if refused.code == "INSUFFICIENT_CREDITS" else refused.message.rstrip(".").lower()
            when = timezone.localtime(now, ZoneInfo(deployment.schedule.get("tz") or "UTC")).strftime("%a %d %b %H:%M")
            AgentDeployment.objects.filter(id=deployment.id).update(autopilot_note=f"Skipped {when}: {note}."[:200])
            continue
        AgentDeployment.objects.filter(id=deployment.id).update(topic_queue=queue[1:], autopilot_note="")
        started += 1
    return started
