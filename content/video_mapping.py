"""Map camelCase FE video payloads to fal snake_case inputs per model profile."""

from __future__ import annotations

from content.video_catalog import get_model_entry


def build_video_fal_input(capability: str, model: str, data: dict) -> dict:
    """Build fal `arguments` from a validated create-video-job payload."""
    entry = get_model_entry(capability, model) or {}
    fields = entry.get("fields") or {}
    keys = entry.get("falImageKeys") or {}
    out: dict = {}

    prompt = (data.get("prompt") or "").strip()
    if prompt:
        out["prompt"] = prompt

    start_url = data.get("startImageUrl") or ""
    end_url = data.get("endImageUrl") or ""
    # Back-compat: imageUrls[0]/start, imageUrls[1]/end
    urls = data.get("imageUrls") or []
    if not start_url and urls:
        start_url = urls[0]
    if not end_url and len(urls) > 1:
        end_url = urls[1]

    start_key = keys.get("start")
    end_key = keys.get("end")
    if start_key and start_url:
        out[start_key] = start_url
    if end_key and end_url:
        out[end_key] = end_url

    if "duration" in fields and data.get("duration"):
        out["duration"] = data["duration"]
    if "aspectRatio" in fields and data.get("aspectRatio"):
        out["aspect_ratio"] = data["aspectRatio"]
    if "resolution" in fields and data.get("resolution"):
        out["resolution"] = data["resolution"]
    if fields.get("generateAudio") and data.get("generateAudio") is not None:
        out["generate_audio"] = bool(data["generateAudio"])
    if fields.get("negativePrompt") and data.get("negativePrompt"):
        out["negative_prompt"] = data["negativePrompt"]
    if fields.get("seed") and data.get("seed") is not None:
        out["seed"] = data["seed"]

    return out
