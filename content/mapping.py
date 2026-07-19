"""Map camelCase FE payloads to fal snake_case inputs."""

from __future__ import annotations

from content.catalog import (
    ASPECT_TO_FLUX_SIZE,
    FLUX_MODELS,
    NANO_MODELS,
    OPENAI_MODELS,
    REMBG_MODEL_MAP,
)


def build_fal_input(capability: str, model: str, data: dict) -> dict:
    """Build fal `arguments` dict from a validated create-job payload."""
    out: dict = {}
    image_urls = data.get("imageUrls") or []

    if capability in ("textToImage", "edit", "multiEdit"):
        prompt = (data.get("prompt") or "").strip()
        if prompt:
            out["prompt"] = prompt

    if capability in ("edit", "multiEdit") and image_urls:
        if model.startswith("fal-ai/flux-pro/kontext"):
            out["image_url"] = image_urls[0]
        else:
            # Nano Banana edit + GPT Image 2 edit use image_urls[]
            out["image_urls"] = image_urls
    elif capability in ("upscale", "removeBackground") and image_urls:
        out["image_url"] = image_urls[0]

    # Size controls
    if model in FLUX_MODELS or model.startswith("fal-ai/ideogram") or model in OPENAI_MODELS:
        if data.get("imageSize") is not None:
            out["image_size"] = data["imageSize"]
        else:
            aspect = data.get("aspectRatio")
            if aspect == "auto" and model in OPENAI_MODELS:
                out["image_size"] = "auto"
            elif aspect and aspect in ASPECT_TO_FLUX_SIZE:
                out["image_size"] = ASPECT_TO_FLUX_SIZE[aspect]
    elif model in NANO_MODELS:
        if data.get("aspectRatio"):
            out["aspect_ratio"] = data["aspectRatio"]
        if data.get("resolution"):
            out["resolution"] = data["resolution"]

    _maybe(out, "num_images", data.get("numImages"))
    _maybe(out, "seed", data.get("seed"))
    _maybe(out, "output_format", data.get("outputFormat"))
    _maybe(out, "negative_prompt", data.get("negativePrompt"))
    _maybe(out, "num_inference_steps", data.get("numInferenceSteps"))
    _maybe(out, "guidance_scale", data.get("guidanceScale"))
    _maybe(out, "acceleration", data.get("acceleration"))
    _maybe(out, "system_prompt", data.get("systemPrompt"))
    _maybe(out, "enable_web_search", data.get("enableWebSearch"))
    _maybe(out, "thinking_level", data.get("thinkingLevel"))
    _maybe(out, "expand_prompt", data.get("expandPrompt"))
    _maybe(out, "rendering_speed", data.get("renderingSpeed"))
    _maybe(out, "style", data.get("style"))
    _maybe(out, "style_preset", data.get("stylePreset"))
    # GPT Image quality: auto | low | medium | high
    _maybe(out, "quality", data.get("quality"))
    _maybe(out, "mask_url", data.get("maskUrl"))

    if data.get("enableSafetyChecker") is not None:
        out["enable_safety_checker"] = data["enableSafetyChecker"]
    elif model in FLUX_MODELS and capability == "textToImage":
        out["enable_safety_checker"] = True

    if capability == "upscale":
        _maybe(out, "scale", data.get("scale"))
        if data.get("faceEnhance") is not None:
            out["face"] = data["faceEnhance"]
        if data.get("upscaleModel"):
            out["model"] = data["upscaleModel"]

    if capability == "removeBackground" and model == "fal-ai/birefnet":
        rembg = data.get("rembgModel")
        if rembg in REMBG_MODEL_MAP:
            out["model"] = REMBG_MODEL_MAP[rembg]
        _maybe(out, "operating_resolution", data.get("operatingResolution"))
        _maybe(out, "output_mask", data.get("outputMask"))
        _maybe(out, "refine_foreground", data.get("refineForeground"))
        if "output_format" not in out:
            out["output_format"] = data.get("outputFormat") or "png"

    return {k: v for k, v in out.items() if v is not None}


def _maybe(out: dict, key: str, value) -> None:
    if value is not None and value != "":
        out[key] = value
