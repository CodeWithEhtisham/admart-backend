"""Admin dashboard API for agents: edit recipes, monitor runs, cancel or retry them.

Mounted under /api/admin/agents/. Staff can view; only owners (superusers) change things,
matching the plans/packs rules in admin_panel.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response

from admin_panel.permissions import IsAdmin, IsOwnerAdmin
from admin_panel.views import AdminAPIView
from agents import engine, providers
from agents.models import AgentDeployment, AgentRecipe, AgentRun
from agents.registry import PLATFORMS, PROMPT_KEYS, SLUG_RE, STEP_BLOCKS, validate_recipe
from agents.steps import DEFAULT_PROMPTS
from content.credits import InsufficientCredits
from content.pricing import serialize_decimal

STUCK_AFTER = timedelta(minutes=10)  # queued this long, or running past its lease = stuck
FIELDS = ("name", "kind", "description", "steps", "needs", "input_kind", "input_hint", "review", "uses",
          "prompts", "is_active", "sort_order")


def recipe_data(recipe: AgentRecipe) -> dict:
    return {
        "slug": recipe.slug,
        "name": recipe.name,
        "kind": recipe.kind,
        "description": recipe.description,
        "steps": recipe.steps,
        "needs": recipe.needs,
        "inputKind": recipe.input_kind,
        "inputHint": recipe.input_hint,
        "review": recipe.review,
        "uses": recipe.uses,
        "prompts": recipe.prompts,
        "isActive": recipe.is_active,
        "sortOrder": recipe.sort_order,
        "deployments": AgentDeployment.objects.filter(agent_type=recipe.slug).count(),
        "updatedAt": recipe.updated_at,
    }


def _clean(data: dict, current: AgentRecipe | None) -> tuple[dict | None, str | None]:
    """Merge a camelCase payload over the current recipe and validate the result."""
    source = {
        "name": data.get("name"), "kind": data.get("kind"), "description": data.get("description"),
        "steps": data.get("steps"), "needs": data.get("needs"), "input_kind": data.get("inputKind"),
        "input_hint": data.get("inputHint"), "review": data.get("review"), "uses": data.get("uses"),
        "prompts": data.get("prompts"), "is_active": data.get("isActive"), "sort_order": data.get("sortOrder"),
    }
    merged = {f: getattr(current, f) for f in FIELDS} if current else {
        "description": "", "needs": [], "input_hint": "", "review": False, "uses": [], "prompts": {},
        "is_active": True, "sort_order": 100,
    }
    merged.update({k: v for k, v in source.items() if v is not None})
    name = str(merged.get("name") or "").strip()
    if not name or len(name) > 80:
        return None, "Name is required (up to 80 characters)."
    merged["name"] = name
    merged["description"] = str(merged.get("description") or "").strip()[:300]
    merged["input_hint"] = str(merged.get("input_hint") or "").strip()[:120]
    merged["review"] = bool(merged.get("review"))
    merged["is_active"] = bool(merged.get("is_active"))
    try:
        merged["sort_order"] = max(0, min(int(merged.get("sort_order") or 0), 9999))
    except (TypeError, ValueError):
        return None, "Sort order must be a number."
    merged["prompts"] = {k: v for k, v in (merged.get("prompts") or {}).items() if isinstance(v, str) and v.strip()}
    uses = merged.get("uses") or []
    if not isinstance(uses, list) or any(not isinstance(u, str) for u in uses):
        return None, "'Built from' must be a list of agent slugs."
    merged["uses"] = [u for u in uses if AgentRecipe.objects.filter(slug=u).exists()][:6]
    problem = validate_recipe(merged)
    return (None, problem) if problem else (merged, None)


class AdminAgentRecipesView(AdminAPIView):
    """GET (staff) list recipes + step blocks; POST (owner) create one."""

    def get_permissions(self):
        return [IsOwnerAdmin()] if self.request.method == "POST" else [IsAdmin()]

    def get(self, request):
        return Response(
            {
                "recipes": [recipe_data(r) for r in AgentRecipe.objects.all()],
                "stepBlocks": [{"id": k, **v} for k, v in STEP_BLOCKS.items()],
                "platforms": list(PLATFORMS),
                "defaultPrompts": {k: DEFAULT_PROMPTS[k] for k in PROMPT_KEYS},
                "providers": providers.status(),
            }
        )

    def post(self, request):
        slug = str(request.data.get("slug", "")).strip().lower()
        if not SLUG_RE.match(slug):
            return Response({"message": "ID: 2-49 lowercase letters, numbers or dashes."}, status=400)
        if AgentRecipe.objects.filter(slug=slug).exists():
            return Response({"message": "An agent with this ID already exists."}, status=400)
        data, problem = _clean(request.data, None)
        if problem:
            return Response({"message": problem}, status=400)
        recipe = AgentRecipe.objects.create(slug=slug, **data)
        return Response(recipe_data(recipe), status=status.HTTP_201_CREATED)


class AdminAgentRecipeDetailView(AdminAPIView):
    """PUT (owner): edit a recipe. Changes apply to the next runs, not ones already in progress."""

    permission_classes = [IsOwnerAdmin]

    def put(self, request, slug):
        recipe = get_object_or_404(AgentRecipe, slug=slug)
        data, problem = _clean(request.data, recipe)
        if problem:
            return Response({"message": problem}, status=400)
        for key, value in data.items():
            setattr(recipe, key, value)
        recipe.save()
        return Response(recipe_data(recipe))


def run_row(run: AgentRun) -> dict:
    return {
        "id": str(run.id),
        "agent": run.deployment.agent_type,
        "user": run.user.email,
        "project": run.project.name,
        "status": run.status,
        "step": run.step,
        "input": (run.input.get("topic") or run.input.get("text") or "")[:120],
        "credits": serialize_decimal(run.credits_reserved),
        "error": run.error,
        "attempts": run.attempts,
        "createdAt": run.created_at,
        "updatedAt": run.updated_at,
    }


class AdminAgentRunsView(AdminAPIView):
    """GET (staff): recent runs across all users with a 30-day summary."""

    permission_classes = [IsAdmin]

    def get(self, request):
        now = timezone.now()
        # Queued too long (but not a scheduled post waiting for its time), or a worker that died mid-run.
        stuck_q = Q(status="queued", updated_at__lt=now - STUCK_AFTER) & (
            Q(locked_until__isnull=True) | Q(locked_until__lte=now)
        ) | Q(status="running", locked_until__lt=now)
        runs = AgentRun.objects.select_related("deployment", "user", "project")
        wanted = request.query_params.get("status", "")
        if wanted == "stuck":
            runs = runs.filter(stuck_q)
        elif wanted:
            runs = runs.filter(status=wanted)
        try:
            limit = max(1, min(int(request.query_params.get("limit", 100)), 500))
        except ValueError:
            limit = 100
        month = AgentRun.objects.filter(created_at__gte=now - timedelta(days=30))
        counts = dict(month.order_by().values("status").annotate(n=Count("id")).values_list("status", "n"))
        finished = counts.get("failed", 0) + sum(counts.get(s, 0) for s in ("needs_review", "approved", "succeeded"))
        spent = month.exclude(status="failed").aggregate(total=Sum("credits_reserved"))["total"] or 0
        stuck = AgentRun.objects.filter(stuck_q).count()
        return Response(
            {
                "summary": {
                    "runs30d": sum(counts.values()),
                    "byStatus": counts,
                    "failureRate": round(100 * counts.get("failed", 0) / finished, 1) if finished else 0,
                    "credits30d": serialize_decimal(spent),
                    "stuck": stuck,
                    "inProgress": counts.get("queued", 0) + counts.get("running", 0),
                },
                "runs": [run_row(r) for r in runs[:limit]],
            }
        )


class AdminAgentRunActionView(AdminAPIView):
    """POST (owner): cancel (refund) or retry a run."""

    permission_classes = [IsOwnerAdmin]

    def post(self, request, run_id, action):
        run = get_object_or_404(AgentRun.objects.select_related("deployment", "user", "project"), id=run_id)
        if action == "cancel":
            if not engine.cancel(run):
                return Response({"message": "Only queued, running or paused runs can be cancelled."}, status=400)
        elif action == "retry":
            try:
                if not engine.retry(run):
                    return Response({"message": "Only failed runs can be retried."}, status=400)
            except InsufficientCredits:
                return Response({"message": "The user doesn't have enough credits to retry."}, status=400)
        else:
            return Response({"message": "Unknown action."}, status=400)
        return Response(run_row(run))
