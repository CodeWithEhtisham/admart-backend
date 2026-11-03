"""Posting caps that keep users' social accounts clear of spam flags.

Platform maximums (Instagram 50 posts / 24h, Facebook Reels 30 / 24h) are far above
what looks human, so per-account caps sit well below them. YouTube's limit is different:
100 videos.insert calls per day for Admart's whole Google Cloud project, shared by
every user, until Google grants more quota after an audit.
"""

import random
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from projects.models import PublishEvent, SocialAccount
from projects.publish import PLATFORM_LABELS, PUBLISHERS

DAY = timedelta(hours=24)
DAILY_CAP = {"youtube": 3, "instagram": 10, "facebook": 10}  # organic posts per account in 24 hours
FACEBOOK_VIDEO_CAP = 5
MIN_GAP = timedelta(hours=1)
DUPLICATE_WINDOW = timedelta(days=3)
PAUSE_AFTER_BLOCK = DAY
YOUTUBE_PROJECT_DAILY_UPLOADS = 100
SCHEDULE_JITTER_SECONDS = 300
BLOCK_SIGNS = (
    "quota",
    "rate limit",
    "ratelimit",
    "uploadlimitexceeded",
    "too many",
    "spam",
    "limit reached",
    "limit exceeded",
)


class PublishLimited(RuntimeError):
    """A post Admart refuses to send, to protect the user's account."""


def channel_key(account) -> str:
    return f"{account.platform}:{account.external_id or account.id}"


def jitter(at):
    """Nudge a scheduled time by a few minutes so posts never land on the exact same second."""
    return at + timedelta(seconds=random.randint(0, SCHEDULE_JITTER_SECONDS))


def _check(account, *, kind: str, source_url: str, post_at, now, organic: bool) -> None:
    platform = account.platform
    name = PLATFORM_LABELS.get(platform, platform)
    if platform == "youtube" and (
        PublishEvent.objects.filter(platform="youtube", created_at__gt=now - DAY).count()
        >= YOUTUBE_PROJECT_DAILY_UPLOADS
    ):
        raise PublishLimited("Admart has used today's YouTube upload allowance. Try again tomorrow.")
    if not organic:
        return
    events = PublishEvent.objects.filter(channel=channel_key(account), organic=True).exclude(status="failed")
    if events.filter(status="blocked", created_at__gt=now - PAUSE_AFTER_BLOCK).exists():
        raise PublishLimited(
            f"{name} pushed back on a recent post, so posting to it is paused for 24 hours to protect the account."
        )
    if source_url and events.filter(
        source_url=source_url, post_at__gt=post_at - DUPLICATE_WINDOW, post_at__lt=post_at + DUPLICATE_WINDOW
    ).exists():
        raise PublishLimited(f"This was already posted to {name} in the last 3 days. Reposting it looks like spam.")
    # Counting 24h on both sides of post_at keeps every rolling day under the cap, even with scheduled posts.
    window = events.filter(post_at__gt=post_at - DAY, post_at__lt=post_at + DAY)
    cap = DAILY_CAP[platform]
    if window.count() >= cap:
        raise PublishLimited(f"{name} allows {cap} posts per account in 24 hours on Admart. Schedule this one later.")
    if platform == "facebook" and kind == "video" and window.filter(kind="video").count() >= FACEBOOK_VIDEO_CAP:
        raise PublishLimited(
            f"Facebook allows {FACEBOOK_VIDEO_CAP} videos per Page in 24 hours on Admart. Schedule this one later."
        )
    if events.filter(post_at__gt=post_at - MIN_GAP, post_at__lt=post_at + MIN_GAP).exists():
        raise PublishLimited(f"Leave at least an hour between {name} posts. Schedule this one later.")


def publish(account, *, kind: str, source_url: str, post_at=None, organic: bool = True, **kwargs) -> dict:
    """Send one post through PUBLISHERS once it passes the caps. Raises PublishLimited when it doesn't.

    organic=False (an ad creative hosted on the channel) only counts against the shared YouTube allowance.
    """
    platform = account.platform
    if platform not in DAILY_CAP:
        return PUBLISHERS[platform](account, kind=kind, source_url=source_url, **kwargs)
    now = timezone.now()
    post_at = post_at or now
    with transaction.atomic():
        SocialAccount.objects.select_for_update().filter(pk=account.pk).first()  # one post per account at a time
        _check(account, kind=kind, source_url=source_url, post_at=post_at, now=now, organic=organic)
        event = PublishEvent.objects.create(
            account=account,
            channel=channel_key(account),
            platform=platform,
            kind=kind,
            source_url=source_url,
            organic=organic,
            post_at=post_at,
        )
    try:
        result = PUBLISHERS[platform](account, kind=kind, source_url=source_url, **kwargs)
    except Exception as exc:
        event.status = "blocked" if any(sign in str(exc).lower() for sign in BLOCK_SIGNS) else "failed"
        event.save(update_fields=["status"])
        raise
    event.status = "succeeded" if result.get("status") == "succeeded" else "failed"
    event.save(update_fields=["status"])
    return result
