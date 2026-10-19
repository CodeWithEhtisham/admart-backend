"""Starting runs (Run now and Autopilot) and Autopilot scheduling."""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Sum
from django.utils import timezone

from agents.clips import max_seconds
from agents.cross_post import connected
from agents.engine import enqueue
from agents.models import AgentDeployment, AgentRun
from agents.registry import MAX_TEXT_INPUT, MAX_VIDEO_SECONDS, estimate_credits, get_agent
from agents.video_edit import asset_file, probe
from content.credits import InsufficientCredits, reserve_credits
from content.models import LibraryAsset

OPEN_STATUSES = ("queued", "running")
MAX_OPEN_RUNS = 3  # per deployment, so a double-click can't queue (and charge) a pile of runs
MAX_QUEUED_TOPICS = 50
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
MODES = ("manual", "daily", "weekly", "monthly")
VIDEO_CANDIDATES = 10  # newest unused Library videos checked per scheduled video run


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
    run = AgentRun.objects.create(
        deployment=deployment,
        project=deployment.project,
        user=deployment.user,
        input=run_input,
        credits_reserved=credits,
        topup_reserved=topup,
    )
    enqueue(run.id)
    return run


# ── schedule ──────────────────────────────────────────────────────────────


def schedule_mode(schedule: dict) -> str:
    """A schedule's mode; one saved before modes existed (days, no mode) is weekly."""
    return (schedule or {}).get("mode") or ("weekly" if (schedule or {}).get("days") else "manual")


def clean_schedule(raw) -> dict:
    """Validate {"mode": manual|daily|weekly|monthly, "time": "HH:MM", "days": [0-6] (weekly),
    "dayOfMonth": 1-28 (monthly), "tz": "Area/City"}, keeping only the fields of its mode. Raises ValueError."""
    if not isinstance(raw, dict):
        raise ValueError("Schedule must be an object.")
    mode = raw.get("mode") or "weekly"
    if mode not in MODES:
        raise ValueError("Pick manual, daily, weekly or monthly.")
    if mode == "manual":
        return {"mode": mode}
    cleaned = {"mode": mode}
    if mode == "weekly":
        days = raw.get("days")
        if not isinstance(days, list) or not days or any(not isinstance(d, int) or not 0 <= d <= 6 for d in days):
            raise ValueError("Pick at least one day.")
        cleaned["days"] = sorted(set(days))
    if mode == "monthly":
        day = raw.get("dayOfMonth")
        if not isinstance(day, int) or isinstance(day, bool) or not 1 <= day <= 28:
            raise ValueError("Pick a day of the month from 1 to 28.")
        cleaned["dayOfMonth"] = day
    at = str(raw.get("time", ""))
    if not TIME_RE.match(at):
        raise ValueError("Time must be HH:MM (24-hour).")
    tz = str(raw.get("tz") or "UTC")
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Unknown time zone.") from None
    return {**cleaned, "time": at, "tz": tz}


def clean_texts(raw) -> list[str]:
    """Voiceover queue: texts to read, each up to MAX_TEXT_INPUT characters."""
    if not isinstance(raw, list):
        raise ValueError("Texts must be a list.")
    texts = [str(t).strip() for t in raw if str(t).strip()]
    if any(len(t) > MAX_TEXT_INPUT for t in texts):
        raise ValueError(f"Each text can be up to {MAX_TEXT_INPUT:,} characters.")
    if len(texts) > MAX_QUEUED_TOPICS:
        raise ValueError(f"Up to {MAX_QUEUED_TOPICS} queued texts.")
    return texts


def clean_topics(raw) -> list[str]:
    if not isinstance(raw, list):
        raise ValueError("Topics must be a list.")
    topics = [" ".join(str(t).split())[:200] for t in raw if str(t).strip()]
    if len(topics) > MAX_QUEUED_TOPICS:
        raise ValueError(f"Up to {MAX_QUEUED_TOPICS} queued topics.")
    return topics


def next_slot(schedule: dict, after: datetime) -> datetime | None:
    """The first scheduled moment strictly after `after` (aware), or None without a schedule (or manual)."""
    mode = schedule_mode(schedule)
    if mode == "manual" or not TIME_RE.match(str(schedule.get("time", ""))):
        return None
    tz = ZoneInfo(schedule.get("tz") or "UTC")
    hour, minute = map(int, schedule["time"].split(":"))
    local = after.astimezone(tz)
    if mode == "monthly":
        day = schedule.get("dayOfMonth")
        if not isinstance(day, int) or not 1 <= day <= 28:
            return None
        year, month = local.year, local.month
        for _ in range(2):  # this month's slot, or next month's
            candidate = datetime(year, month, day, hour, minute, tzinfo=tz)
            if candidate > after:
                return candidate
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return None
    days = range(7) if mode == "daily" else schedule.get("days") or []
    for offset in range(8):
        day = local.date() + timedelta(days=offset)
        if day.weekday() in days:
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
        queue = list(deployment.topic_queue or [])
        try:
            run_input, pops = _scheduled_input(deployment, spec, every)
            start_run(deployment, run_input)
        except RunRefused as refused:
            note = ("not enough credits" if refused.code == "INSUFFICIENT_CREDITS" else refused.message
                    if refused.code == "NO_INPUT" else refused.message.rstrip(".").lower())
            when = timezone.localtime(now, ZoneInfo(deployment.schedule.get("tz") or "UTC")).strftime("%a %d %b %H:%M")
            AgentDeployment.objects.filter(id=deployment.id).update(autopilot_note=f"Skipped {when}: {note}."[:200])
            continue
        AgentDeployment.objects.filter(id=deployment.id).update(topic_queue=queue[1:] if pops else queue, autopilot_note="")
        started += 1
    return started


def _scheduled_input(deployment: AgentDeployment, spec, period) -> tuple[dict, bool]:
    """A scheduled run's input, and whether it uses the first queued topic or text. Raises RunRefused
    (code NO_INPUT: the message is the skip note as is)."""
    queue = deployment.topic_queue or []
    if spec is None:
        raise RunRefused("This agent is no longer available.")
    if spec.input_kind == "report":
        return {"period": period or 7}, False
    if "trends" in spec.steps:
        return {"window": {"daily": "day", "weekly": "week", "monthly": "month"}[schedule_mode(deployment.schedule)]}, False
    if spec.input_kind == "video":
        return _scheduled_video(deployment, spec), False
    if spec.input_kind == "text":
        if not queue:
            raise RunRefused("no text left to read", "NO_INPUT")
        return {"text": queue[0]}, True
    return ({"topic": queue[0]}, True) if queue else ({"topic": "", "auto": True}, False)


def _scheduled_video(deployment: AgentDeployment, spec) -> dict:
    """The newest Library video no earlier run of this agent used, as a manual start sends it
    ({"assetId", "seconds", "title"}). Videos too long for the agent are passed over."""
    if "post" in spec.steps and not connected(deployment.project_id):
        raise RunRefused("Connect YouTube, Instagram or Facebook on Social Accounts first", "NO_INPUT")
    used = [a for a in deployment.runs.values_list("input__assetId", flat=True) if a]
    videos = (
        LibraryAsset.objects.filter(project_id=deployment.project_id, media_type="video", deleted_at__isnull=True)
        .exclude(status__in=("generating", "failed"))
        .exclude(id__in=used)
    )
    if "post" not in spec.steps:  # the Video Editor and Clip Maker don't take agent-made videos (their own results)
        videos = videos.exclude(capability="agent")
    limit, leeway = None, 0  # same limits (and leeway) as a manual start
    if "get_video" in spec.steps:
        limit, leeway = max_seconds(deployment.user), 5
    elif "prepare" in spec.steps:
        limit, leeway = MAX_VIDEO_SECONDS, 1
    too_long = False
    for asset in videos.order_by("-created_at")[:VIDEO_CANDIDATES]:
        seconds, path = None, asset_file(asset)
        if path:
            try:
                seconds = probe(path)["duration"]
            except RuntimeError:
                continue
        if limit and seconds and seconds > limit + leeway:
            too_long = True
            continue
        return {"assetId": str(asset.id), "seconds": seconds, "title": asset.title[:120]}
    if too_long:
        raise RunRefused(f"your new videos are longer than this agent takes (up to {limit // 60} minutes)", "NO_INPUT")
    raise RunRefused("no new video in your Library", "NO_INPUT")
