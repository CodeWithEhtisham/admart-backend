"""Curated fal.ai video model catalog with per-model field profiles."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

VIDEO_CAPABILITIES = (
    "textToVideo",
    "imageToVideo",
    "firstLastFrame",
)

# inputs: text | image | firstLast
# falImageKeys: which fal args receive start/end frame URLs


def _m(
    *,
    id: str,
    label: str,
    family: str,
    inputs: str,
    default: bool = False,
    fal_image_keys: dict[str, str] | None = None,
    duration: list[str] | None = None,
    aspect_ratio: list[str] | None = None,
    resolution: list[str] | None = None,
    generate_audio: bool = False,
    negative_prompt: bool = False,
    seed: bool = True,
    strength: str = "",
) -> dict[str, Any]:
    fields: dict[str, Any] = {"seed": seed}
    if duration is not None:
        fields["duration"] = duration
    if aspect_ratio is not None:
        fields["aspectRatio"] = aspect_ratio
    if resolution is not None:
        fields["resolution"] = resolution
    if generate_audio:
        fields["generateAudio"] = True
    if negative_prompt:
        fields["negativePrompt"] = True
    entry: dict[str, Any] = {
        "id": id,
        "label": label,
        "family": family,
        "default": default,
        "inputs": inputs,
        "falImageKeys": fal_image_keys or {},
        "fields": fields,
    }
    if strength:
        entry["strength"] = strength
    return entry


VIDEO_MODEL_CATALOG: dict[str, list[dict[str, Any]]] = {
    "textToVideo": [
        _m(
            id="fal-ai/veo3.1",
            label="Veo 3.1",
            family="veo",
            inputs="text",
            default=True,
            duration=["4s", "6s", "8s"],
            aspect_ratio=["16:9", "9:16"],
            resolution=["720p", "1080p", "4k"],
            generate_audio=True,
            negative_prompt=True,
            strength="Cinematic + native audio",
        ),
        _m(
            id="bytedance/seedance-2.0/text-to-video",
            label="Seedance 2.0",
            family="seedance",
            inputs="text",
            duration=["auto", "4", "5", "6", "7", "8", "10", "12", "15"],
            aspect_ratio=["auto", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
            resolution=["480p", "720p", "1080p", "4k"],
            generate_audio=True,
            strength="Multi-shot cinematic",
        ),
        _m(
            id="fal-ai/kling-video/v2.5-turbo/pro/text-to-video",
            label="Kling 2.5 Turbo Pro",
            family="kling",
            inputs="text",
            duration=["5", "10"],
            aspect_ratio=["16:9", "9:16", "1:1"],
            strength="Fast motion quality",
        ),
        _m(
            id="fal-ai/kling-video/v2.1/master/text-to-video",
            label="Kling 2.1 Master",
            family="kling",
            inputs="text",
            duration=["5", "10"],
            aspect_ratio=["16:9", "9:16", "1:1"],
            strength="High fidelity",
        ),
        _m(
            id="fal-ai/minimax/hailuo-02/standard/text-to-video",
            label="Hailuo 02 Standard",
            family="minimax",
            inputs="text",
            duration=["6", "10"],
            strength="Social short clips",
        ),
        _m(
            id="wan/v2.6/text-to-video",
            label="Wan 2.6",
            family="wan",
            inputs="text",
            duration=["5", "10"],
            aspect_ratio=["16:9", "9:16", "1:1"],
            resolution=["720p", "1080p"],
            negative_prompt=True,
            strength="Coherent scenes",
        ),
        _m(
            id="fal-ai/pixverse/v5/text-to-video",
            label="PixVerse V5",
            family="pixverse",
            inputs="text",
            duration=["5", "8"],
            aspect_ratio=["16:9", "9:16", "1:1"],
            strength="Stylized clips",
        ),
        _m(
            id="fal-ai/ltx-video-13b-distilled",
            label="LTX Video 13B",
            family="ltx",
            inputs="text",
            aspect_ratio=["16:9", "9:16", "1:1"],
            strength="Fast / low cost",
        ),
    ],
    "imageToVideo": [
        _m(
            id="fal-ai/veo3.1/image-to-video",
            label="Veo 3.1",
            family="veo",
            inputs="image",
            default=True,
            fal_image_keys={"start": "image_url"},
            duration=["4s", "6s", "8s"],
            aspect_ratio=["auto", "16:9", "9:16"],
            resolution=["720p", "1080p", "4k"],
            generate_audio=True,
            strength="Animate one frame",
        ),
        _m(
            id="bytedance/seedance-2.0/image-to-video",
            label="Seedance 2.0",
            family="seedance",
            inputs="image",
            fal_image_keys={"start": "image_url"},
            duration=["auto", "4", "5", "6", "8", "10", "12", "15"],
            aspect_ratio=["auto", "16:9", "9:16", "1:1"],
            resolution=["480p", "720p", "1080p"],
            generate_audio=True,
            strength="Image + motion",
        ),
        _m(
            id="fal-ai/kling-video/v2.5-turbo/pro/image-to-video",
            label="Kling 2.5 Turbo Pro",
            family="kling",
            inputs="image",
            fal_image_keys={"start": "image_url"},
            duration=["5", "10"],
            strength="Smooth motion",
        ),
        _m(
            id="fal-ai/kling-video/v2.1/master/image-to-video",
            label="Kling 2.1 Master",
            family="kling",
            inputs="image",
            fal_image_keys={"start": "image_url"},
            duration=["5", "10"],
            strength="High fidelity I2V",
        ),
        _m(
            id="fal-ai/minimax/hailuo-02/standard/image-to-video",
            label="Hailuo 02 Standard",
            family="minimax",
            inputs="image",
            fal_image_keys={"start": "image_url"},
            duration=["6", "10"],
            strength="Product / social",
        ),
        _m(
            id="wan/v2.6/image-to-video",
            label="Wan 2.6",
            family="wan",
            inputs="image",
            fal_image_keys={"start": "image_url"},
            duration=["5", "10", "15"],
            resolution=["720p", "1080p"],
            negative_prompt=True,
            strength="Coherent I2V",
        ),
        _m(
            id="fal-ai/pixverse/v5/image-to-video",
            label="PixVerse V5",
            family="pixverse",
            inputs="image",
            fal_image_keys={"start": "image_url"},
            duration=["5", "8"],
            strength="Stylized motion",
        ),
    ],
    "firstLastFrame": [
        _m(
            id="fal-ai/veo3.1/first-last-frame-to-video",
            label="Veo 3.1 First→Last",
            family="veo",
            inputs="firstLast",
            default=True,
            fal_image_keys={"start": "first_frame_url", "end": "last_frame_url"},
            duration=["4s", "6s", "8s"],
            aspect_ratio=["auto", "16:9", "9:16"],
            resolution=["720p", "1080p", "4k"],
            generate_audio=True,
            strength="Start + end frames",
        ),
        _m(
            id="fal-ai/veo3.1/fast/first-last-frame-to-video",
            label="Veo 3.1 Fast First→Last",
            family="veo",
            inputs="firstLast",
            fal_image_keys={"start": "first_frame_url", "end": "last_frame_url"},
            duration=["4s", "6s", "8s"],
            aspect_ratio=["auto", "16:9", "9:16"],
            resolution=["720p", "1080p"],
            generate_audio=True,
            strength="Faster transition",
        ),
        _m(
            id="bytedance/seedance-2.0/image-to-video",
            label="Seedance 2.0 Start→End",
            family="seedance",
            inputs="firstLast",
            fal_image_keys={"start": "image_url", "end": "end_image_url"},
            duration=["auto", "4", "5", "6", "8", "10"],
            aspect_ratio=["auto", "16:9", "9:16", "1:1"],
            resolution=["480p", "720p", "1080p"],
            generate_audio=True,
            strength="Start + optional end",
        ),
        _m(
            id="fal-ai/kling-video/v2.5-turbo/pro/image-to-video",
            label="Kling 2.5 Turbo Start→End",
            family="kling",
            inputs="firstLast",
            fal_image_keys={"start": "image_url", "end": "tail_image_url"},
            duration=["5", "10"],
            strength="Start + end (tail)",
        ),
    ],
}

DEFAULT_VIDEO_MODELS = {
    cap: next(m["id"] for m in models if m.get("default"))
    if any(m.get("default") for m in models)
    else models[0]["id"]
    for cap, models in VIDEO_MODEL_CATALOG.items()
}

VIDEO_ALLOW_LISTS = {
    cap: {m["id"] for m in models} for cap, models in VIDEO_MODEL_CATALOG.items()
}

VIDEO_CREDIT_COSTS = {
    "textToVideo": Decimal("5"),
    "imageToVideo": Decimal("5"),
    "firstLastFrame": Decimal("6"),
}

# Lookup id → entry (first match if same id appears in multiple caps)
_MODEL_BY_ID: dict[str, dict[str, Any]] = {}
for _cap, _models in VIDEO_MODEL_CATALOG.items():
    for _m_entry in _models:
        _MODEL_BY_ID.setdefault(_m_entry["id"], {**_m_entry, "capability": _cap})


def get_model_entry(capability: str, model_id: str) -> dict[str, Any] | None:
    for entry in VIDEO_MODEL_CATALOG.get(capability, []):
        if entry["id"] == model_id:
            return entry
    return None


def resolve_video_model(capability: str, model: str | None) -> str:
    chosen = (model or "").strip() or DEFAULT_VIDEO_MODELS[capability]
    if chosen not in VIDEO_ALLOW_LISTS[capability]:
        raise ValueError(f"Model not allowed for {capability}: {chosen}")
    return chosen


def video_credit_cost(capability: str) -> Decimal:
    return VIDEO_CREDIT_COSTS[capability]
