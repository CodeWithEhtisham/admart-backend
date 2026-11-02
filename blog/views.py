"""Blog: public list/article API, and admin dashboard API to write posts and upload images."""

from __future__ import annotations

import uuid

from django.core.files.storage import default_storage
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from admin_panel.permissions import IsAdmin
from admin_panel.views import AdminAPIView
from blog.models import BlogPost
from content.storage_utils import absolute_media_url

IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def post_data(post: BlogPost, request, body: bool = True) -> dict:
    data = {
        "id": str(post.id),
        "slug": post.slug,
        "title": post.title,
        "summary": post.summary,
        "coverUrl": absolute_media_url(post.cover, request=request) if post.cover else None,
        "author": post.author,
        "status": post.status,
        "publishedAt": post.published_at,
        "updatedAt": post.updated_at,
    }
    if body:
        data.update(body=post.body, cover=post.cover)
    return data


class BlogListView(APIView):
    """GET /api/blog — published posts, newest first."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request):
        posts = BlogPost.objects.filter(status="published")[:100]
        return Response([post_data(p, request, body=False) for p in posts])


class BlogDetailView(APIView):
    """GET /api/blog/<slug> — one published post."""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request, slug):
        return Response(post_data(get_object_or_404(BlogPost, slug=slug, status="published"), request))


def _apply(post: BlogPost, data: dict) -> str | None:
    """Copy the editable fields onto `post`; return a readable problem or None."""
    for field, limit in (("title", 160), ("summary", 300), ("author", 80)):
        if field in data:
            setattr(post, field, str(data[field] or "").strip()[:limit])
    if "body" in data:
        post.body = str(data["body"] or "")
    if "cover" in data:
        cover = str(data["cover"] or "")
        if cover and not cover.startswith("blog/"):
            return "Upload the cover image here first."
        post.cover = cover
    if not post.title:
        return "Give the post a title."
    slug = slugify(str(data.get("slug") or post.slug or post.title))[:80]
    if not slug:
        return "Give the post a web address (letters and numbers)."
    if BlogPost.objects.filter(slug=slug).exclude(id=post.id).exists():
        return "Another post already uses this web address."
    post.slug = slug
    if data.get("status") in ("draft", "published"):
        post.status = data["status"]
    if post.status == "published" and not post.published_at:
        post.published_at = timezone.now()
    return None


class AdminBlogPostsView(AdminAPIView):
    """GET|POST /api/admin/blog/posts"""

    permission_classes = [IsAdmin]

    def get(self, request):
        return Response([post_data(p, request, body=False) for p in BlogPost.objects.all()])

    def post(self, request):
        post = BlogPost()
        problem = _apply(post, request.data)
        if problem:
            return Response({"message": problem}, status=status.HTTP_400_BAD_REQUEST)
        post.save()
        return Response(post_data(post, request), status=status.HTTP_201_CREATED)


class AdminBlogPostDetailView(AdminAPIView):
    """GET|PATCH|DELETE /api/admin/blog/posts/<id>"""

    permission_classes = [IsAdmin]

    def get(self, request, post_id):
        return Response(post_data(get_object_or_404(BlogPost, id=post_id), request))

    def patch(self, request, post_id):
        post = get_object_or_404(BlogPost, id=post_id)
        problem = _apply(post, request.data)
        if problem:
            return Response({"message": problem}, status=status.HTTP_400_BAD_REQUEST)
        post.save()
        return Response(post_data(post, request))

    def delete(self, request, post_id):
        get_object_or_404(BlogPost, id=post_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminBlogImageView(AdminAPIView):
    """POST /api/admin/blog/images — upload a cover or in-article image; returns its path and URL."""

    permission_classes = [IsAdmin]

    def post(self, request):
        upload = request.FILES.get("file")
        ext = IMAGE_TYPES.get((getattr(upload, "content_type", "") or "").lower()) if upload else None
        if not ext:
            return Response({"message": "Upload a JPEG, PNG or WebP image."}, status=status.HTTP_400_BAD_REQUEST)
        if upload.size > MAX_IMAGE_BYTES:
            return Response({"message": "Images can be up to 8 MB."}, status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        path = default_storage.save(f"blog/{uuid.uuid4().hex}{ext}", upload)
        return Response({"path": path, "url": absolute_media_url(path, request=request)}, status=status.HTTP_201_CREATED)
