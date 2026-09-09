import mimetypes
import uuid
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from content import fal_client
from content.catalog import MODEL_CATALOG
from content.credits import InsufficientCredits, refund_credits, reserve_credits
from content.fal_models import (
    FalModelSearchError,
    catalog_discovery_payload,
    search_fal_models,
)
from content.jobs import refresh_job
from content.library import mark_library_generating, sync_library_from_image_job
from content.mapping import build_fal_input
from content.models import FavoriteTemplate, ImageJob, ImageUpload, LibraryAsset, Template, TemplateUseEvent
from content.pricing import attach_image_pricing, quote_image_job, quote_response
from content.prompt_enhancer import enhance_prompt
from content.serializers import (
    ImageJobCreateSerializer,
    ImageJobSerializer,
    LibraryAssetSerializer,
    PromptEnhanceSerializer,
    TemplateSerializer,
)
from content.storage_utils import absolute_media_url
from content.url_resolve import resolve_urls_for_fal
from projects.models import Project

ALLOWED_UPLOAD_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB

ALLOWED_LIBRARY_IMAGE_TYPES = ALLOWED_UPLOAD_TYPES
ALLOWED_LIBRARY_VIDEO_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "video/x-m4v",
}
MAX_LIBRARY_VIDEO_BYTES = 200 * 1024 * 1024  # 200 MB
TEMPLATE_PAGE_SIZE = 18


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
        quote = quote_image_job(capability, model, data)
        amount = quote["credits_decimal"]

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
                    "creditsRequired": quote_response(quote)["credits"],
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
            fal_cost_usd=quote.get("fal_cost_decimal", 0),
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
        payload["creditsRequired"] = quote_response(quote)["credits"]
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
            refund_credits(request.user, job.credits_reserved)
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
        payload = attach_image_pricing(MODEL_CATALOG)
        if _truthy(request.query_params.get("discover")):
            payload["_fal"] = catalog_discovery_payload("image")
        return Response(payload)


class PromptEnhanceView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ser = PromptEnhanceSerializer(data=request.data)
        if not ser.is_valid():
            err = ser.errors
            if isinstance(err, dict):
                for key, val in err.items():
                    msg = val[0] if isinstance(val, list) else val
                    return Response(
                        {"message": str(msg), "field": key},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            return Response({"message": "Invalid request"}, status=status.HTTP_400_BAD_REQUEST)

        data = ser.validated_data
        result = enhance_prompt(
            prompt=data["prompt"],
            kind=data.get("kind") or "image",
            negative_prompt=data.get("negativePrompt") or "",
            context=data.get("context") or {},
        )
        return Response(result)


# Categories used before the meigen-style scheme; mapped on read so old rows
# keep showing up under the new tabs until the next gallery refresh rewrites them.
_LEGACY_CATEGORY_MAP = {
    "ad": "ads-product",
    "ads": "ads-product",
    "product": "ads-product",
    "announce": "ads-product",
    "announcement": "ads-product",
    "carousel": "ads-product",
    "story": "ads-product",
    "reel": "video",
}


def _with_current_categories(queryset):
    """Annotate legacy category values onto their new meigen-style slugs.

    New rows are written with the new slugs directly; this only affects rows
    created before the category migration until the gallery refresh updates them.
    """
    from django.db.models import Case, CharField, Value, When

    whens = [
        When(category=old, then=Value(new)) for old, new in _LEGACY_CATEGORY_MAP.items()
    ]
    return queryset.annotate(
        current_category=Case(*whens, default=F("category"), output_field=CharField())
    )


def _category_stats():
    """Per-category image/video counts for the frontend category pills."""
    from django.db.models import Count, Q

    stats = {
        slug: {"images": 0, "videos": 0}
        for slug, _label in Template.CATEGORY_CHOICES
    }
    rows = (
        _with_current_categories(Template.objects.filter(is_active=True))
        .values("current_category")
        .annotate(
            images=Count("id", filter=Q(is_video=False)),
            videos=Count("id", filter=Q(is_video=True)),
        )
    )
    for row in rows:
        entry = stats.get(row["current_category"])
        if entry is not None:
            entry["images"] = row["images"]
            entry["videos"] = row["videos"]
    all_stats = {
        "images": sum(entry["images"] for entry in stats.values()),
        "videos": sum(entry["videos"] for entry in stats.values()),
    }
    stats["all"] = all_stats
    return stats


def _category(request):
    return (request.query_params.get("category") or "").strip().lower()


class TemplateListView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        qs = _with_current_categories(Template.objects.filter(is_active=True))

        category = _category(request)
        if category and category != "all":
            qs = qs.filter(current_category=category)

        media = (request.query_params.get("media") or "").strip().lower()
        if media == "image":
            qs = qs.filter(is_video=False)
        elif media == "video":
            qs = qs.filter(is_video=True)

        search = (request.query_params.get("search") or "").strip()
        if search:
            # Search titles plus the full prompt/description text stored in
            # template_config (titles are often truncated or just "{").
            qs = qs.filter(
                Q(title__icontains=search)
                | Q(template_config__prompt__icontains=search)
                | Q(template_config__description__icontains=search)
            )

        model_name = (request.query_params.get("model") or "").strip()
        if model_name and model_name != "all":
            qs = qs.filter(template_config__modelName__iexact=model_name)

        sort = (request.query_params.get("sort") or "featured").strip().lower()
        if sort == "trending":
            # Real trending: only templates actually used in the rolling 7-day window.
            qs = qs.filter(uses_last_7d__gt=0).order_by(
                "-uses_last_7d", "-uses_count", "-created_at"
            )
        elif sort in {"new", "newest"}:
            qs = qs.order_by("-created_at", "title")
        elif sort in {"uses", "popular"}:
            qs = qs.order_by("-uses_count", "-uses_last_7d", "-created_at")
        else:
            qs = qs.order_by("-uses_last_7d", "-uses_count", "-created_at")

        try:
            offset = max(int(request.query_params.get("cursor") or 0), 0)
        except (TypeError, ValueError):
            offset = 0

        page = list(qs[offset : offset + TEMPLATE_PAGE_SIZE + 1])
        has_more = len(page) > TEMPLATE_PAGE_SIZE
        items = page[:TEMPLATE_PAGE_SIZE]
        next_cursor = str(offset + TEMPLATE_PAGE_SIZE) if has_more else None

        data = TemplateSerializer(
            items,
            many=True,
            context={
                "trending_ids": _trending_template_ids(),
                "favorite_ids": _favorite_template_ids(request.user),
            },
        ).data
        return Response(
            {
                "items": data,
                "nextCursor": next_cursor,
                "count": qs.count(),
                "categoryStats": _category_stats(),
            }
        )


class TemplateDetailView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, template_id):
        template = _with_current_categories(
            Template.objects.filter(id=template_id, is_active=True)
        ).first()
        if template is None:
            return Response(
                {"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND
            )
        return Response(
            TemplateSerializer(
                template,
                context={
                    "trending_ids": _trending_template_ids(),
                    "favorite_ids": _favorite_template_ids(request.user),
                },
            ).data
        )


class TemplateUseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, template_id):
        with transaction.atomic():
            template = (
                Template.objects.select_for_update().filter(id=template_id).first()
            )
            if template is None:
                return Response(
                    {"detail": "Template not found."}, status=status.HTTP_404_NOT_FOUND
                )
            # Favorited templates stay usable even after a gallery refresh
            # deactivates them (favorites outlive template refreshes).
            is_favorite = FavoriteTemplate.objects.filter(
                user=request.user, template=template
            ).exists()
            if not template.is_active and not is_favorite:
                return Response(
                    {"detail": "Template is no longer available."},
                    status=status.HTTP_404_NOT_FOUND,
                )
            TemplateUseEvent.objects.create(template=template, user=request.user)
            Template.objects.filter(id=template.id).update(
                uses_count=F("uses_count") + 1,
                uses_last_7d=F("uses_last_7d") + 1,
            )
            template.refresh_from_db()

        serialized = TemplateSerializer(
            template,
            context={
                "trending_ids": _trending_template_ids(),
                "favorite_ids": _favorite_template_ids(request.user),
            },
        ).data
        return Response(
            {
                "template": serialized,
                "templateConfig": template.template_config,
            }
        )


class TemplateFavoriteListView(APIView):
    """List the current user's favorited templates.

    Includes templates deactivated by gallery refreshes so favorites never
    disappear from the user's collection.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        favorite_ids = _favorite_template_ids(request.user)
        templates = _with_current_categories(
            Template.objects.filter(
                id__in=favorite_ids,
                favorited_by__user=request.user,
            )
        ).order_by("-favorited_by__created_at")
        data = TemplateSerializer(
            templates,
            many=True,
            context={
                "trending_ids": _trending_template_ids(),
                "favorite_ids": favorite_ids,
            },
        ).data
        return Response({"items": data, "count": len(data)})


class TemplateFavoriteView(APIView):
    """Add (POST) or remove (DELETE) a template from the user's favorites."""

    permission_classes = [IsAuthenticated]

    def post(self, request, template_id):
        template = Template.objects.filter(id=template_id).first()
        if template is None:
            return Response(
                {"detail": "Template not found."}, status=status.HTTP_404_NOT_FOUND
            )
        _, created = FavoriteTemplate.objects.get_or_create(
            user=request.user, template=template
        )
        return Response(
            {"templateId": str(template.id), "isFavorite": True, "created": created},
            status=status.HTTP_200_OK,
        )

    def delete(self, request, template_id):
        deleted, _ = FavoriteTemplate.objects.filter(
            user=request.user, template_id=template_id
        ).delete()
        if not deleted:
            return Response(
                {"detail": "Template is not in favorites."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({"templateId": str(template_id), "isFavorite": False})


class FalModelSearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            limit = min(int(request.query_params.get("limit", 50)), 100)
        except (TypeError, ValueError):
            limit = 50
        try:
            payload = search_fal_models(
                q=(request.query_params.get("q") or "").strip(),
                category=(request.query_params.get("category") or "").strip(),
                capability=(request.query_params.get("capability") or "").strip(),
                status=(request.query_params.get("status") or "active").strip(),
                limit=limit,
                cursor=(request.query_params.get("cursor") or "").strip(),
                expand=(request.query_params.get("expand") or "").strip(),
                include_pricing=not _falsey(request.query_params.get("pricing")),
            )
        except FalModelSearchError as exc:
            return Response({"message": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(payload)


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


class LibraryUploadView(APIView):
    """POST /api/projects/:id/library/uploads — user image or video into library."""

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

        content_type = (upload.content_type or "").split(";")[0].strip().lower()
        if not content_type or content_type == "application/octet-stream":
            guessed, _ = mimetypes.guess_type(upload.name or "")
            content_type = (guessed or "").lower()

        if content_type in ALLOWED_LIBRARY_IMAGE_TYPES:
            media_type = "image"
            max_bytes = MAX_UPLOAD_BYTES
        elif content_type in ALLOWED_LIBRARY_VIDEO_TYPES:
            media_type = "video"
            max_bytes = MAX_LIBRARY_VIDEO_BYTES
        else:
            return Response(
                {
                    "message": "Only jpeg, png, webp images or mp4/mov/webm videos are allowed",
                    "field": "file",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if upload.size > max_bytes:
            return Response(
                {"message": "File too large"},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        # Never trust the client filename extension — map from verified MIME only.
        ext_by_type = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "video/mp4": ".mp4",
            "video/quicktime": ".mov",
            "video/webm": ".webm",
            "video/x-m4v": ".m4v",
        }
        ext = ext_by_type.get(content_type) or (
            ".mp4" if media_type == "video" else ".png"
        )

        rel = f"projects/{project.id}/library/{uuid.uuid4().hex}{ext}"
        saved = default_storage.save(rel, upload)
        url = absolute_media_url(saved, request=request)
        raw_name = Path(upload.name or "").stem
        # Strip path junk / control chars from display title only.
        title = "".join(c for c in raw_name if c.isprintable() and c not in "/\\")[:255]
        if not title:
            title = f"Uploaded {media_type}"

        asset = LibraryAsset.objects.create(
            project=project,
            user=request.user,
            media_type=media_type,
            title=title,
            status="ready",
            thumbnail_url=url,
            source_url=url,
            capability="upload",
            model="upload",
        )
        data = LibraryAssetSerializer(asset).data
        for key in ("sourceUrl", "thumbnailUrl"):
            u = data.get(key) or ""
            if u.startswith("/"):
                rel_url = u
                if settings.MEDIA_URL and rel_url.startswith(settings.MEDIA_URL):
                    rel_url = rel_url[len(settings.MEDIA_URL) :]
                data[key] = absolute_media_url(rel_url.lstrip("/"), request=request)

        return Response(data, status=status.HTTP_201_CREATED)


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


def _truthy(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _falsey(value) -> bool:
    return str(value or "").strip().lower() in {"0", "false", "no", "off"}


def _trending_template_ids() -> set:
    return set(
        Template.objects.filter(is_active=True, uses_last_7d__gt=0)
        .order_by("-uses_last_7d", "-uses_count")
        .values_list("id", flat=True)[:6]
    )


def _favorite_template_ids(user) -> set:
    """Return the set of template ids the user has favorited (empty for anonymous)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return set()
    return set(
        FavoriteTemplate.objects.filter(user=user).values_list("template_id", flat=True)
    )
