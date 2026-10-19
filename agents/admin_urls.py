from django.urls import path

from agents.admin_views import (
    AdminAgentRecipeDetailView,
    AdminAgentRecipesView,
    AdminAgentRunActionView,
    AdminAgentRunsView,
)

# Mounted under /api/admin/agents/.
urlpatterns = [
    path("recipes", AdminAgentRecipesView.as_view(), name="admin_agent_recipes"),
    path("recipes/<slug:slug>", AdminAgentRecipeDetailView.as_view(), name="admin_agent_recipe"),
    path("runs", AdminAgentRunsView.as_view(), name="admin_agent_runs"),
    path("runs/<uuid:run_id>/<str:action>", AdminAgentRunActionView.as_view(), name="admin_agent_run_action"),
]
