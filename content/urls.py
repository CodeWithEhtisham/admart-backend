from django.urls import path

from content.views import (
    ImageJobCancelView,
    ImageJobDetailView,
    ImageJobListCreateView,
    ImageModelCatalogView,
    ImageUploadView,
    LibraryDetailView,
    LibraryListView,
)

urlpatterns = [
    path(
        "<uuid:project_id>/images/jobs",
        ImageJobListCreateView.as_view(),
        name="image_job_list_create",
    ),
    path(
        "<uuid:project_id>/images/jobs/<uuid:job_id>",
        ImageJobDetailView.as_view(),
        name="image_job_detail",
    ),
    path(
        "<uuid:project_id>/images/jobs/<uuid:job_id>/cancel",
        ImageJobCancelView.as_view(),
        name="image_job_cancel",
    ),
    path(
        "<uuid:project_id>/images/uploads",
        ImageUploadView.as_view(),
        name="image_upload",
    ),
    path(
        "<uuid:project_id>/images/models",
        ImageModelCatalogView.as_view(),
        name="image_models_project",
    ),
    path(
        "<uuid:project_id>/library",
        LibraryListView.as_view(),
        name="library_list",
    ),
    path(
        "<uuid:project_id>/library/<uuid:asset_id>",
        LibraryDetailView.as_view(),
        name="library_detail",
    ),
]
