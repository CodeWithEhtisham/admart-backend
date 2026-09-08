"""Organic publish API."""

from datetime import datetime, timezone as dt_timezone

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from content.models import LibraryAsset
from projects.analytics import build_project_analytics
from projects.calendar import build_project_calendar
from projects.media_policy import validate_organic_platforms
from projects.models import PublishJob, SocialAccount
from projects.publish import PUBLISHERS, PublishUnavailable, list_facebook_pages, list_youtube_playlists
from projects.serializers import PublishJobSerializer
from projects.views import ProjectScopedSocialMixin
from projects.youtube_suggest import (
    YoutubeSuggestConfigError,
    YoutubeSuggestProviderError,
    suggest_youtube_copy,
)


def _youtube_publish_kwargs(data, title: str, thumbnail_fallback: str = "") -> dict:
    raw = data.get("youtube") or {}
    if not isinstance(raw, dict):
        raw = {}
    tags = raw.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    privacy = (raw.get("privacyStatus") or raw.get("privacy") or "public").strip()
    if privacy not in ("public", "unlisted", "private"):
        privacy = "public"
    made = raw.get("madeForKids")
    if isinstance(made, str):
        made_for_kids = made.strip().lower() in ("yes", "true", "1", "kids")
    else:
        made_for_kids = bool(made)
    publish_at = (raw.get("publishAt") or "").strip()
    if publish_at and len(publish_at) == 16:
        publish_at = publish_at + ":00Z"
    recording_date = (raw.get("recordingDate") or "").strip()
    if recording_date and len(recording_date) == 10:
        recording_date = recording_date + "T00:00:00Z"
    return {
        "title": (raw.get("title") or title or "Admart video")[:100],
        "description": (raw.get("description") or "")[:5000],
        "tags": [str(t)[:100] for t in tags if str(t).strip()][:30],
        "privacy": privacy,
        "thumbnail_url": (raw.get("thumbnailUrl") or thumbnail_fallback or "").strip(),
        "category_id": str(raw.get("categoryId") or "22").strip() or "22",
        "language": (raw.get("language") or "").strip(),
        "license_type": (raw.get("license") or "youtube").strip() or "youtube",
        "embeddable": raw.get("embeddable", True) is not False,
        "public_stats": raw.get("publicStatsViewable", True) is not False,
        "made_for_kids": made_for_kids,
        "synthetic_media": raw.get("containsSyntheticMedia", True) is not False,
        "notify_subscribers": raw.get("notifySubscribers", True) is not False,
        "publish_at": publish_at,
        "recording_date": recording_date,
        "playlist_id": (raw.get("playlistId") or "").strip(),
        "paid_promotion": raw.get("paidPromotion") is True
        or (
            isinstance(raw.get("paidPromotion"), str)
            and raw.get("paidPromotion").strip().lower() in ("yes", "true", "1")
        ),
    }


def _facebook_publish_kwargs(data, title: str) -> dict:
    raw = data.get("facebook") or {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "caption": (raw.get("caption") or title or "").strip()[:5000],
        "page_id": str(raw.get("pageId") or "").strip(),
    }


def _instagram_publish_kwargs(data, title: str) -> dict:
    raw = data.get("instagram") or {}
    if not isinstance(raw, dict):
        raw = {}
    return {"caption": (raw.get("caption") or title or "").strip()[:2200]}


def _object_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _parse_scheduled_at(raw) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if len(text) == 16:
        text = text + ":00"
    parsed = parse_datetime(text)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


NATIVE_SCHEDULE = frozenset({"youtube", "facebook"})


class ProjectPublishView(ProjectScopedSocialMixin, APIView):
    """POST /api/projects/:id/publish — post a generated asset to connected accounts."""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request, project_id: str, *args, **kwargs) -> Response:
        project = self.get_project(request, project_id)
        kind = (request.data.get("kind") or "").strip()
        platforms = request.data.get("platforms") or []
        if isinstance(platforms, str):
            platforms = [p.strip() for p in platforms.split(",") if p.strip()]
        title = (request.data.get("title") or "").strip()
        source_url = (request.data.get("sourceUrl") or "").strip()
        asset_id = request.data.get("assetId") or None

        asset = None
        if asset_id:
            asset = LibraryAsset.objects.filter(id=asset_id, project=project).first()
            if asset is None:
                return Response({"message": "Asset not found."}, status=status.HTTP_404_NOT_FOUND)
            kind = kind or asset.media_type
            source_url = source_url or asset.source_url
            title = title or asset.title

        youtube_kwargs = _youtube_publish_kwargs(
            request.data, title, (asset.thumbnail_url if asset else "") or ""
        )
        facebook_kwargs = _facebook_publish_kwargs(request.data, title)
        instagram_kwargs = _instagram_publish_kwargs(request.data, title)
        error = validate_organic_platforms(kind, platforms)
        if error:
            return Response({"message": error}, status=status.HTTP_400_BAD_REQUEST)
        if not source_url:
            return Response({"message": "sourceUrl or assetId is required."}, status=status.HTTP_400_BAD_REQUEST)

        action = (request.data.get("action") or "publish").strip().lower()
        if action not in ("publish", "draft", "schedule"):
            return Response({"message": "action must be publish, draft, or schedule."}, status=status.HTTP_400_BAD_REQUEST)
        scheduled_at = _parse_scheduled_at(request.data.get("scheduledAt"))
        if action == "schedule":
            if scheduled_at is None:
                return Response({"message": "Pick a date and time to schedule."}, status=status.HTTP_400_BAD_REQUEST)
            if scheduled_at <= timezone.now():
                return Response({"message": "Schedule time must be in the future."}, status=status.HTTP_400_BAD_REQUEST)
            youtube_kwargs["publish_at"] = scheduled_at.astimezone(dt_timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            facebook_kwargs["scheduled_at"] = scheduled_at

        connected = {
            a.platform: a
            for a in SocialAccount.objects.filter(project=project, platform__in=platforms, connected=True)
        }
        if action != "draft":
            missing = [p for p in platforms if p not in connected]
            if missing:
                return Response(
                    {"message": f"Not connected: {', '.join(missing)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        stored_payload = {
            "youtube": _object_dict(request.data.get("youtube")),
            "facebook": _object_dict(request.data.get("facebook")),
            "instagram": _object_dict(request.data.get("instagram")),
        }
        job = PublishJob.objects.create(
            project=project,
            user=request.user,
            library_asset=asset,
            kind=kind,
            source_url=source_url,
            title=title,
            platforms=platforms,
            payload=stored_payload,
            scheduled_at=scheduled_at if action == "schedule" else None,
            status="draft" if action == "draft" else "running",
        )
        if action == "draft":
            return Response(PublishJobSerializer(job).data, status=status.HTTP_201_CREATED)

        results = {}
        for platform in platforms:
            if action == "schedule" and platform not in NATIVE_SCHEDULE:
                results[platform] = {"status": "scheduled"}
                continue
            publisher = PUBLISHERS[platform]
            try:
                kwargs = {"kind": kind, "source_url": source_url, "title": title}
                if platform == "youtube":
                    kwargs.update(youtube_kwargs)
                elif platform == "facebook":
                    kwargs.update(facebook_kwargs)
                elif platform == "instagram":
                    kwargs.update(instagram_kwargs)
                results[platform] = publisher(connected[platform], **kwargs)
                if action == "schedule" and results[platform].get("status") == "succeeded":
                    results[platform]["status"] = "scheduled"
            except PublishUnavailable as exc:
                results[platform] = {"status": "failed", "error": str(exc)}
            except Exception as exc:  # noqa: BLE001
                results[platform] = {"status": "failed", "error": str(exc)}

        statuses = [row.get("status") for row in results.values()]
        if action == "schedule" and all(s in ("scheduled", "succeeded") for s in statuses):
            job.status = "scheduled"
        elif all(s == "succeeded" for s in statuses):
            job.status = "succeeded"
        elif any(s in ("succeeded", "scheduled") for s in statuses):
            job.status = "partial"
        else:
            job.status = "failed"
            job.error = "; ".join(
                f"{p}: {results[p].get('error')}" for p in platforms if results[p].get("error")
            )
        job.results = results
        job.save(update_fields=["status", "error", "results", "updated_at"])

        http = status.HTTP_201_CREATED if job.status != "failed" else status.HTTP_400_BAD_REQUEST
        return Response(PublishJobSerializer(job).data, status=http)


class ProjectYoutubePlaylistsView(ProjectScopedSocialMixin, APIView):
    """GET /api/projects/:id/social/youtube/playlists"""

    def get(self, request: Request, project_id: str, *args, **kwargs) -> Response:
        project = self.get_project(request, project_id)
        account = SocialAccount.objects.filter(project=project, platform="youtube", connected=True).first()
        if account is None:
            return Response({"message": "Connect YouTube first."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            playlists = list_youtube_playlists(account)
        except Exception as exc:  # noqa: BLE001
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(playlists)


class ProjectFacebookPagesView(ProjectScopedSocialMixin, APIView):
    """GET /api/projects/:id/social/facebook/pages"""

    def get(self, request: Request, project_id: str, *args, **kwargs) -> Response:
        project = self.get_project(request, project_id)
        account = SocialAccount.objects.filter(project=project, platform="facebook", connected=True).first()
        if account is None:
            return Response({"message": "Connect Facebook first."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            pages = list_facebook_pages(account)
        except PublishUnavailable as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:  # noqa: BLE001
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(pages)


class ProjectYoutubeSuggestView(ProjectScopedSocialMixin, APIView):
    """POST /api/projects/:id/publish/youtube/suggest"""

    def post(self, request: Request, project_id: str, *args, **kwargs) -> Response:
        project = self.get_project(request, project_id)
        prompt = (request.data.get("prompt") or "").strip()
        title = (request.data.get("title") or "").strip()
        try:
            payload = suggest_youtube_copy(
                prompt=prompt,
                title=title,
                brand_name=project.brand_name,
                industry=project.brand_industry,
            )
        except ValueError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except YoutubeSuggestConfigError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except YoutubeSuggestProviderError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
        return Response(payload)


class ProjectAnalyticsView(ProjectScopedSocialMixin, APIView):
    """GET /api/projects/:id/analytics — publish activity for the project."""

    def get(self, request: Request, project_id: str, *args, **kwargs) -> Response:
        project = self.get_project(request, project_id)
        payload = build_project_analytics(
            project,
            range_key=(request.query_params.get("range") or "30d").strip(),
            platform=(request.query_params.get("platform") or "all").strip(),
        )
        return Response(payload)


class ProjectCalendarView(ProjectScopedSocialMixin, APIView):
    """GET /api/projects/:id/calendar — scheduled posts and generations for a month."""

    def get(self, request: Request, project_id: str, *args, **kwargs) -> Response:
        project = self.get_project(request, project_id)
        now = timezone.now()
        try:
            year = int(request.query_params.get("year") or now.year)
            month = int(request.query_params.get("month") or now.month)
        except (TypeError, ValueError):
            return Response({"message": "year and month must be numbers."}, status=status.HTTP_400_BAD_REQUEST)
        if year < 2000 or year > 2100 or month < 1 or month > 12:
            return Response({"message": "Invalid year or month."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(build_project_calendar(project, year=year, month=month))
