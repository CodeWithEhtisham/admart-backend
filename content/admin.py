from django.contrib import admin

from content.models import ImageJob, ImageUpload, LibraryAsset, Template, TemplateUseEvent


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
