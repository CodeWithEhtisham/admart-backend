import logging

from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from content import fal_client
from content.catalog import MODEL_CATALOG
from content.credits import InsufficientCredits, cost_for, refund_credits, reserve_credits
from content.jobs import refresh_job
from content.library import mark_library_generating, sync_library_from_image_job
from content.mapping import build_fal_input
from content.models import ImageJob, ImageUpload, LibraryAsset
from content.serializers import (
    ImageJobCreateSerializer,
    ImageJobSerializer,
    LibraryAssetSerializer,
)
from content.storage_utils import absolute_media_url
from content.url_resolve import resolve_urls_for_fal
from projects.models import Project

logger = logging.getLogger(__name__)

ALLOWED_UPLOAD_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB


def _owned_project(user, project_id) -> Project:
    return get_object_or_404(Project, id=project_id, owner=user)


class ImageJobListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, project_id):
        project = _owned_project(request.user, project_id)
        limit = min(int(request.query_params.get("limit", 20)), 50)
        qs = ImageJob.objects.filter(project=project)[:limit]
        return Response(
            {
                "items": ImageJobSerializer(qs, many=True).data,
                "nextCursor": None,
            }
        )

    def post(self, request, project_id):
        project = _owned_project(request.user, project_id)
        ser = ImageJobCreateSerializer(data=request.data)
        if not ser.is_valid():
            err = ser.errors
            # Normalize to {message, field} when possible
            if isinstance(err, dict):
                for key, val in err.items():
                    if key in ("field", "message"):
                        continue
                    msg = val[0] if isinstance(val, list) else val
                    if isinstance(msg, dict) and "message" in msg:
                        return Response(msg, status=status.HTTP_400_BAD_REQUEST)
                    return Response(
                        {"message": str(msg), "field": key},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            return Response({"message": "Invalid request"}, status=status.HTTP_400_BAD_REQUEST)

        data = ser.validated_data
        capability = data["capability"]
        model = data["model"]
        amount = cost_for(capability, data.get("numImages") or 1)

        try:
            reserve_credits(request.user, amount)
        except InsufficientCredits:
            request.user.refresh_from_db()
            return Response(
                {
                    "message": "Insufficient credits",
                    "code": "INSUFFICIENT_CREDITS",
                    # Gate on remaining — not creditsTotal (plan allotment).
                    "creditsRemaining": request.user.credits_remaining,
                    "creditsTotal": request.user.credits_total,
                },
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        # Keep original FE URLs in the stored request; rewrite for fal only.
        fal_data = dict(data)
        try:
            if fal_data.get("imageUrls"):
                fal_data["imageUrls"] = resolve_urls_for_fal(fal_data["imageUrls"])
        except ValueError as exc:
            return Response(
                {"message": str(exc), "field": "imageUrls"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fal_input = build_fal_input(capability, model, fal_data)
        job = ImageJob.objects.create(
            project=project,
            user=request.user,
            capability=capability,
            model=model,
            status="queued",
            prompt=data.get("prompt"),
            request={k: v for k, v in data.items() if k != "prompt" or v},
            credits_reserved=amount,
        )

        try:
            submission = fal_client.submit(model, fal_input)
        except fal_client.FalError as exc:
            refund_credits(request.user, amount)
            job.status = "failed"
            job.error = str(exc) if settings.DEBUG else "Provider error"
            job.credits_reserved = 0
            job.save(update_fields=["status", "error", "credits_reserved", "updated_at"])
            code = status.HTTP_503_SERVICE_UNAVAILABLE if exc.status_code == 503 else status.HTTP_502_BAD_GATEWAY
            return Response({"message": job.error}, status=code)

        job.fal_request_id = submission.request_id
        job.fal_status_url = submission.status_url
        job.fal_response_url = submission.response_url
        job.save(
            update_fields=[
                "fal_request_id",
                "fal_status_url",
                "fal_response_url",
                "updated_at",
            ]
        )
        mark_library_generating(job)
        request.user.refresh_from_db()
        payload = ImageJobSerializer(job).data
        payload["creditsRemaining"] = request.user.credits_remaining
        return Response(payload, status=status.HTTP_202_ACCEPTED)


class ImageJobDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, project_id, job_id):
        project = _owned_project(request.user, project_id)
        job = get_object_or_404(ImageJob, id=job_id, project=project)
        job = refresh_job(job, request=request)
        # Re-absolute any relative media URLs for the client
        job = _absolutize_job_urls(job, request)
        return Response(ImageJobSerializer(job).data)


class ImageJobCancelView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, project_id, job_id):
        project = _owned_project(request.user, project_id)
        job = get_object_or_404(ImageJob, id=job_id, project=project)
        if job.status in ("succeeded", "failed"):
            return Response(ImageJobSerializer(job).data)
        job.status = "failed"
        job.error = "Cancelled"
        job.save(update_fields=["status", "error", "updated_at"])
        if job.credits_reserved and job.credits_used is None:
            refund_credits(request.user, int(job.credits_reserved))
            job.credits_reserved = 0
            job.save(update_fields=["credits_reserved", "updated_at"])
        sync_library_from_image_job(job)
        return Response(ImageJobSerializer(job).data)


class ImageUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, project_id):
        project = _owned_project(request.user, project_id)
        upload = request.FILES.get("file")
        if not upload:
            return Response(
                {"message": "file is required", "field": "file"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        content_type = upload.content_type or ""
        if content_type not in ALLOWED_UPLOAD_TYPES:
            return Response(
                {"message": "Only jpeg, png, and webp are allowed", "field": "file"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if upload.size > MAX_UPLOAD_BYTES:
            return Response({"message": "File too large"}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        record = ImageUpload(
            project=project,
            user=request.user,
            content_type=content_type,
            byte_size=upload.size,
        )
        record.file.save(upload.name, upload, save=True)
        url = absolute_media_url(record.file.name, request=request)
        return Response(
            {
                "url": url,
                "contentType": content_type,
                "byteSize": upload.size,
            },
            status=status.HTTP_201_CREATED,
        )


class ImageModelCatalogView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, project_id=None):
        if project_id is not None:
            _owned_project(request.user, project_id)
        return Response(MODEL_CATALOG)


class LibraryListView(APIView):
    """GET /api/projects/:id/library — images + videos, newest first."""

    permission_classes = [IsAuthenticated]

    def get(self, request, project_id):
        project = _owned_project(request.user, project_id)
        media_type = (request.query_params.get("mediaType") or "all").lower()
        try:
            limit = min(int(request.query_params.get("limit", 50)), 100)
        except (TypeError, ValueError):
            limit = 50
        try:
            offset = max(int(request.query_params.get("cursor") or 0), 0)
        except (TypeError, ValueError):
            offset = 0

        qs = LibraryAsset.objects.filter(project=project, deleted_at__isnull=True)
        if media_type in ("image", "video"):
            qs = qs.filter(media_type=media_type)

        page = list(qs[offset : offset + limit + 1])
        has_more = len(page) > limit
        items = page[:limit]
        next_cursor = str(offset + limit) if has_more else None

        # Absolutize relative media URLs for the client
        data = LibraryAssetSerializer(items, many=True).data
        for item in data:
            for key in ("sourceUrl", "thumbnailUrl"):
                url = item.get(key) or ""
                if url.startswith("/"):
                    rel = url
                    if settings.MEDIA_URL and rel.startswith(settings.MEDIA_URL):
                        rel = rel[len(settings.MEDIA_URL) :]
                    item[key] = absolute_media_url(rel.lstrip("/"), request=request)

        return Response({"items": data, "nextCursor": next_cursor})


class LibraryDetailView(APIView):
    """DELETE /api/projects/:id/library/:assetId — soft delete."""

    permission_classes = [IsAuthenticated]

    def delete(self, request, project_id, asset_id):
        project = _owned_project(request.user, project_id)
        asset = get_object_or_404(
            LibraryAsset, id=asset_id, project=project, deleted_at__isnull=True
        )
        asset.deleted_at = timezone.now()
        asset.save(update_fields=["deleted_at", "updated_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)


def _absolutize_job_urls(job: ImageJob, request) -> ImageJob:
    changed = False
    images = []
    for img in job.images or []:
        url = img.get("url") or ""
        if url.startswith("/"):
            rel = url
            if settings.MEDIA_URL and rel.startswith(settings.MEDIA_URL):
                rel = rel[len(settings.MEDIA_URL) :]
            img = {**img, "url": absolute_media_url(rel.lstrip("/"), request=request)}
            changed = True
        images.append(img)
    if changed:
        job.images = images
    return job
