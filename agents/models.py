import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class AgentRecipe(models.Model):
    """An agent in the catalog: which step blocks it runs, its prompts and presentation.

    Editable in the admin dashboard; see agents.registry for the step blocks and validation.
    """

    KIND_CHOICES = [("small", "Single task"), ("large", "Full automation")]
    INPUT_CHOICES = [("topic", "Topic"), ("text", "Text"), ("video", "Video"), ("report", "Report")]

    slug = models.SlugField(max_length=50, primary_key=True)
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=8, choices=KIND_CHOICES, default="small")
    description = models.CharField(max_length=300, blank=True, default="")
    steps = models.JSONField(default=list)
    needs = models.JSONField(default=list, blank=True)
    input_kind = models.CharField(max_length=8, choices=INPUT_CHOICES, default="topic")
    input_hint = models.CharField(max_length=120, blank=True, default="")
    review = models.BooleanField(default=False)
    uses = models.JSONField(default=list, blank=True)
    prompts = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=100)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


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
    # Autopilot: start runs on a schedule. schedule = {"days": [0-6 (Mon=0)], "time": "HH:MM", "tz": "Area/City"}
    autopilot = models.BooleanField(default=False)
    schedule = models.JSONField(default=dict, blank=True)
    topic_queue = models.JSONField(default=list, blank=True)  # used first; empty = agent picks from the niche
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)
    autopilot_note = models.CharField(max_length=200, blank=True, default="")  # last skip reason, shown to the user
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
