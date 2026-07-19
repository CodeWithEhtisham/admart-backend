"""Video generation API views (mirror of image jobs)."""

from __future__ import annotations

import logging

from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from content import fal_client
from content.credits import InsufficientCredits, cost_for, refund_credits, reserve_credits
from content.library import mark_library_generating_video, sync_library_from_video_job
from content.models import VideoJob
from content.serializers import VideoJobCreateSerializer, VideoJobSerializer
from content.storage_utils import absolute_media_url
from content.url_resolve import resolve_urls_for_fal
from content.video_catalog import VIDEO_MODEL_CATALOG
from content.video_jobs import refresh_video_job
from content.video_mapping import build_video_fal_input
from content.views import ImageUploadView, _owned_project

logger = logging.getLogger(__name__)


class VideoJobListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, project_id):
        project = _owned_project(request.user, project_id)
        limit = min(int(request.query_params.get("limit", 20)), 50)
        qs = VideoJob.objects.filter(project=project)[:limit]
        return Response(
            {
                "items": VideoJobSerializer(qs, many=True).data,
                "nextCursor": None,
            }
        )

    def post(self, request, project_id):
        project = _owned_project(request.user, project_id)
        ser = VideoJobCreateSerializer(data=request.data)
        if not ser.is_valid():
            err = ser.errors
            if isinstance(err, dict):
                for key, val in err.items():
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
        amount = cost_for(capability)

        try:
            reserve_credits(request.user, amount)
        except InsufficientCredits:
            request.user.refresh_from_db()
            return Response(
                {
                    "message": "Insufficient credits",
                    "code": "INSUFFICIENT_CREDITS",
                    "creditsRemaining": request.user.credits_remaining,
                    "creditsTotal": request.user.credits_total,
                },
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        fal_data = dict(data)
        try:
            if fal_data.get("startImageUrl"):
                fal_data["startImageUrl"] = resolve_urls_for_fal([fal_data["startImageUrl"]])[0]
            if fal_data.get("endImageUrl"):
                fal_data["endImageUrl"] = resolve_urls_for_fal([fal_data["endImageUrl"]])[0]
            if fal_data.get("imageUrls"):
                fal_data["imageUrls"] = resolve_urls_for_fal(fal_data["imageUrls"])
        except ValueError as exc:
            refund_credits(request.user, amount)
            return Response(
                {"message": str(exc), "field": "startImageUrl"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        fal_input = build_video_fal_input(capability, model, fal_data)
        job = VideoJob.objects.create(
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
            code = (
                status.HTTP_503_SERVICE_UNAVAILABLE
                if exc.status_code == 503
                else status.HTTP_502_BAD_GATEWAY
            )
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
        mark_library_generating_video(job)
        request.user.refresh_from_db()
        payload = VideoJobSerializer(job).data
        payload["creditsRemaining"] = request.user.credits_remaining
        return Response(payload, status=status.HTTP_202_ACCEPTED)


class VideoJobDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, project_id, job_id):
        project = _owned_project(request.user, project_id)
        job = get_object_or_404(VideoJob, id=job_id, project=project)
        job = refresh_video_job(job, request=request)
        job = _absolutize_video_job_urls(job, request)
        return Response(VideoJobSerializer(job).data)


class VideoJobCancelView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, project_id, job_id):
        project = _owned_project(request.user, project_id)
        job = get_object_or_404(VideoJob, id=job_id, project=project)
        if job.status in ("succeeded", "failed"):
            return Response(VideoJobSerializer(job).data)
        job.status = "failed"
        job.error = "Cancelled"
        job.save(update_fields=["status", "error", "updated_at"])
        if job.credits_reserved and job.credits_used is None:
            refund_credits(request.user, int(job.credits_reserved))
            job.credits_reserved = 0
            job.save(update_fields=["credits_reserved", "updated_at"])
        sync_library_from_video_job(job)
        return Response(VideoJobSerializer(job).data)


class VideoModelCatalogView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, project_id=None):
        if project_id is not None:
            _owned_project(request.user, project_id)
        return Response(VIDEO_MODEL_CATALOG)


# Reuse image upload endpoint for frame images (same mime/size rules).
VideoFrameUploadView = ImageUploadView


def _absolutize_video_job_urls(job: VideoJob, request) -> VideoJob:
    video = job.video
    if not isinstance(video, dict):
        return job
    url = video.get("url") or ""
    if url.startswith("/"):
        rel = url
        if settings.MEDIA_URL and rel.startswith(settings.MEDIA_URL):
            rel = rel[len(settings.MEDIA_URL) :]
        job.video = {**video, "url": absolute_media_url(rel.lstrip("/"), request=request)}
    return job
