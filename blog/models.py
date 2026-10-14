import uuid

from django.db import models
from django.utils import timezone


class BlogPost(models.Model):
    """A public blog article, written in the admin dashboard. `body` uses simple Markdown."""

    STATUS_CHOICES = [("draft", "Draft"), ("published", "Published")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=80, unique=True)
    title = models.CharField(max_length=160)
    summary = models.CharField(max_length=300, blank=True, default="")  # also the search description
    body = models.TextField(blank=True, default="")
    cover = models.CharField(max_length=500, blank=True, default="")  # MEDIA-relative path
    author = models.CharField(max_length=80, blank=True, default="")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="draft")
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at", "-created_at"]

    def __str__(self) -> str:
        return self.title
