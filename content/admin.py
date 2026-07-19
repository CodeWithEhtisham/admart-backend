from django.contrib import admin

from content.models import ImageJob, ImageUpload


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
