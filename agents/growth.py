"""Growth Report agent: every 7, 15 or 30 days, what happened, why, and a plan for the next period.

collect → analyze → deliver. Plan: docs/plans/2026-10-15-growth-report-agent.md

Numbers are computed here; the AI only interprets them and writes the plan. YouTube Analytics data is
Authorized Data (policy III.E.4.b): kept with the report while the user stays connected, re-checked on
every run, and removed from saved reports when YouTube is disconnected (projects.views).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, time, timedelta

import requests
from django.conf import settings
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.html import escape

from agents import providers
from agents import steps as base
from projects.insights import attach_metrics
from projects.models import PublishJob, SocialAccount
from projects.oauth import REQUEST_TIMEOUT, ensure_fresh_access_token
from projects.publish import PLATFORM_LABELS

logger = logging.getLogger(__name__)

PERIODS = (7, 15, 30)
MAX_EMAILS = 5
ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
ANALYTICS_SCOPE = "https://www.googleapis.com/auth/yt-analytics.readonly"
MONEY_SCOPE = "https://www.googleapis.com/auth/yt-analytics-monetary.readonly"
YT_METRICS = ("views", "estimatedMinutesWatched", "averageViewPercentage", "subscribersGained", "subscribersLost",
              "likes", "comments", "shares")
GOAL_METRICS = {  # id -> (label, how to read it from the numbers)
    "views": ("views", lambda n: (n.get("youtube") or {}).get("now", {}).get("views")),
    "subscribers": ("new subscribers", lambda n: _net_subs((n.get("youtube") or {}).get("now"))),
    "watch_hours": ("watch hours", lambda n: _hours((n.get("youtube") or {}).get("now"))),
    "posts": ("posts published", lambda n: n["posts"]["count"]),
}
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

REPORT_PROMPT = """You are a social media growth coach writing a short report for a small business or creator.
You get this period's numbers as JSON, already compared with the previous period. Use ONLY these numbers:
never invent figures. If data is thin, say so plainly.
Return JSON only:
{"verdict": string, "wins": [string], "losses": [string],
 "plan": [{"topic": string, "hook": string, "format": string, "platform": string, "day": string, "time": string, "why": string}],
 "actions": [string]}
- verdict: 2-3 plain sentences: how the period went and the single most important reason.
- wins / losses: up to 3 each. Explain WHY using the top videos, posts and best days (name the video, format,
  day or topic). Never just repeat a total. If only totals exist, say what to test to learn more.
- plan: exactly the number of posts asked for. Mix more of what worked with fresh topics people search
  for now in the niche. topic at most 12 words; hook 9-24 words that talk to "you"; format is short video,
  long video or image; platform is one of the connected ones; day is a weekday name; time is HH:MM.
- actions: 3 growth actions for the next period, each tied to THIS data (name a day, a video, a format or a
  number), each one sentence. Nothing generic like "engage with your audience".
Use web search only to find fresh topics for the plan. Never cite sources or name websites, and never mention
APIs, tools, analytics software or Admart itself."""


def period_of(deployment) -> int:
    value = (deployment.config or {}).get("period")
    return value if value in PERIODS else 7


def period(run) -> int:
    return run.input.get("period") if run.input.get("period") in PERIODS else period_of(run.deployment)


def _net_subs(yt: dict | None):
    return None if not yt else (yt.get("subscribersGained") or 0) - (yt.get("subscribersLost") or 0)


def _hours(yt: dict | None):
    return None if not yt or yt.get("estimatedMinutesWatched") is None else round(yt["estimatedMinutesWatched"] / 60, 1)


def change(now, before):
    """Percent change, or None when it can't be computed."""
    if now is None or before in (None, 0):
        return None
    return round(100 * (now - before) / before)


# ── YouTube Analytics ─────────────────────────────────────────────────────


def _yt_report(token: str, start: date, end: date, metrics, **extra) -> dict:
    resp = requests.get(ANALYTICS_URL, headers={"Authorization": f"Bearer {token}"}, timeout=REQUEST_TIMEOUT, params={
        "ids": "channel==MINE", "startDate": start.isoformat(), "endDate": end.isoformat(),
        "metrics": ",".join(metrics), **extra,
    })
    resp.raise_for_status()
    return resp.json()


def _rows(data: dict) -> list[dict]:
    names = [h["name"] for h in data.get("columnHeaders") or []]
    return [dict(zip(names, row)) for row in data.get("rows") or []]


def youtube_numbers(account, now: tuple[date, date], before: tuple[date, date]) -> dict:
    """Channel totals for both periods, revenue when allowed, top videos and the subscriber count."""
    token = ensure_fresh_access_token(account)
    totals = [(_rows(_yt_report(token, *span, YT_METRICS)) or [{}])[0] for span in (now, before)]
    out = {"now": totals[0], "before": totals[1]}
    if MONEY_SCOPE in (account.scope or ""):
        try:
            out["revenue_now"], out["revenue_before"] = [
                ((_rows(_yt_report(token, *span, ["estimatedRevenue"])) or [{}])[0]).get("estimatedRevenue")
                for span in (now, before)
            ]
        except requests.HTTPError:  # not a monetized channel
            pass
    top = _rows(_yt_report(token, *now, ["views", "averageViewPercentage", "likes", "comments", "subscribersGained"],
                           dimensions="video", sort="-views", maxResults=10))
    if top:
        meta = requests.get("https://www.googleapis.com/youtube/v3/videos", headers={"Authorization": f"Bearer {token}"},
                            params={"part": "snippet", "id": ",".join(r["video"] for r in top)}, timeout=REQUEST_TIMEOUT)
        snippets = {v["id"]: v["snippet"] for v in (meta.json() if meta.ok else {}).get("items", [])}
        for row in top:
            snippet = snippets.get(row["video"]) or {}
            row["title"] = snippet.get("title", "")
            row["publishedAt"] = snippet.get("publishedAt", "")
    out["top"] = top
    stats = requests.get("https://www.googleapis.com/youtube/v3/channels", headers={"Authorization": f"Bearer {token}"},
                         params={"part": "statistics", "mine": "true"}, timeout=REQUEST_TIMEOUT)
    items = (stats.json() if stats.ok else {}).get("items") or [{}]
    out["subscribers_total"] = int((items[0].get("statistics") or {}).get("subscriberCount") or 0) or None
    return out


def _followers(account) -> int | None:
    """Instagram or Facebook Page followers right now (best effort; read live, not stored separately)."""
    from projects.publish import _facebook_accounts, _ig_user_id, ig_graph

    try:
        if account.platform == "instagram":
            token = ensure_fresh_access_token(account)
            resp = requests.get(f"{ig_graph(account)}/{_ig_user_id(account, token)}",
                                params={"fields": "followers_count", "access_token": token}, timeout=REQUEST_TIMEOUT)
            return resp.json().get("followers_count") if resp.ok else None
        pages = _facebook_accounts(account)
        if pages:
            page = pages[0]
            resp = requests.get(f"https://graph.facebook.com/v21.0/{page['id']}",
                                params={"fields": "followers_count", "access_token": page.get("access_token", "")},
                                timeout=REQUEST_TIMEOUT)
            return resp.json().get("followers_count") if resp.ok else None
    except Exception:  # noqa: BLE001 — a missing follower count must not stop the report
        logger.warning("Follower count unavailable for %s", account.platform, exc_info=True)
    return None


# ── posts published through Admart ────────────────────────────────────────


def admart_posts(project_id, start, end) -> list[dict]:
    """One row per platform a post went to in [start, end), with its live stats."""
    rows = []
    for job in PublishJob.objects.filter(project_id=project_id, created_at__gte=start, created_at__lt=end,
                                         status__in=("succeeded", "partial")):
        for platform in job.platforms or []:
            result = (job.results or {}).get(platform) or {}
            if result.get("status") in ("succeeded", "scheduled"):
                rows.append({"title": job.title or "Untitled", "kind": job.kind, "platform": platform,
                             "status": "succeeded", "externalId": result.get("externalId") or "",
                             "pageId": result.get("pageId") or "", "createdAt": job.created_at})
    from projects.models import Project

    attach_metrics(Project.objects.get(id=project_id), rows)
    return rows


def best_days(posts: list[dict], top_videos: list[dict]) -> list[dict]:
    """Average views by weekday of publishing, from the user's own posts (most views first)."""
    by_day: dict[int, list[int]] = {}
    for p in posts:
        if p.get("views") is not None:
            by_day.setdefault(timezone.localtime(p["createdAt"]).weekday(), []).append(p["views"])
    for v in top_videos:
        if v.get("publishedAt"):
            day = date.fromisoformat(v["publishedAt"][:10]).weekday()
            by_day.setdefault(day, []).append(int(v.get("views") or 0))
    rows = [{"day": WEEKDAYS[d], "posts": len(views), "avg_views": round(sum(views) / len(views))}
            for d, views in by_day.items()]
    return sorted(rows, key=lambda r: -r["avg_views"])


# ── steps ─────────────────────────────────────────────────────────────────


def step_collect(run) -> None:
    if run.output.get("numbers"):
        return
    days = period(run)
    end = timezone.localdate() - timedelta(days=1)  # analytics lag: up to yesterday
    start = end - timedelta(days=days - 1)
    before = (start - timedelta(days=days), start - timedelta(days=1))
    accounts = {a.platform: a for a in SocialAccount.objects.filter(project_id=run.project_id, connected=True)}
    numbers: dict = {"period": days, "start": start.isoformat(), "end": end.isoformat(), "youtube": None, "notes": []}

    youtube = accounts.get("youtube")
    if not youtube:
        numbers["notes"].append("YouTube is not connected.")
    elif ANALYTICS_SCOPE not in (youtube.scope or "") and not settings.AGENTS_DRY_RUN:
        numbers["notes"].append("reconnect_youtube")
    elif settings.AGENTS_DRY_RUN:
        numbers["youtube"] = {"now": {"views": 1200, "estimatedMinutesWatched": 2400, "subscribersGained": 30,
                                      "subscribersLost": 4, "averageViewPercentage": 61, "likes": 80},
                              "before": {"views": 900, "estimatedMinutesWatched": 1900, "subscribersGained": 21,
                                         "subscribersLost": 5, "averageViewPercentage": 55, "likes": 60},
                              "subscribers_total": 1450, "top": [
                                  {"video": "dry1", "title": "How to bloom coffee in 30 seconds", "views": 640,
                                   "averageViewPercentage": 78, "likes": 41, "publishedAt": "2026-10-07T17:00:00Z"},
                                  {"video": "dry2", "title": "3 coffee myths baristas hate", "views": 380,
                                   "averageViewPercentage": 52, "likes": 22, "publishedAt": "2026-10-09T09:00:00Z"},
                                  {"video": "dry3", "title": "Why your espresso is sour", "views": 180,
                                   "averageViewPercentage": 35, "likes": 9, "publishedAt": "2026-10-11T12:00:00Z"}]}
    else:
        try:
            numbers["youtube"] = youtube_numbers(youtube, (start, end), before)
        except requests.HTTPError as exc:  # access revoked or API refused
            logger.warning("YouTube Analytics unavailable: %s", exc)
            numbers["notes"].append("reconnect_youtube")
    for platform in ("instagram", "facebook"):
        if platform in accounts and not settings.AGENTS_DRY_RUN:
            numbers[f"{platform}_followers"] = _followers(accounts[platform])

    edge = lambda d: timezone.make_aware(datetime.combine(d, time.min))  # noqa: E731 — local midnight
    posts = admart_posts(run.project_id, edge(start), edge(end + timedelta(days=1)))
    earlier = PublishJob.objects.filter(project_id=run.project_id, created_at__gte=edge(before[0]),
                                        created_at__lt=edge(start), status__in=("succeeded", "partial")).count()
    ranked = sorted([p for p in posts if p.get("views") is not None], key=lambda p: -p["views"])
    slim = lambda p: {k: p.get(k) for k in ("title", "platform", "kind", "views", "likes", "comments", "engagementRate")}  # noqa: E731
    numbers["posts"] = {"count": len({(p["title"], p["createdAt"]) for p in posts}), "count_before": earlier,
                        "top": [slim(p) for p in ranked[:3]], "bottom": [slim(p) for p in ranked[-3:][::-1]] if len(ranked) > 3 else []}
    numbers["best_days"] = best_days(posts, (numbers["youtube"] or {}).get("top") or [])
    numbers["connected"] = sorted(accounts)
    run.output["numbers"] = numbers
    base._save(run)


def mood(numbers: dict) -> str:
    yt = numbers.get("youtube")
    pct = change(yt["now"].get("views"), yt["before"].get("views")) if yt else change(
        numbers["posts"]["count"], numbers["posts"]["count_before"])
    if pct is None:
        return "same"
    return "better" if pct >= 10 else "worse" if pct <= -10 else "same"


def goal_progress(goal: dict | None, numbers: dict) -> dict | None:
    if not isinstance(goal, dict) or goal.get("metric") not in GOAL_METRICS:
        return None
    try:
        target = float(goal.get("target"))
    except (TypeError, ValueError):
        return None
    if target <= 0:
        return None
    label, read = GOAL_METRICS[goal["metric"]]
    value = read(numbers)
    return {"metric": goal["metric"], "label": label, "target": target, "value": value,
            "pct": None if value is None else round(100 * value / target)}


def step_analyze(run) -> None:
    if run.output.get("report"):
        return
    numbers = run.output["numbers"]
    config = base._config(run)
    per_week = config.get("posts_per_week") if config.get("posts_per_week") in range(1, 15) else 3
    count = max(1, min(8, round(per_week * numbers["period"] / 7)))
    niche = str(config.get("niche") or run.project.brand_industry or "").strip()
    platforms = [p for p in numbers["connected"] if p in ("youtube", "instagram", "facebook")] or ["youtube"]
    goal = goal_progress(config.get("goal"), numbers)
    if settings.AGENTS_DRY_RUN:
        raw, sources = {"verdict": "Dry run: views went up because the how-to posts did well.", "wins": ["How-to Shorts"],
                        "losses": ["Few posts on weekends"], "actions": ["Reply to comments in the first hour."] * 3,
                        "plan": [{"topic": f"{niche or 'Your niche'} idea {i + 1}", "hook": "You can do this in 30 seconds.",
                                  "format": "short video", "platform": platforms[0], "day": "Tuesday", "time": "18:00",
                                  "why": "Tuesdays did best."} for i in range(count)]}, []
    else:
        raw, sources = providers.text(
            REPORT_PROMPT,
            f"Niche: {niche or 'not set'}\nConnected platforms: {', '.join(platforms)}\n"
            f"Posts to plan for the next {numbers['period']} days: {count}\n"
            f"Goal: {json.dumps(goal) if goal else 'none'}\nNumbers:\n{json.dumps(numbers, default=str)[:9000]}",
            search=bool(niche),
            model=base._model(run, "text"),
        )
    plan = []
    for item in (raw.get("plan") or [])[:count]:
        if isinstance(item, dict) and str(item.get("topic") or "").strip():
            hook = " ".join(str(item.get("hook") or "").split())[:240]
            plan.append({**{k: str(item.get(k) or "").strip()[:120] for k in ("topic", "format", "platform", "day", "time")},
                         "why": plain(item.get("why"), 240), **base.scored_hook(hook)})
    as_list = lambda key: [plain(x, 300) for x in (raw.get(key) or []) if plain(x, 300)][:3]  # noqa: E731
    run.output["report"] = {"verdict": plain(raw.get("verdict"), 800), "mood": mood(numbers),
                            "wins": as_list("wins"), "losses": as_list("losses"), "actions": as_list("actions"),
                            "plan": plan, "goal": goal, "sources": sources[:5]}
    run.output["title"] = f"{numbers['period']}-day report · {date.fromisoformat(numbers['end']):%d %b}"
    base._save(run)


LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
CITATION = re.compile(r"\s*\[[^\]]*\.[a-z]{2,}[^\]]*\]", re.I)


def plain(value, limit: int) -> str:
    """Model text without stray citations like "[example.com]"; markdown links keep only their text."""
    return CITATION.sub("", LINK.sub(r"\1", str(value or ""))).strip()[:limit]


def recipients(run) -> list[str]:
    emails = [run.user.email, *(base._config(run).get("emails") or [])]
    valid = []
    for email in emails:
        email = str(email or "").strip().lower()
        try:
            validate_email(email)
        except ValidationError:
            continue
        if email not in valid:
            valid.append(email)
    return valid[: MAX_EMAILS + 1]  # the owner plus up to 5 more


def report_email(run) -> tuple[str, str, str]:
    """Subject, plain text and HTML of the report email."""
    out, numbers = run.output["report"], run.output["numbers"]
    link = f"{settings.FRONTEND_URL.rstrip('/')}/agents/{run.deployment_id}?run={run.id}"
    yt = numbers.get("youtube")
    figures = []
    if yt:
        for label, now, before in (("Views", yt["now"].get("views"), yt["before"].get("views")),
                                   ("Watch hours", _hours(yt["now"]), _hours(yt["before"])),
                                   ("New subscribers", _net_subs(yt["now"]), _net_subs(yt["before"])),
                                   ("Revenue", yt.get("revenue_now"), yt.get("revenue_before"))):
            if now is not None:
                pct = change(now, before)
                shown = f"${now:,.2f}" if label == "Revenue" else f"{now:,}"
                figures.append((label, shown, "" if pct is None else f"{pct:+d}%"))
    if numbers["posts"]["count"] or numbers["posts"]["count_before"]:
        figures.append(("Posts", str(numbers["posts"]["count"]), f"was {numbers['posts']['count_before']}"))
    mood_word = {"better": "Better than last period", "worse": "Down from last period", "same": "About the same as last period"}[out["mood"]]
    subject = f"Your {numbers['period']}-day report: {mood_word.lower()}"
    text = "\n".join([out["verdict"], "", *[f"{a}: {b} {c}" for a, b, c in figures], "", "Next period:",
                      *[f"- {p['day']} {p['time']} · {p['topic']}" for p in out["plan"]], "", "Actions:",
                      *[f"- {a}" for a in out["actions"]], "", f"Full report: {link}"])
    li = lambda items: "".join(f"<li style='margin:4px 0'>{escape(i)}</li>" for i in items)  # noqa: E731
    rows = "".join(f"<tr><td style='padding:6px 12px 6px 0;color:#555'>{escape(a)}</td><td style='padding:6px 12px 6px 0;"
                   f"font-weight:700'>{escape(b)}</td><td style='color:#555'>{escape(c)}</td></tr>" for a, b, c in figures)
    plan = "".join(f"<li style='margin:8px 0'><b>{escape(p['day'])} {escape(p['time'])} · {escape(PLATFORM_LABELS.get(p['platform'], p['platform']))}</b><br>"
                   f"{escape(p['topic'])}<br><span style='color:#555'>“{escape(p['hook'])}”</span></li>" for p in out["plan"])
    html = f"""<!doctype html><html><head><meta charset="utf-8"></head><body>
<div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;color:#111">
<h2 style="margin:0 0 4px">{escape(mood_word)}</h2>
<p style="color:#555;margin:0 0 16px">{escape(numbers['start'])} to {escape(numbers['end'])}</p>
<p style="font-size:16px;line-height:1.5">{escape(out['verdict'])}</p>
<table style="border-collapse:collapse;margin:12px 0">{rows}</table>
{f"<h3>What worked</h3><ul>{li(out['wins'])}</ul>" if out['wins'] else ""}
{f"<h3>What didn't</h3><ul>{li(out['losses'])}</ul>" if out['losses'] else ""}
<h3>Your plan for the next {numbers['period']} days</h3><ul style="padding-left:18px">{plan}</ul>
<h3>3 things to do</h3><ol>{li(out['actions'])}</ol>
<p style="margin:24px 0"><a href="{escape(link)}" style="background:#3B82F6;color:#fff;padding:12px 20px;border-radius:999px;text-decoration:none;font-weight:700">Open the report and approve the plan</a></p>
<p style="color:#888;font-size:12px">You get this because you scheduled the Growth Report agent in Admart. Change or stop it on the agent's page.</p>
</div></body></html>"""
    return subject, text, html


def step_deliver(run) -> None:
    if run.output.get("sent_to") is not None:
        return
    to = recipients(run)
    subject, text, html = report_email(run)
    try:
        send_mail(subject, text, settings.DEFAULT_FROM_EMAIL, to, html_message=html)
        run.output["sent_to"] = to
    except Exception:  # noqa: BLE001 — the report is still in the app; don't fail (and refund) for email
        logger.exception("Growth report email failed")
        run.output["sent_to"] = []
        run.output["email_error"] = "The email could not be sent. The report is still here."
    base._save(run)


STEPS = {"collect": step_collect, "analyze": step_analyze, "deliver": step_deliver}
