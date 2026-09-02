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

    list_display = ("name", "owner_email", "org", "brand_industry", "last_accessed_at", "created_at")
    list_filter = ("org",)
    search_fields = ("name", "org", "owner__email", "brand_name")
    ordering = ("-last_accessed_at", "-created_at")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"
    inlines = [SocialAccountInline]

    @admin.display(description="Owner")
    def owner_email(self, obj):
        return obj.owner.email


@admin.register(SocialAccount)
class SocialAccountAdmin(admin.ModelAdmin):
    """Admin for connected social media accounts."""

    list_display = ("platform", "handle", "display_name", "project_name", "owner_email", "connected", "created_at")
    list_filter = ("platform", "connected")
    search_fields = ("project__name", "project__owner__email", "handle", "display_name")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Project")
    def project_name(self, obj):
        return obj.project.name

    @admin.display(description="Owner")
    def owner_email(self, obj):
        return obj.project.owner.email
