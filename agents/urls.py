from django.urls import path

from agents.views import (
    DeploymentDetailView,
    DeploymentListCreateView,
    RunActionView,
    RunDetailView,
    RunListCreateView,
)

urlpatterns = [
    path("<uuid:project_id>/agents", DeploymentListCreateView.as_view(), name="agent_deployments"),
    path("<uuid:project_id>/agents/<uuid:deployment_id>", DeploymentDetailView.as_view(), name="agent_deployment"),
    path("<uuid:project_id>/agents/<uuid:deployment_id>/runs", RunListCreateView.as_view(), name="agent_runs"),
    path(
        "<uuid:project_id>/agents/<uuid:deployment_id>/runs/<uuid:run_id>",
        RunDetailView.as_view(),
        name="agent_run",
    ),
    path(
        "<uuid:project_id>/agents/<uuid:deployment_id>/runs/<uuid:run_id>/<str:action>",
        RunActionView.as_view(),
        name="agent_run_action",
    ),
]
