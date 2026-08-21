"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from admin_panel.dashboard_views import admin_dashboard
from content.video_views import VideoModelCatalogView
from content.views import (
    FalModelSearchView,
    ImageModelCatalogView,
    PromptEnhanceView,
    TemplateDetailView,
    TemplateListView,
    TemplateUseView,
)
from projects.views import ProjectListCreateView, SocialCallbackView
from users.credits_views import CreditsBalanceView

urlpatterns = [
    path("admin/dashboard/", admin_dashboard, name="admin_dashboard"),
    path("admin/", admin.site.urls),
    path("api/auth/", include("users.urls")),
    # Credits: balance at /api/credits; costs/history under /api/credits/
    path("api/credits", CreditsBalanceView.as_view(), name="credits_balance"),
    path("api/credits/", include("users.credits_urls")),
    # List/create at "/api/projects" (no trailing slash); sub-routes under "/api/projects/".
    path("api/projects", ProjectListCreateView.as_view(), name="project_list_create"),
    path("api/projects/", include("projects.urls")),
    path("api/projects/", include("content.urls")),
    path("api/images/models", ImageModelCatalogView.as_view(), name="image_models"),
    path("api/videos/models", VideoModelCatalogView.as_view(), name="video_models"),
    path("api/fal/models", FalModelSearchView.as_view(), name="fal_models"),
    path("api/prompts/enhance", PromptEnhanceView.as_view(), name="prompt_enhance"),
    path("api/templates", TemplateListView.as_view(), name="template_list"),
    path("api/templates/<uuid:template_id>", TemplateDetailView.as_view(), name="template_detail"),
    path("api/templates/<uuid:template_id>/use", TemplateUseView.as_view(), name="template_use"),
    # Superadmin panel API
    path("api/admin/", include("admin_panel.urls")),
    # OAuth provider callback (browser redirect from provider; secured by signed state).
    path("api/social/callback/<str:platform>", SocialCallbackView.as_view(), name="social_callback"),
    # OpenAPI schema endpoints
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

