"""What a user's plan lets them use: agents, scheduled agents, video models and quality, Clip Maker length.

Each check returns None when allowed, or a PlanRequired naming the cheapest public plan that allows it, so
the API can answer 403 {"code": "PLAN_REQUIRED", "requiredPlan": id, "message": ...} and the app can offer
the upgrade. Limits come from users.plans (the admin-editable PlanDefinition rows).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from users.plans import PLAN_TIERS, get_plan, get_public_plan_ids

# Output quality, lowest first. MiniMax's 768P counts as 720p; 2K/1440p sit between 1080p and 4K.
RESOLUTION_RANK = {"360p": 0, "480p": 1, "540p": 1, "720p": 2, "768p": 2, "1k": 2,
                   "1080p": 3, "2k": 4, "1440p": 4, "4k": 5, "2160p": 5}
IMAGE_2K_PIXELS = 2048 * 2048

# Video models by plan tier (see users.plans): 1 = fast models every plan has; 2 = Basic; 3 = Plus.
# A model missing here is tier 3, so a newly added model is never given away by accident.
VIDEO_MODEL_TIERS = {
    "fal-ai/minimax/hailuo-02/standard/text-to-video": 1,
    "fal-ai/minimax/hailuo-02/standard/image-to-video": 1,
    "wan/v2.6/text-to-video": 1,
    "wan/v2.6/image-to-video": 1,
    "fal-ai/kling-video/v2.5-turbo/pro/text-to-video": 1,
    "fal-ai/kling-video/v2.5-turbo/pro/image-to-video": 1,
    "fal-ai/pixverse/v5/text-to-video": 1,
    "fal-ai/pixverse/v5/image-to-video": 1,
    "fal-ai/pixverse/v6/text-to-video": 1,
    "fal-ai/pixverse/v6/image-to-video": 1,
    "fal-ai/ltx-video-13b-distilled": 1,
    "minimax/h3-max-turbo/text-to-video": 1,
    "minimax/h3-max-turbo/image-to-video": 1,
    "bytedance/seedance-2.0/mini/text-to-video": 1,
    "xai/grok-imagine-video/text-to-video": 1,
    "xai/grok-imagine-video/image-to-video": 1,
    "google/gemini-omni-flash/v1.1/text-to-video": 1,
    "google/gemini-omni-flash/v1.1/image-to-video": 1,
    "fal-ai/veo3.1/fast": 2,
    "fal-ai/veo3.1/fast/image-to-video": 2,
    "fal-ai/veo3.1/fast/first-last-frame-to-video": 2,
    "fal-ai/kling-video/v3/standard/text-to-video": 2,
    "fal-ai/kling-video/v3/standard/image-to-video": 2,
    "bytedance/seedance-2.0/text-to-video": 2,
    "bytedance/seedance-2.0/image-to-video": 2,
    "bytedance/seedance-2.0/fast/text-to-video": 2,
    "bytedance/seedance-2.0/fast/image-to-video": 2,
    "minimax/h3/text-to-video": 2,
    "minimax/h3/image-to-video": 2,
    "minimax/h3-max/text-to-video": 2,
    "minimax/h3-max/image-to-video": 2,
    "alibaba/wan-3.0/text-to-video": 2,
    "alibaba/wan-3.0/image-to-video": 2,
    "fal-ai/kling-video/v2.6/pro/text-to-video": 2,
    "fal-ai/kling-video/v2.6/pro/image-to-video": 2,
}


@dataclass
class PlanRequired:
    feature: str  # as it reads mid-sentence: "scheduled agents", "Clip Maker", "this video model"
    plan_id: str | None  # the cheapest public plan that allows it; None: no plan does
    plan_name: str = ""

    @property
    def message(self) -> str:
        if self.plan_id is None:
            return f"No plan includes {self.feature}."
        return f"Your plan doesn't include {self.feature}. Upgrade to {self.plan_name} to use it."

    @property
    def short(self) -> str:
        """For notes: "your plan doesn't include scheduled agents (upgrade to Basic)"."""
        upgrade = f" (upgrade to {self.plan_name})" if self.plan_id else ""
        return f"your plan doesn't include {self.feature}{upgrade}"

    def response_data(self) -> dict:
        return {"message": self.message, "code": "PLAN_REQUIRED", "requiredPlan": self.plan_id}


def limits(plan_id: str | None) -> dict[str, Any]:
    """The plan's limits; any limit an (admin-made) plan lacks takes Starter's value."""
    return {**PLAN_TIERS["free"]["limits"], **(get_plan(plan_id).get("limits") or {})}


def _needed(feature: str, allows: Callable[[dict], bool]) -> PlanRequired:
    for plan_id in get_public_plan_ids():
        if allows(limits(plan_id)):
            return PlanRequired(feature, plan_id, get_plan(plan_id)["name"])
    return PlanRequired(feature, None)


def _check(user, feature: str, allows: Callable[[dict], bool]) -> PlanRequired | None:
    return None if allows(limits(user.plan)) else _needed(feature, allows)


def required_plan(problem: PlanRequired | None) -> dict | None:
    """{"id", "name"} of the plan that unlocks it, for catalog entries; None when allowed."""
    if problem is None or problem.plan_id is None:
        return None
    return {"id": problem.plan_id, "name": get_plan(problem.plan_id)["name"]}


# ── agents ─────────────────────────────────────────────────────────────────


def agent_problem(user, agent_type: str, agent_name: str = "this agent") -> PlanRequired | None:
    """Plans list Admart's built-in agents; agents the owner builds in the admin are on every plan."""
    from agents.registry import BUILTIN_AGENTS

    if agent_type not in BUILTIN_AGENTS:
        return None
    return _check(user, agent_name, lambda lim: agent_type in (lim.get("agents") or []))


def runs_per_week(schedule: dict | None) -> float:
    from agents.runs import schedule_mode

    mode = schedule_mode(schedule)
    if mode == "daily":
        return 7
    if mode == "weekly":
        return len((schedule or {}).get("days") or [])
    return 0.25 if mode == "monthly" else 0


def schedule_problem(user, deployment, earlier_only: bool = False) -> PlanRequired | None:
    """Whether this agent may run on its schedule: the plan's number of scheduled agents and runs per week.

    ``earlier_only`` (at run time) counts only agents scheduled before this one, so after a downgrade the
    oldest schedules keep running and the newer ones are skipped.
    """
    from agents.models import AgentDeployment
    from agents.runs import schedule_mode

    if schedule_mode(deployment.schedule) == "manual":
        return None
    others = AgentDeployment.objects.filter(user=user, autopilot=True).exclude(id=deployment.id)
    if earlier_only:
        others = others.filter(created_at__lt=deployment.created_at)
    count = sum(schedule_mode(d.schedule) != "manual" for d in others) + 1
    feature = "scheduled agents" if count == 1 else f"{count} scheduled agents"
    problem = _check(user, feature, lambda lim: lim.get("max_scheduled_agents", 0) >= count)
    if problem:
        return problem
    per_week = runs_per_week(deployment.schedule)
    return _check(user, "running an agent more than once a week",
                  lambda lim: lim.get("max_runs_per_week", 0) >= per_week)


def clip_max_seconds(user) -> int:
    return int(limits(user.plan).get("clip_max_minutes", 0)) * 60


def has_priority(user) -> bool:
    return bool(limits(user.plan).get("has_priority_queue"))


# ── generation ─────────────────────────────────────────────────────────────


def _rank(value) -> int:
    return RESOLUTION_RANK.get(str(value or "").lower(), 0)


def video_model_problem(user, model: str) -> PlanRequired | None:
    tier = VIDEO_MODEL_TIERS.get(model, 3)
    return _check(user, "this video model", lambda lim: lim.get("video_model_tier", 1) >= tier)


def video_problem(user, capability: str, model: str, data: dict) -> PlanRequired | None:
    problem = video_model_problem(user, model)
    if problem:
        return problem
    from content.fal_price_tables import VIDEO_OPTION_RATES
    from content.video_catalog import get_model_entry

    if "resolution" not in ((get_model_entry(capability, model) or {}).get("fields") or {}):
        return None  # one fixed output size: the model tier already covers it
    resolution = data.get("resolution") or (VIDEO_OPTION_RATES.get(model) or {}).get("default") or "720p"
    label = f"{str(resolution).upper() if str(resolution).lower() in ('2k', '4k') else resolution} video"
    return _check(user, label, lambda lim: _rank(lim.get("video_max_resolution", "720p")) >= _rank(resolution))


def _image_rank(data: dict) -> int:
    size = data.get("imageSize")
    if isinstance(size, dict):
        try:
            if int(size.get("width") or 0) * int(size.get("height") or 0) > IMAGE_2K_PIXELS:
                return RESOLUTION_RANK["4k"]
        except (TypeError, ValueError):
            pass
    return _rank(data.get("resolution")) if str(data.get("resolution") or "").lower() == "4k" else 0


def image_problem(user, data: dict) -> PlanRequired | None:
    rank = _image_rank(data)
    return _check(user, "4K images", lambda lim: _rank(lim.get("image_max_resolution", "2k")) >= rank) if rank else None


def plan_summary(user) -> dict:
    lim = limits(user.plan)
    return {"plan": user.plan, "videoMaxResolution": lim.get("video_max_resolution", "720p"),
            "imageMaxResolution": lim.get("image_max_resolution", "2k")}
