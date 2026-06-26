import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class Project(models.Model):
    """A workspace owned by a user.

    A user can own many projects. Each project is the parent/bounded context for
    its own social media accounts, brand kit, and settings — because a single
    person typically manages several distinct brands or sets of social accounts.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="projects",
    )

    name = models.CharField(max_length=80)
    icon = models.CharField(max_length=16, blank=True, default="")
    color = models.CharField(max_length=7, blank=True, default="#2563eb")
    org = models.CharField(max_length=120, blank=True, default="")

    # Per-project brand kit / settings. Each project carries its own brand
    # identity independent of the owning user.
    brand_name = models.CharField(max_length=255, blank=True, default="")
    brand_industry = models.CharField(max_length=100, blank=True, default="")
    brand_color_hex = models.CharField(max_length=7, blank=True, default="#2563eb")
    brand_logo_url = models.URLField(max_length=1000, null=True, blank=True)

    # Recency tracking — used to auto-select the active project on login.
    last_accessed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_accessed_at", "-created_at"]
        indexes = [
            models.Index(fields=["owner", "-last_accessed_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.owner_id})"

    def touch(self) -> None:
        """Mark this project as accessed now."""
        self.last_accessed_at = timezone.now()
        self.save(update_fields=["last_accessed_at", "updated_at"])

    @property
    def brand_kit(self) -> dict:
        """Return the project's brand kit as a camelCase dict."""
        return {
            "brandName": self.brand_name,
            "industry": self.brand_industry,
            "brandColorHex": self.brand_color_hex,
            "logoUrl": self.brand_logo_url,
        }


class SocialAccount(models.Model):
    """A connected social media account that belongs to a single Project.

    Tracks OAuth connections to TikTok, YouTube, Instagram, and Facebook. Scoped
    to a project so each project manages its own set of platform connections.
    """

    PLATFORM_CHOICES = [
        ("tiktok", "TikTok"),
        ("youtube", "YouTube"),
        ("instagram", "Instagram"),
        ("facebook", "Facebook"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="social_accounts",
    )
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES)
    handle = models.CharField(max_length=255, blank=True, default="")
    display_name = models.CharField(max_length=255, blank=True, default="")
    access_token = models.TextField(blank=True, default="")
    refresh_token = models.TextField(blank=True, default="")
    token_expires_at = models.DateTimeField(null=True, blank=True)
    connected = models.BooleanField(default=True)
    avatar_url = models.URLField(max_length=1000, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["platform"]
        unique_together = [("project", "platform")]

    def __str__(self) -> str:
        return f"{self.project_id} — {self.platform}"
