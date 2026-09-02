from django.urls import path

from projects.ads_views import (
    AdsConnectUrlView,
    AdsDisconnectView,
    ProjectAdAccountListView,
    ProjectAdBoostView,
)
from projects.publish_views import ProjectPublishView, ProjectYoutubePlaylistsView, ProjectYoutubeSuggestView
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
    path("<uuid:project_id>/publish", ProjectPublishView.as_view(), name="project_publish"),
    path(
        "<uuid:project_id>/social/youtube/playlists",
        ProjectYoutubePlaylistsView.as_view(),
        name="project_youtube_playlists",
    ),
    path(
        "<uuid:project_id>/publish/youtube/suggest",
        ProjectYoutubeSuggestView.as_view(),
        name="project_youtube_suggest",
    ),
    path("<uuid:project_id>/ads/accounts", ProjectAdAccountListView.as_view(), name="project_ads_list"),
    path(
        "<uuid:project_id>/ads/connect/<str:provider>/url",
        AdsConnectUrlView.as_view(),
        name="project_ads_connect_url",
    ),
    path(
        "<uuid:project_id>/ads/disconnect/<str:provider>",
        AdsDisconnectView.as_view(),
        name="project_ads_disconnect",
    ),
    path("<uuid:project_id>/ads/boost", ProjectAdBoostView.as_view(), name="project_ads_boost"),
]
