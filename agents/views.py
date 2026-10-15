"""Agents API: catalog, deployments per project, runs."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from agents import engine
from agents.models import AgentDeployment, AgentRun
from agents.runs import OPEN_STATUSES, RunRefused, clean_schedule, clean_topics, month_spend, next_slot, start_run
from agents.registry import (
    MAX_TEXT_INPUT, MAX_VIDEO_SECONDS, STYLES, active_agents, catalog_entry, get_agent, image_credits,
)
from agents.clips import caption_fixes, max_seconds, parse_youtube_url, youtube_info
from agents.cross_post import connected
from agents.hooks import lint_title
from agents.steps import clean_script, scored_hook
from agents.video_edit import asset_file, merge_cuts, probe
from content.models import LibraryAsset
from content.credits import InsufficientCredits, refund_credits, reserve_credits
from content.pricing import serialize_decimal
from content.storage_utils import absolute_media_url
from projects.models import Project
from projects.publish import PLATFORM_LABELS
from users.plans import get_plan

# Stopping at these checkpoints refunds the run: nothing expensive has been made yet.
REFUNDABLE_GATES = ("concept", "script", "post")
MAX_SCHEDULE_DAYS = 60


def _is_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


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


def _edit_data(out: dict, request) -> dict:
    """Video Editor fields."""
    info = out.get("source_info") or {}
    return {
        "sourceUrl": _media(out.get("source"), request),
        "sourceSeconds": info.get("duration"),
        "audioUrl": _media(out.get("audio"), request),
        "audioCleanUrl": _media(out.get("audio_clean"), request),
        "audioLevel": out.get("audio_level"),
        "audioLevelUsed": out.get("audio_level_used"),
        "audioFallback": bool(out.get("audio_fallback")),
        "transcript": out.get("captions") or out.get("words") or [],
        "captionFixes": out.get("caption_fixes", []),
        "cuts": out.get("cuts", []),
        "removedSeconds": out.get("removed_seconds"),
        "width": out.get("width"),
        "height": out.get("height"),
    }


def _post_data(out: dict) -> dict:
    """Cross-poster fields."""
    info = out.get("source_info") or {}
    return {
        "sourceUrl": out.get("asset_url"),
        "sourceSeconds": info.get("duration"),
        "short": out.get("short", False),
        "transcript": out.get("words") or [],
        "platforms": out.get("platforms", []),
        "chosen": out.get("chosen") or out.get("platforms", []),
        "posts": out.get("posts", {}),
        "postAt": out.get("post_at"),
        "posted": {p: {k: v for k, v in r.items() if k in ("status", "error", "externalId")}
                   for p, r in (out.get("posted") or {}).items()},
    }


def _clips_data(out: dict, request) -> dict:
    """Clip Maker fields."""
    return {
        "sourceUrl": None if out.get("source_deleted") else _media(out.get("clip_source"), request),
        "sourceSeconds": (out.get("clip_info") or {}).get("duration"),
        "sourceTitle": out.get("source_title", ""),
        "download": out.get("download"),
        "transcribedWith": out.get("transcribed_with", []),
        "moments": out.get("moments", []),
        "clips": [
            {**{k: c.get(k) for k in ("start", "end", "score", "title", "hook", "reason", "text", "duration",
                                     "checks", "error", "assetId")},
             "videoUrl": _media(c.get("video"), request), "thumbnailUrl": _media(c.get("thumbnail"), request)}
            for c in out.get("clips") or []
        ],
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
        "trends": out.get("trends", []),
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
        **(_edit_data(out, request) if "source" in out else {}),
        "log": out.get("log", {}),
        "music": out.get("music"),
        "videoUrl": _media(out.get("video"), request),
        "thumbnailUrl": _media(out.get("thumbnail"), request),
        "duration": out.get("duration"),
        "libraryAssetId": str(run.library_asset_id) if run.library_asset_id else None,
        "createdAt": run.created_at,
        "updatedAt": run.updated_at,
        "finishedAt": run.finished_at,
        **(_post_data(out) if "short" in out else {}),
        **(_clips_data(out, request) if "clip_source" in out or run.input.get("url") else {}),
        **({"thumbnailUrl": out["thumbnail_url"]} if out.get("thumbnail_url") else {}),
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
        if "get_video" in spec.steps:
            run_input = self._clip_input(request, deployment)
            if isinstance(run_input, Response):
                return run_input
        elif spec.input_kind == "video":
            run_input = self._video_input(request, deployment, spec)
            if isinstance(run_input, Response):
                return run_input
        elif spec.input_kind == "topic":
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

    @staticmethod
    def _video_input(request, deployment, spec):
        """{"assetId", "seconds"} for a video from this project's library, or an error response."""
        asset_id = request.data.get("assetId")
        asset = (
            LibraryAsset.objects.filter(id=asset_id, project=deployment.project, media_type="video").first()
            if _is_uuid(asset_id) else None
        )
        if asset is None:
            return _bad("Pick a video from your library.")
        seconds = None
        path = asset_file(asset)
        if path:
            try:
                seconds = probe(path)["duration"]
            except RuntimeError as exc:
                return _bad(str(exc))
            if "prepare" in spec.steps and seconds > MAX_VIDEO_SECONDS + 1:
                return _bad("The Video Editor takes videos up to 3 minutes.", "VIDEO_TOO_LONG")
        if "post" in spec.steps and not connected(deployment.project_id):
            return _bad("Connect YouTube, Instagram or Facebook on Social Accounts first.", "NOT_CONNECTED")
        return {"assetId": str(asset.id), "seconds": seconds, "title": asset.title[:120]}


    @classmethod
    def _clip_input(cls, request, deployment):
        """Clip Maker: a YouTube link (with the user's rights confirmation) or a library video."""
        limit = max_seconds(request.user)
        too_long = _bad(f"Your plan takes videos up to {limit // 60} minutes.", "VIDEO_TOO_LONG")
        if "url" not in request.data:
            run_input = cls._video_input(request, deployment, get_agent(deployment.agent_type))
            if not isinstance(run_input, Response) and (run_input["seconds"] or 0) > limit + 5:
                return too_long
            return run_input
        if request.data.get("rights") is not True:
            return _bad("Confirm that you own this video or have the rights to use it.", "RIGHTS_REQUIRED")
        url = parse_youtube_url(str(request.data.get("url") or ""))
        if url is None:
            return _bad("Paste a link to a single YouTube video.")
        try:
            info = youtube_info(url)
        except RuntimeError as exc:
            return _bad(str(exc), "VIDEO_UNAVAILABLE")
        if info["live"]:
            return _bad("Live streams can't be clipped until they have ended.")
        if info["duration"] > limit + 5:
            return too_long
        if info["duration"] < 10:
            return _bad("This video is too short to make clips from.")
        return {"url": url, "seconds": round(info["duration"]), "title": info["title"], "rights": True}


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
        if run.status != "needs_review" or run.step not in ("concept", "script", "storyboard", "edit", "post", "clips"):
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
        elif run.step == "edit":
            problem = self._apply_edit(out, data)
            if problem:
                return _bad(problem)
            out["edit_ok"] = True
        elif run.step == "post":
            problem = self._apply_post(run, out, data)
            if problem:
                return _bad(problem)
            out["post_ok"] = True
        elif run.step == "clips":
            problem = self._apply_clips(out, data)
            if problem:
                return _bad(problem)
            out["clips_ok"] = True
        else:
            out["storyboard_ok"] = True
        self._resume(run)
        return None

    @staticmethod
    def _apply_post(run, out: dict, data: dict) -> str | None:
        """The user's edits to the Cross-poster's posts, platforms and time."""
        chosen = [p for p in out.get("platforms", []) if p in (data.get("platforms") or [])]
        if not chosen:
            return "Pick at least one platform."
        edits = data.get("posts") if isinstance(data.get("posts"), dict) else {}
        for platform in chosen:
            post, edit = out["posts"][platform], edits.get(platform)
            edit = edit if isinstance(edit, dict) else {}
            if platform == "youtube":
                for key, limit in (("title", 100), ("description", 5000)):
                    if isinstance(edit.get(key), str):
                        post[key] = edit[key].strip()[:limit]
                if isinstance(edit.get("tags"), list):
                    post["tags"] = [str(t).strip().lstrip("#")[:60] for t in edit["tags"] if str(t).strip()][:15]
                if edit.get("privacy") in ("public", "unlisted", "private"):
                    post["privacy"] = edit["privacy"]
                if not post["title"]:
                    return "Give the YouTube video a title."
                out["title"] = post["title"]
                out["title_check"] = lint_title(post["title"], post.get("thumbnail_text", ""))
            else:
                if isinstance(edit.get("caption"), str):
                    post["caption"] = edit["caption"].strip()[:2200 if platform == "instagram" else 5000]
                if not post["caption"]:
                    return f"Write a caption for {PLATFORM_LABELS[platform]}."
        at = None
        if data.get("postAt"):
            at = parse_datetime(str(data["postAt"]))
            if at is None or timezone.is_naive(at):
                return "Pick a valid date and time."
            if at <= timezone.now():
                return "Pick a time in the future."
            if at > timezone.now() + timedelta(days=MAX_SCHEDULE_DAYS):
                return f"Pick a time within {MAX_SCHEDULE_DAYS} days."
            if not get_plan(run.user.plan).get("limits", {}).get("can_schedule_publishing"):
                return "Scheduled posting is not included in your plan. Post it now, or upgrade."
        out["chosen"] = chosen
        out["post_at"] = at.isoformat() if at else None
        return None

    @staticmethod
    def _apply_clips(out: dict, data: dict) -> str | None:
        """The user's pick of moments, with their trimmed edges and hook text."""
        moments = out.get("moments") or []
        duration = (out.get("clip_info") or {}).get("duration") or 0
        picks = data.get("clips")
        if not isinstance(picks, list) or len(picks) > len(moments):
            return "Invalid clip list."
        changed = [dict(m) for m in moments]
        for pick in picks:
            try:
                moment = changed[int(pick["index"])]
                start = float(pick.get("start", moment["start"]))
                end = float(pick.get("end", moment["end"]))
            except (KeyError, TypeError, ValueError, IndexError):
                return "Invalid clip list."
            if not 0 <= start < end <= duration + 0.01 or not 3 <= end - start <= 180:
                return "A clip must be 3 seconds to 3 minutes long and inside the video."
            moment.update({"start": round(start, 3), "end": round(end, 3), "keep": bool(pick.get("keep"))})
            for key, limit in (("hook", 80), ("title", 90)):
                if isinstance(pick.get(key), str):
                    moment[key] = " ".join(pick[key].split())[:limit]
            captions = pick.get("captions")
            if isinstance(captions, str) and moment.get("w"):
                if len(captions) > 5000 or not captions.strip():
                    return "Captions must be 1 to 5,000 characters."
                first, last = moment["w"]
                fixes = out.setdefault("caption_fixes", {})
                for key in [k for k in fixes if first <= int(k) <= last]:  # replace earlier edits of this clip
                    del fixes[key]
                fixes.update({str(i): w for i, w in caption_fixes(out.get("words") or [], first, last, captions).items()})
                moment["text"] = " ".join(captions.split())[:2000]
        if not any(m["keep"] for m in changed):
            return "Pick at least one clip."
        out["moments"] = changed
        return None

    @staticmethod
    def _apply_edit(out: dict, data: dict) -> str | None:
        """The user's cut list and caption corrections from the edit review."""
        duration = (out.get("source_info") or {}).get("duration") or 0
        if "cuts" in data:
            raw = data["cuts"]
            if not isinstance(raw, list) or len(raw) > 1000:
                return "Invalid cut list."
            cuts = []
            for c in raw:
                try:
                    start, end = float(c["start"]), float(c["end"])
                except (KeyError, TypeError, ValueError):
                    return "Invalid cut list."
                if not 0 <= start < end <= duration + 0.01:
                    return "A cut is outside the video."
                reasons = [r for r in c.get("reasons") or [] if r in ("pause", "filler", "retake", "black frames",
                                                                     "frozen frames", "manual")] or ["manual"]
                cuts.append({"start": start, "end": end, "reasons": reasons, "keep": bool(c.get("keep"))})
            removed = [c for c in cuts if not c["keep"]]
            kept = [c for c in cuts if c["keep"]]
            out["cuts"] = sorted(merge_cuts(removed, duration) + kept, key=lambda c: c["start"])
        captions = out.get("captions") or []
        for edit in data.get("captions") or []:
            try:
                index, word = int(edit["index"]), " ".join(str(edit["word"]).split())[:40]
            except (KeyError, TypeError, ValueError):
                return "Invalid caption edit."
            if not 0 <= index < len(captions) or not word:
                return "Invalid caption edit."
            captions[index]["word"] = word
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
        if run.status in ("queued", "running"):  # cancel: a scheduled post, or a job waiting or in progress
            if run.status == "running" and run.step == "post":
                return _bad("It is being posted right now, so it can't be cancelled.")
            credits, topup = run.credits_reserved, run.topup_reserved
            cancelled = AgentRun.objects.filter(id=run.id, status__in=("queued", "running")).exclude(
                status="running", step="post"
            ).update(status="discarded", error="Cancelled. Your credits were refunded.", finished_at=timezone.now(),
                     locked_until=None, credits_reserved=0, topup_reserved=0)
            if not cancelled:
                return _bad("It is being posted right now, so it can't be cancelled.")
            if credits > 0:
                refund_credits(run.user, credits, topup=topup)
            run.refresh_from_db()
            return None
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
