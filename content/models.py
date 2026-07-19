import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class ImageJob(models.Model):
    """One fal image generation / edit request scoped to a project."""

    CAPABILITY_CHOICES = [
        ("textToImage", "Text to image"),
        ("edit", "Edit"),
        ("multiEdit", "Multi-image edit"),
        ("upscale", "Upscale"),
        ("removeBackground", "Remove background"),
    ]
    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="image_jobs",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="image_jobs",
    )
    capability = models.CharField(max_length=32, choices=CAPABILITY_CHOICES)
    model = models.CharField(max_length=200)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="queued")
    prompt = models.TextField(null=True, blank=True)
    request = models.JSONField(default=dict, blank=True)
    images = models.JSONField(default=list, blank=True)
    mask_image = models.JSONField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    credits_used = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    credits_reserved = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    seed = models.BigIntegerField(null=True, blank=True)
    fal_request_id = models.CharField(max_length=128, null=True, blank=True)
    # Canonical fal queue URLs from submit (required for models with subpaths like flux/dev).
    fal_status_url = models.URLField(max_length=1000, null=True, blank=True)
    fal_response_url = models.URLField(max_length=1000, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["project", "-created_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.capability} {self.status} ({self.id})"


class ImageUpload(models.Model):
    """Source image uploaded for edit / upscale / rembg jobs."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="image_uploads",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="image_uploads",
    )
    file = models.FileField(upload_to="projects/%Y/%m/%d/uploads/")
    content_type = models.CharField(max_length=64)
    byte_size = models.PositiveIntegerField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"upload {self.id}"


class VideoJob(models.Model):
    """One fal video generation request scoped to a project."""

    CAPABILITY_CHOICES = [
        ("textToVideo", "Text to video"),
        ("imageToVideo", "Image to video"),
        ("firstLastFrame", "First to last frame"),
    ]
    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="video_jobs",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="video_jobs",
    )
    capability = models.CharField(max_length=32, choices=CAPABILITY_CHOICES)
    model = models.CharField(max_length=200)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="queued")
    prompt = models.TextField(null=True, blank=True)
    request = models.JSONField(default=dict, blank=True)
    # Single output video asset dict: { url, contentType, fileName, providerUrl, … }
    video = models.JSONField(null=True, blank=True)
    error = models.TextField(null=True, blank=True)
    credits_used = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    credits_reserved = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    seed = models.BigIntegerField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    fal_request_id = models.CharField(max_length=128, null=True, blank=True)
    fal_status_url = models.URLField(max_length=1000, null=True, blank=True)
    fal_response_url = models.URLField(max_length=1000, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["project", "-created_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.capability} {self.status} ({self.id})"


class LibraryAsset(models.Model):
    """Browsable library item (image or video) for a project."""

    MEDIA_TYPE_CHOICES = [
        ("image", "Image"),
        ("video", "Video"),
    ]
    STATUS_CHOICES = [
        ("ready", "Ready"),
        ("generating", "Generating"),
        ("published", "Published"),
        ("scheduled", "Scheduled"),
        ("failed", "Failed"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="library_assets",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="library_assets",
    )
    media_type = models.CharField(max_length=16, choices=MEDIA_TYPE_CHOICES)
    title = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="ready")
    # CharField: local MEDIA URLs may be relative (/media/...) until absolutized in the API.
    thumbnail_url = models.CharField(max_length=2000, null=True, blank=True)
    source_url = models.CharField(max_length=2000, blank=True, default="")
    prompt = models.TextField(null=True, blank=True)
    model = models.CharField(max_length=200, null=True, blank=True)
    capability = models.CharField(max_length=32, null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    image_job = models.ForeignKey(
        ImageJob,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="library_assets",
    )
    video_job = models.ForeignKey(
        "content.VideoJob",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="library_assets",
    )
    source_index = models.PositiveSmallIntegerField(default=0)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["project", "-created_at"]),
            models.Index(fields=["project", "media_type", "-created_at"]),
            models.Index(fields=["project", "deleted_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["image_job", "source_index"],
                name="uniq_library_asset_job_index",
            ),
            models.UniqueConstraint(
                fields=["video_job", "source_index"],
                name="uniq_library_asset_video_job_index",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.media_type} {self.status} ({self.id})"
