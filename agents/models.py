import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class AgentDeployment(models.Model):
    """An agent from the catalog (registry slug) deployed to a project."""

    STATUS_CHOICES = [("active", "Active"), ("paused", "Paused")]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="agent_deployments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agent_deployments")
    agent_type = models.CharField(max_length=50)
    config = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="active")
    monthly_credit_limit = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]


class AgentRun(models.Model):
    """One execution of a deployed agent; the worker advances it step by step."""

    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("running", "Running"),
        ("needs_review", "Needs review"),
        ("approved", "Approved"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("discarded", "Discarded"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    deployment = models.ForeignKey(AgentDeployment, on_delete=models.CASCADE, related_name="runs")
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="agent_runs")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="agent_runs")
    input = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="queued")
    step = models.CharField(max_length=32, blank=True, default="")
    output = models.JSONField(default=dict, blank=True)
    library_asset = models.ForeignKey(
        "content.LibraryAsset", on_delete=models.SET_NULL, null=True, blank=True, related_name="agent_runs"
    )
    credits_reserved = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    topup_reserved = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    error = models.TextField(blank=True, default="")
    attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["deployment", "-created_at"]),
        ]
