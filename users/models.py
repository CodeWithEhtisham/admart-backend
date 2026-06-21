import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    """Custom manager for the custom User model where email is the unique identifier."""

    def create_user(
        self, email: str, password: str | None = None, **extra_fields
    ) -> "User":
        """Create and save a regular User with the given email and password."""
        if not email:
            raise ValueError("The Email field must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_superuser(
        self, email: str, password: str | None = None, **extra_fields
    ) -> "User":
        """Create and save a SuperUser with the given email and password."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("plan", "agency")
        extra_fields.setdefault("credits_total", 500)
        extra_fields.setdefault("credits_remaining", 500)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Custom User model matching the Vidify specification."""

    PLAN_CHOICES = [
        ("free", "Free"),
        ("starter", "Starter"),
        ("pro", "Pro"),
        ("agency", "Agency"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    avatar_url = models.URLField(max_length=1000, null=True, blank=True)
    google_id = models.CharField(max_length=255, null=True, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default="free")
    credits_total = models.IntegerField(default=5)
    credits_used = models.IntegerField(default=0)
    credits_remaining = models.IntegerField(default=5)
    credits_reset_at = models.DateTimeField(null=True, blank=True)
    onboarding_completed = models.BooleanField(default=False)

    # Brand Kit fields
    brand_name = models.CharField(max_length=255, blank=True)
    brand_industry = models.CharField(max_length=100, blank=True)
    brand_color_hex = models.CharField(max_length=7, default="#2563eb")
    brand_logo_url = models.URLField(max_length=1000, null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.email

    @property
    def brand_kit(self) -> dict:
        """Returns the onboarding brand kit as a dictionary."""
        return {
            "brandName": self.brand_name,
            "industry": self.brand_industry,
            "brandColorHex": self.brand_color_hex,
            "logoUrl": self.brand_logo_url,
        }
