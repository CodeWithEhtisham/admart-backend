from django.contrib import admin

from django.utils.html import format_html

from content.models import FalModelListing, ImageJob, ImageUpload, LibraryAsset, Template, TemplateUseEvent


@admin.register(FalModelListing)
class FalModelListingAdmin(admin.ModelAdmin):
    """New fal models found by the daily discover_fal_models job. Users never see these; adding
    one to Admart is a code change (input mapping + option prices), then it shows as "added"."""

    list_display = ("label", "endpoint_id", "category", "price", "status", "first_seen", "fal_page")
    list_filter = ("status", "category")
    search_fields = ("label", "endpoint_id")
    readonly_fields = ("endpoint_id", "label", "category", "description", "model_url", "unit_price", "unit",
                       "first_seen", "last_seen")
    actions = ("mark_ignored", "mark_new")

    @admin.display(description="fal price")
    def price(self, obj):
        return f"${obj.unit_price.normalize()} per {obj.unit}" if obj.unit_price is not None else "-"

    @admin.display(description="fal page")
    def fal_page(self, obj):
        return format_html('<a href="{}" target="_blank" rel="noopener">Open</a>', obj.model_url) if obj.model_url else "-"

    @admin.action(description="Ignore (not useful for Admart)")
    def mark_ignored(self, request, queryset):
        queryset.update(status="ignored")

    @admin.action(description="Mark as new again")
    def mark_new(self, request, queryset):
        queryset.exclude(status="added").update(status="new")


@admin.register(ImageJob)
class ImageJobAdmin(admin.ModelAdmin):
    list_display = ("id", "capability", "model", "status", "project", "user", "created_at")
    list_filter = ("capability", "status", "model")
    search_fields = ("id", "fal_request_id", "prompt")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ImageUpload)
class ImageUploadAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "user", "content_type", "byte_size", "created_at")
    search_fields = ("id",)


@admin.register(LibraryAsset)
class LibraryAssetAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "media_type",
        "status",
        "title",
        "project",
        "capability",
        "created_at",
        "deleted_at",
    )
    list_filter = ("media_type", "status")
    search_fields = ("id", "title", "prompt")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Template)
class TemplateAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "category",
        "format",
        "is_video",
        "uses_count",
        "uses_last_7d",
        "is_active",
        "created_at",
    )
    list_filter = ("category", "is_video", "is_active")
    search_fields = ("title", "format")
    readonly_fields = ("id", "uses_count", "uses_last_7d", "created_at", "updated_at")


@admin.register(TemplateUseEvent)
class TemplateUseEventAdmin(admin.ModelAdmin):
    list_display = ("template", "user", "created_at")
    list_filter = ("created_at",)
    search_fields = ("template__title", "user__email")
    readonly_fields = ("id", "template", "user", "created_at")
