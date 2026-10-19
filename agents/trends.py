"""Trend Finder signals: what people are reading, discussing and watching right now, from Google News,
Reddit and YouTube. Every source fails softly (empty list): one source being down never fails a run."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as dt_timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import requests

logger = logging.getLogger(__name__)

TIMEOUT = 8
MAX_TOPICS = 3
MAX_SIGNALS = 80
PER_SOURCE = {"news": 10, "reddit": 4, "youtube": 5}  # per topic; per subreddit for Reddit
REDDIT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}
ATOM = "{http://www.w3.org/2005/Atom}"

# news: Google News topic section (None = search `query` instead); youtube: videoCategoryId (None = skip).
TREND_TOPICS = {
    "ai": {"label": "AI", "news": None, "query": "artificial intelligence",
           "subreddits": ("artificial", "OpenAI", "singularity"), "youtube": None},
    "technology": {"label": "Technology", "news": "TECHNOLOGY", "query": "technology",
                   "subreddits": ("technology", "gadgets", "Futurology"), "youtube": "28"},
    "news": {"label": "News", "news": "WORLD", "query": "world news",
             "subreddits": ("worldnews", "news", "nottheonion"), "youtube": "25"},
    "business": {"label": "Business & Finance", "news": "BUSINESS", "query": "business",
                 "subreddits": ("business", "finance", "investing"), "youtube": None},
    "sports": {"label": "Sports", "news": "SPORTS", "query": "sports",
               "subreddits": ("sports", "nba", "soccer"), "youtube": "17"},
    "entertainment": {"label": "Entertainment", "news": "ENTERTAINMENT", "query": "entertainment",
                      "subreddits": ("movies", "television", "popculturechat"), "youtube": "24"},
    "gaming": {"label": "Gaming", "news": None, "query": "video games",
               "subreddits": ("gaming", "Games", "pcgaming"), "youtube": "20"},
    "science": {"label": "Science", "news": "SCIENCE", "query": "science",
                "subreddits": ("science", "space", "EverythingScience"), "youtube": "28"},
    "health": {"label": "Health & Fitness", "news": "HEALTH", "query": "health and fitness",
               "subreddits": ("health", "Fitness", "nutrition"), "youtube": None},
    "lifestyle": {"label": "Lifestyle", "news": None, "query": "lifestyle trends",
                  "subreddits": ("lifehacks", "LifeProTips", "selfimprovement"), "youtube": "26"},
    "food": {"label": "Food", "news": None, "query": "food",
             "subreddits": ("food", "Cooking", "recipes"), "youtube": None},
    "travel": {"label": "Travel", "news": None, "query": "travel",
               "subreddits": ("travel", "solotravel", "backpacking"), "youtube": "19"},
    "education": {"label": "Education", "news": None, "query": "education",
                  "subreddits": ("education", "college", "GetStudying"), "youtube": "27"},
}

REGIONS = {
    "world": {"label": "Worldwide", "hl": "en-US", "gl": "US", "ceid": "US:en", "youtube": "US"},
    "us": {"label": "United States", "hl": "en-US", "gl": "US", "ceid": "US:en", "youtube": "US"},
    "gb": {"label": "United Kingdom", "hl": "en-GB", "gl": "GB", "ceid": "GB:en", "youtube": "GB"},
    "pk": {"label": "Pakistan", "hl": "en-PK", "gl": "PK", "ceid": "PK:en", "youtube": "PK"},
    "in": {"label": "India", "hl": "en-IN", "gl": "IN", "ceid": "IN:en", "youtube": "IN"},
    "ae": {"label": "UAE", "hl": "en-AE", "gl": "AE", "ceid": "AE:en", "youtube": "AE"},
    "ca": {"label": "Canada", "hl": "en-CA", "gl": "CA", "ceid": "CA:en", "youtube": "CA"},
    "au": {"label": "Australia", "hl": "en-AU", "gl": "AU", "ceid": "AU:en", "youtube": "AU"},
}

WINDOWS = {"day": "Today", "week": "This week", "month": "This month"}
WINDOW_DAYS = {"day": 1, "week": 7, "month": 30}


def _signal(title, url, source, topic, published=None, score=None) -> dict:
    return {"title": " ".join(str(title or "").split())[:200], "url": url, "source": source, "topic": topic,
            "published": published, "score": score}


def google_news(topic: str, spec: dict | None, region: dict, window: str, custom: str = "") -> list[dict]:
    """Headlines from a Google News section (or search, for a custom topic or one without a section)."""
    days = WINDOW_DAYS[window]
    params = f"hl={region['hl']}&gl={region['gl']}&ceid={quote_plus(region['ceid'])}"
    if spec and spec["news"]:
        url = f"https://news.google.com/rss/headlines/section/topic/{spec['news']}?{params}"
    else:
        query = quote_plus(f"{custom or spec['query']} when:{days}d")
        url = f"https://news.google.com/rss/search?q={query}&{params}"
    try:
        response = requests.get(url, timeout=TIMEOUT)
        response.raise_for_status()
        items = ET.fromstring(response.content).iter("item")
        cutoff = datetime.now(dt_timezone.utc) - timedelta(days=days)
        found = []
        for item in items:
            title, link = (item.findtext("title") or "").strip(), (item.findtext("link") or "").strip()
            if not title or not link:
                continue
            published = None
            if item.findtext("pubDate"):
                try:
                    when = parsedate_to_datetime(item.findtext("pubDate"))
                except (TypeError, ValueError):
                    when = None
                if when:
                    if when.tzinfo is None:
                        when = when.replace(tzinfo=dt_timezone.utc)
                    if when < cutoff:
                        continue
                    published = when.isoformat()
            found.append(_signal(title, link, "Google News", topic, published))
            if len(found) == PER_SOURCE["news"]:
                break
        return found
    except Exception as exc:  # network, bad status or bad XML: skip this source
        logger.warning("Google News unavailable for %s: %s", topic, exc)
        return []


def reddit(subreddits: dict[str, str], window: str) -> list[dict]:
    """Top posts in the window for {subreddit: topic id}, at most PER_SOURCE["reddit"] per subreddit.

    One combined Atom feed (r/a+b+c): Reddit blocks top.json from servers and rate-limits each feed request.
    """
    if not subreddits:
        return []
    topic_of = {sub.lower(): topic for sub, topic in subreddits.items()}
    try:
        response = requests.get(f"https://www.reddit.com/r/{'+'.join(subreddits)}/top/.rss",
                                params={"t": window, "limit": 100}, headers=REDDIT_HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        found, taken = [], {}
        for entry in ET.fromstring(response.content).iter(f"{ATOM}entry"):
            category = entry.find(f"{ATOM}category")
            sub = (category.get("term") if category is not None else "").lower()
            title = " ".join((entry.findtext(f"{ATOM}title") or "").split())
            link = entry.find(f"{ATOM}link")
            url = link.get("href") if link is not None else ""
            if sub not in topic_of or not title or not url or taken.get(sub, 0) >= PER_SOURCE["reddit"]:
                continue
            taken[sub] = taken.get(sub, 0) + 1
            found.append(_signal(title, url, "Reddit", topic_of[sub], entry.findtext(f"{ATOM}published")))
        return found
    except Exception as exc:
        logger.warning("Reddit unavailable for r/%s: %s", "+".join(subreddits), exc)
        return []


def youtube(topic: str, category: str, region: dict, token: str) -> list[dict]:
    """Most popular videos in a category for the region."""
    try:
        response = requests.get(
            "https://www.googleapis.com/youtube/v3/videos",
            params={"part": "snippet,statistics", "chart": "mostPopular", "regionCode": region["youtube"],
                    "videoCategoryId": category, "maxResults": 10},
            headers={"Authorization": f"Bearer {token}"}, timeout=TIMEOUT)
        response.raise_for_status()
        found = []
        for video in response.json().get("items") or []:
            snippet = video.get("snippet") or {}
            if not snippet.get("title") or not video.get("id"):
                continue
            views = (video.get("statistics") or {}).get("viewCount")
            found.append(_signal(snippet["title"], f"https://www.youtube.com/watch?v={video['id']}", "YouTube", topic,
                                 snippet.get("publishedAt"), int(views) if str(views).isdigit() else None))
            if len(found) == PER_SOURCE["youtube"]:
                break
        return found
    except Exception as exc:
        logger.warning("YouTube trends unavailable for %s: %s", topic, exc)
        return []


def youtube_token(project) -> str:
    """A valid access token of the project's connected YouTube account, or "" (YouTube is then skipped)."""
    from projects.models import SocialAccount
    from projects.oauth import ensure_fresh_access_token

    account = SocialAccount.objects.filter(project=project, platform="youtube", connected=True).first()
    if account is None:
        return ""
    try:
        return ensure_fresh_access_token(account) or ""
    except Exception as exc:
        logger.warning("YouTube token unavailable: %s", exc)
        return ""


def collect_signals(topics: list[str], custom: str, region: str, window: str, project) -> tuple[list[dict], dict]:
    """Signals for the picked topic ids and custom topic, de-duplicated by title, plus the count per source."""
    where = REGIONS[region]
    token = youtube_token(project) if any(TREND_TOPICS[t]["youtube"] for t in topics) else ""
    jobs = []
    for topic in topics:
        spec = TREND_TOPICS[topic]
        jobs.append((google_news, (topic, spec, where, window)))
        if token and spec["youtube"]:
            jobs.append((youtube, (topic, spec["youtube"], where, token)))
    if custom:
        jobs.append((google_news, ("custom", None, where, window, custom)))
    jobs.append((reddit, ({sub: topic for topic in topics for sub in TREND_TOPICS[topic]["subreddits"]}, window)))
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda job: job[0](*job[1]), jobs))
    signals, seen = [], set()
    for found in results:
        for signal in found:
            key = re.sub(r"\W+", " ", signal["title"].lower()).strip()
            if key not in seen:
                seen.add(key)
                signals.append(signal)
    signals = signals[:MAX_SIGNALS]
    counts = {name: sum(s["source"] == name for s in signals) for name in ("Google News", "Reddit", "YouTube")}
    return signals, counts
