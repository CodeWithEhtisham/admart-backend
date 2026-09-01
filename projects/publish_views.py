"""Organic publish API."""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from content.models import LibraryAsset
from projects.media_policy import validate_organic_platforms
from projects.models import PublishJob, SocialAccount
from projects.publish import PUBLISHERS, PublishUnavailable
from projects.serializers import PublishJobSerializer
from projects.views import ProjectScopedSocialMixin


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

        error = validate_organic_platforms(kind, platforms)
        if error:
            return Response({"message": error}, status=status.HTTP_400_BAD_REQUEST)
        if not source_url:
            return Response({"message": "sourceUrl or assetId is required."}, status=status.HTTP_400_BAD_REQUEST)

        connected = {
            a.platform: a
            for a in SocialAccount.objects.filter(project=project, platform__in=platforms, connected=True)
        }
        missing = [p for p in platforms if p not in connected]
        if missing:
            return Response(
                {"message": f"Not connected: {', '.join(missing)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        job = PublishJob.objects.create(
            project=project,
            user=request.user,
            library_asset=asset,
            kind=kind,
            source_url=source_url,
            title=title,
            platforms=platforms,
            status="running",
        )
        results = {}
        for platform in platforms:
            publisher = PUBLISHERS[platform]
            try:
                results[platform] = publisher(
                    connected[platform], kind=kind, source_url=source_url, title=title
                )
            except PublishUnavailable as exc:
                results[platform] = {"status": "failed", "error": str(exc)}
            except Exception as exc:  # noqa: BLE001
                results[platform] = {"status": "failed", "error": str(exc)}

        statuses = [row.get("status") for row in results.values()]
        if all(s == "succeeded" for s in statuses):
            job.status = "succeeded"
        elif any(s == "succeeded" for s in statuses):
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
