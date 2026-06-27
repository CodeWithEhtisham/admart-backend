from django.urls import path

from projects.views import (
    ProjectActivateView,
    ProjectDetailView,
    ProjectSocialConnectView,
    ProjectSocialDisconnectView,
    ProjectSocialListView,
    SocialConnectUrlView,
)

# Sub-routes mounted under the "api/projects/" prefix. The bare list/create
# route lives in config.urls so it matches "/api/projects" with no trailing slash.
urlpatterns = [
    path("<uuid:id>", ProjectDetailView.as_view(), name="project_detail"),
    path("<uuid:id>/activate", ProjectActivateView.as_view(), name="project_activate"),
    # Project-scoped social accounts
    path(
        "<uuid:project_id>/social/accounts",
        ProjectSocialListView.as_view(),
        name="project_social_list",
    ),
    path(
        "<uuid:project_id>/social/connect/<str:platform>/url",
        SocialConnectUrlView.as_view(),
        name="project_social_connect_url",
    ),
    path(
        "<uuid:project_id>/social/connect/<str:platform>",
        ProjectSocialConnectView.as_view(),
        name="project_social_connect",
    ),
    path(
        "<uuid:project_id>/social/disconnect/<str:platform>",
        ProjectSocialDisconnectView.as_view(),
        name="project_social_disconnect",
    ),
]
