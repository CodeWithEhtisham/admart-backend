from django.contrib import admin

from projects.models import Project, SocialAccount


class SocialAccountInline(admin.TabularInline):
    """Inline editor for a project's connected social accounts."""

    model = SocialAccount
    extra = 0
    fields = ("platform", "handle", "display_name", "connected", "created_at")
    readonly_fields = ("created_at",)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    """Admin for projects."""

    list_display = ("name", "owner", "org", "last_accessed_at", "created_at")
    list_filter = ("org",)
    search_fields = ("name", "org", "owner__email", "brand_name")
    ordering = ("-last_accessed_at", "-created_at")
    readonly_fields = ("created_at", "updated_at")
    inlines = [SocialAccountInline]


@admin.register(SocialAccount)
class SocialAccountAdmin(admin.ModelAdmin):
    """Admin for connected social media accounts."""

    list_display = ("project", "platform", "handle", "connected", "created_at")
    list_filter = ("platform", "connected")
    search_fields = ("project__name", "project__owner__email", "handle", "display_name")
    ordering = ("-created_at",)
