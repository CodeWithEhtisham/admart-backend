"""Agents API: catalog, deployments per project, runs."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from agents import engine
from agents.models import AgentDeployment, AgentRun
from agents.runs import OPEN_STATUSES, RunRefused, clean_schedule, clean_topics, month_spend, next_slot, start_run
from agents.registry import MAX_TEXT_INPUT, STYLES, active_agents, catalog_entry, get_agent, image_credits
from agents.steps import clean_script, scored_hook
from content.credits import InsufficientCredits, refund_credits, reserve_credits
from content.pricing import serialize_decimal
from content.storage_utils import absolute_media_url
from projects.models import Project

# Stopping at these checkpoints refunds the run: nothing expensive has been made yet.
REFUNDABLE_GATES = ("concept", "script")


def _bad(message: str, code: str = "INVALID", http=status.HTTP_400_BAD_REQUEST, **extra) -> Response:
    return Response({"message": message, "code": code, **extra}, status=http)


def _media(rel: str | None, request) -> str | None:
    return absolute_media_url(rel, request=request) if rel else None


def deployment_data(deployment: AgentDeployment) -> dict:
    spec = get_agent(deployment.agent_type)
    return {
        "id": str(deployment.id),
        "agentType": deployment.agent_type,
        "name": spec.name if spec else deployment.agent_type,
        "kind": spec.kind if spec else "small",
        "agent": catalog_entry(spec) if spec else None,
        "status": deployment.status,
        "config": deployment.config,
        "monthlyCreditLimit": serialize_decimal(deployment.monthly_credit_limit)
        if deployment.monthly_credit_limit is not None
        else None,
        "creditsThisMonth": serialize_decimal(month_spend(deployment)),
        "autopilot": deployment.autopilot,
        "schedule": deployment.schedule,
        "topicQueue": deployment.topic_queue,
        "nextRunAt": deployment.next_run_at if deployment.autopilot else None,
        "autopilotNote": deployment.autopilot_note,
        "createdAt": deployment.created_at,
    }


def run_data(run: AgentRun, request) -> dict:
    out = run.output or {}
    spec = get_agent(run.deployment.agent_type)
    return {
        "id": str(run.id),
        "deploymentId": str(run.deployment_id),
        "status": run.status,
        "step": run.step,
        "steps": list(spec.steps) if spec else [],
        "input": run.input,
        "error": run.error,
        "credits": serialize_decimal(run.credits_reserved),
        "title": out.get("title", ""),
        "thumbnailText": out.get("thumbnail_text", ""),
        "titleCheck": out.get("title_check", []),
        "description": out.get("description", ""),
        "tags": out.get("tags", []),
        "research": out.get("research"),
        "concepts": out.get("concepts", []),
        "concept": out.get("concept"),
        "scenes": [
            {
                "narration": s.get("narration", ""),
                "imagePrompt": s.get("image_prompt", ""),
                "visual": s.get("visual", "image"),
                "stockQuery": s.get("stock_query", ""),
                "imageUrl": _media(s.get("image"), request),
                "clipUrl": _media(s.get("clip"), request),
                "credit": s.get("credit"),
                "audioUrl": _media(s.get("audio"), request),
                "duration": s.get("duration"),
            }
            for s in out.get("scenes", [])
        ],
        "checks": out.get("checks", []),
        "log": out.get("log", {}),
        "music": out.get("music"),
        "videoUrl": _media(out.get("video"), request),
        "thumbnailUrl": _media(out.get("thumbnail"), request),
        "duration": out.get("duration"),
        "libraryAssetId": str(run.library_asset_id) if run.library_asset_id else None,
        "createdAt": run.created_at,
        "updatedAt": run.updated_at,
        "finishedAt": run.finished_at,
    }


def _parse_limit(raw):
    """Monthly credit limit: None/'' clears it; otherwise a non-negative number."""
    if raw in (None, ""):
        return None
    try:
        value = Decimal(str(raw))
    except InvalidOperation:
        raise ValueError("Monthly credit limit must be a number.")
    if not value.is_finite() or value < 0 or value > Decimal("1000000"):
        raise ValueError("Monthly credit limit must be between 0 and 1,000,000.")
    return value


def _parse_config(raw) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict) or len(json.dumps(raw)) > 2000:
        raise ValueError("Settings must be a small object.")
    return raw


class _ProjectScoped(APIView):
    permission_classes = [IsAuthenticated]

    def project(self, request, project_id) -> Project:
        return get_object_or_404(Project, id=project_id, owner=request.user)

    def deployment(self, request, project_id, deployment_id) -> AgentDeployment:
        return get_object_or_404(
            AgentDeployment, id=deployment_id, project=self.project(request, project_id)
        )


class AgentCatalogView(APIView):
    """GET /api/agents/catalog"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response([catalog_entry(spec) for spec in active_agents()])


class DeploymentListCreateView(_ProjectScoped):
    """GET|POST /api/projects/:pid/agents"""

    def get(self, request, project_id):
        project = self.project(request, project_id)
        return Response([deployment_data(d) for d in project.agent_deployments.all()])

    def post(self, request, project_id):
        project = self.project(request, project_id)
        agent_type = str(request.data.get("agentType", ""))
        if agent_type not in {spec.slug for spec in active_agents()}:
            return _bad("Unknown agent.")
        try:
            config = _parse_config(request.data.get("config"))
            limit = _parse_limit(request.data.get("monthlyCreditLimit"))
        except ValueError as exc:
            return _bad(str(exc))
        deployment = AgentDeployment.objects.create(
            project=project, user=request.user, agent_type=agent_type, config=config, monthly_credit_limit=limit
        )
        return Response(deployment_data(deployment), status=status.HTTP_201_CREATED)


class DeploymentDetailView(_ProjectScoped):
    """GET|PATCH|DELETE /api/projects/:pid/agents/:id"""

    def get(self, request, project_id, deployment_id):
        return Response(deployment_data(self.deployment(request, project_id, deployment_id)))

    def patch(self, request, project_id, deployment_id):
        deployment = self.deployment(request, project_id, deployment_id)
        data = request.data
        try:
            if "status" in data:
                if data["status"] not in ("active", "paused"):
                    raise ValueError("Status must be active or paused.")
                deployment.status = data["status"]
            if "config" in data:
                deployment.config = _parse_config(data["config"])
            if "monthlyCreditLimit" in data:
                deployment.monthly_credit_limit = _parse_limit(data["monthlyCreditLimit"])
            if "schedule" in data:
                deployment.schedule = clean_schedule(data["schedule"])
            if "topicQueue" in data:
                deployment.topic_queue = clean_topics(data["topicQueue"])
            if "autopilot" in data:
                deployment.autopilot = bool(data["autopilot"])
            if deployment.autopilot:
                spec = get_agent(deployment.agent_type)
                if not spec or spec.input_kind != "topic":
                    raise ValueError("Autopilot works with agents that take a topic.")
                if not deployment.schedule:
                    raise ValueError("Set the days and time first.")
                if not deployment.topic_queue and not str(deployment.config.get("niche") or "").strip():
                    raise ValueError("Add some topics, or set the channel niche so the agent can pick topics.")
        except ValueError as exc:
            return _bad(str(exc))
        # Any schedule change re-plans the next run from now.
        deployment.next_run_at = next_slot(deployment.schedule, timezone.now()) if deployment.autopilot else None
        if not deployment.autopilot:
            deployment.autopilot_note = ""
        deployment.save()
        return Response(deployment_data(deployment))

    def delete(self, request, project_id, deployment_id):
        deployment = self.deployment(request, project_id, deployment_id)
        if deployment.runs.filter(status__in=OPEN_STATUSES).exists():
            return _bad("Wait for running jobs to finish before removing this agent.", "AGENT_BUSY")
        deployment.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class RunListCreateView(_ProjectScoped):
    """GET|POST /api/projects/:pid/agents/:id/runs"""

    def get(self, request, project_id, deployment_id):
        deployment = self.deployment(request, project_id, deployment_id)
        runs = deployment.runs.select_related("deployment")[:50]
        return Response([run_data(r, request) for r in runs])

    def post(self, request, project_id, deployment_id):
        deployment = self.deployment(request, project_id, deployment_id)
        spec = get_agent(deployment.agent_type)
        if spec is None:
            return _bad("This agent is no longer available.")
        if spec.input_kind == "topic":
            value = " ".join(str(request.data.get("topic", "")).split())
            if len(value) > 200:
                return _bad("Enter a topic (up to 200 characters).")
            if not value and not (deployment.config or {}).get("niche"):
                return _bad("Enter a topic, or set a channel niche so the agent can pick one.")
            run_input = {"topic": value} if value else {"topic": "", "auto": True}
        else:
            value = str(request.data.get("text", "")).strip()
            if not value or len(value) > MAX_TEXT_INPUT:
                return _bad(f"Enter the text to speak (up to {MAX_TEXT_INPUT:,} characters).")
            run_input = {"text": value}
        try:
            run = start_run(deployment, run_input)
        except RunRefused as refused:
            if refused.code != "INSUFFICIENT_CREDITS":
                return _bad(refused.message, refused.code)
            request.user.refresh_from_db()
            return _bad(
                refused.message,
                refused.code,
                http=status.HTTP_402_PAYMENT_REQUIRED,
                creditsRemaining=request.user.credits_remaining,
                creditsTotal=request.user.credits_total,
                creditsRequired=serialize_decimal(refused.credits),
            )
        return Response(run_data(run, request), status=status.HTTP_201_CREATED)


class InboxView(_ProjectScoped):
    """GET /api/projects/:pid/agents/inbox — runs waiting for the user, and recent failures."""

    def get(self, request, project_id):
        project = self.project(request, project_id)
        since = timezone.now() - timedelta(days=7)
        runs = (
            AgentRun.objects.filter(project=project)
            .filter(Q(status="needs_review") | Q(status="failed", finished_at__gte=since))
            .select_related("deployment")
            .order_by("-updated_at")[:30]
        )
        items = []
        for run in runs:
            spec = get_agent(run.deployment.agent_type)
            items.append(
                {
                    "runId": str(run.id),
                    "deploymentId": str(run.deployment_id),
                    "agent": spec.name if spec else run.deployment.agent_type,
                    "status": run.status,
                    "step": run.step,
                    "title": (run.output or {}).get("title") or run.input.get("topic") or "Auto topic",
                    "error": run.error,
                    "updatedAt": run.updated_at,
                }
            )
        return Response({"waiting": sum(i["status"] == "needs_review" for i in items), "items": items})


class RunDetailView(_ProjectScoped):
    """GET /api/projects/:pid/agents/:id/runs/:rid"""

    def get(self, request, project_id, deployment_id, run_id):
        deployment = self.deployment(request, project_id, deployment_id)
        return Response(run_data(get_object_or_404(AgentRun, id=run_id, deployment=deployment), request))


class RunActionView(_ProjectScoped):
    """POST /api/projects/:pid/agents/:id/runs/:rid/(continue|regenerate|approve|discard)"""

    def post(self, request, project_id, deployment_id, run_id, action):
        deployment = self.deployment(request, project_id, deployment_id)
        run = get_object_or_404(AgentRun, id=run_id, deployment=deployment)
        handler = {
            "continue": self._continue,
            "regenerate": self._regenerate,
            "approve": self._approve,
            "discard": self._discard,
            "retry": self._retry,
        }.get(action)
        if handler is None:
            return _bad("Unknown action.")
        error = handler(run, request.data or {})
        if error is not None:
            return error
        return Response(run_data(run, request))

    @staticmethod
    def _resume(run):
        run.status = "queued"
        run.attempts = 0  # each checkpoint resume is a fresh start, not a retry
        run.save(update_fields=["status", "attempts", "output", "updated_at"])

    def _continue(self, run, data):
        if run.status != "needs_review" or run.step not in ("concept", "script", "storyboard"):
            return _bad("This run isn't waiting at a checkpoint.")
        out = run.output
        if run.step == "concept":
            concepts = out.get("concepts") or []
            try:
                chosen = dict(concepts[int(data.get("index", -1))])
            except (ValueError, TypeError, IndexError):
                return _bad("Pick one of the concepts.")
            for key, limit in (("title", 90), ("hook", 200), ("angle", 300)):
                if isinstance(data.get(key), str) and data[key].strip():
                    chosen[key] = data[key].strip()[:limit]
            if data.get("style") in STYLES:
                chosen["style"] = data["style"]
            if chosen.get("hook"):
                chosen.update(scored_hook(chosen["hook"]))  # the user may have rewritten it
            out["concept"] = chosen
        elif run.step == "script":
            if "scenes" in data:
                try:
                    out.update(clean_script(data, run.input.get("topic", "")))
                except RuntimeError as exc:
                    return _bad(str(exc))
            out["script_ok"] = True
        else:
            out["storyboard_ok"] = True
        self._resume(run)
        return None

    def _regenerate(self, run, data):
        if run.status != "needs_review" or run.step != "storyboard":
            return _bad("Scenes can be redone while reviewing the storyboard.")
        scenes = run.output.get("scenes") or []
        try:
            scene = scenes[int(data.get("scene", -1))]
        except (ValueError, TypeError, IndexError):
            return _bad("Unknown scene.")
        visual = "stock" if data.get("visual") == "stock" else "image"
        if visual == "image":
            prompt = " ".join(str(data.get("prompt") or scene.get("image_prompt", "")).split())[:600]
            if not prompt:
                return _bad("Describe the image you want.")
            scene["image_prompt"] = prompt
            cost = image_credits()
            if cost > 0:
                try:
                    topup = reserve_credits(run.user, cost)
                except InsufficientCredits:
                    return _bad("Not enough credits to redo this scene.", "INSUFFICIENT_CREDITS",
                                http=status.HTTP_402_PAYMENT_REQUIRED)
                run.credits_reserved += cost
                run.topup_reserved += topup
                run.save(update_fields=["credits_reserved", "topup_reserved", "updated_at"])
        else:
            query = " ".join(str(data.get("query") or scene.get("stock_query", "")).split())[:60]
            if not query:
                return _bad("Enter what the stock clip should show.")
            scene["stock_query"] = query
        scene.update({"visual": visual, "image": None, "clip": None, "credit": None})
        self._resume(run)
        return None

    def _approve(self, run, data):
        if run.status != "needs_review" or run.step not in ("final", ""):
            return _bad("Only a finished video waiting for review can be approved.")
        run.status = "approved"
        run.save(update_fields=["status", "updated_at"])
        return None

    def _retry(self, run, data):
        if run.status != "failed":
            return _bad("Only a failed run can be retried.")
        try:
            if not engine.retry(run):
                return _bad("This run was already retried.")
        except InsufficientCredits:
            return _bad("Not enough credits to retry this run.", "INSUFFICIENT_CREDITS",
                        http=status.HTTP_402_PAYMENT_REQUIRED)
        return None

    def _discard(self, run, data):
        if run.status not in ("needs_review", "succeeded"):
            return _bad("Only a run that is paused or finished can be discarded.")
        fields = ["status", "updated_at"]
        if run.status == "needs_review" and run.step in REFUNDABLE_GATES and run.credits_reserved > 0:
            refund_credits(run.user, run.credits_reserved, topup=run.topup_reserved)
            run.credits_reserved = Decimal("0")
            run.topup_reserved = Decimal("0")
            fields += ["credits_reserved", "topup_reserved"]
        run.status = "discarded"
        run.finished_at = timezone.now()
        fields.append("finished_at")
        if run.library_asset_id:
            run.library_asset.deleted_at = timezone.now()
            run.library_asset.save(update_fields=["deleted_at", "updated_at"])
        run.save(update_fields=fields)
        return None
