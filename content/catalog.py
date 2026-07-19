"""Model allow-lists, defaults, and credit costs for image capabilities."""

from decimal import Decimal

CAPABILITIES = (
    "textToImage",
    "edit",
    "multiEdit",
    "upscale",
    "removeBackground",
)

DEFAULT_MODELS = {
    "textToImage": "fal-ai/flux/dev",
    "edit": "fal-ai/nano-banana-2/edit",
    "multiEdit": "fal-ai/nano-banana-pro/edit",
    "upscale": "fal-ai/esrgan",
    "removeBackground": "fal-ai/birefnet",
}

MODEL_CATALOG = {
    "textToImage": [
        {"id": "fal-ai/flux/dev", "label": "Flux Dev", "family": "flux", "default": True},
        {"id": "fal-ai/flux/schnell", "label": "Flux Schnell", "family": "flux", "default": False},
        {"id": "fal-ai/nano-banana-2", "label": "Nano Banana 2", "family": "nano", "default": False},
        {"id": "fal-ai/nano-banana-pro", "label": "Nano Banana Pro", "family": "nano", "default": False},
        {"id": "fal-ai/ideogram/v3", "label": "Ideogram V3", "family": "ideogram", "default": False},
        {
            "id": "openai/gpt-image-2",
            "label": "GPT Image 2",
            "family": "openai",
            "default": False,
        },
    ],
    "edit": [
        {
            "id": "fal-ai/nano-banana-2/edit",
            "label": "Nano Banana 2 Edit",
            "family": "nano",
            "default": True,
        },
        {
            "id": "fal-ai/nano-banana-pro/edit",
            "label": "Nano Banana Pro Edit",
            "family": "nano",
            "default": False,
        },
        {
            "id": "fal-ai/flux-pro/kontext",
            "label": "Flux Kontext Pro",
            "family": "flux",
            "default": False,
        },
        {
            "id": "openai/gpt-image-2/edit",
            "label": "GPT Image 2 Edit",
            "family": "openai",
            "default": False,
        },
    ],
    "multiEdit": [
        {
            "id": "fal-ai/nano-banana-pro/edit",
            "label": "Nano Banana Pro Edit",
            "family": "nano",
            "default": True,
        },
        {
            "id": "fal-ai/nano-banana-2/edit",
            "label": "Nano Banana 2 Edit",
            "family": "nano",
            "default": False,
        },
        {
            "id": "openai/gpt-image-2/edit",
            "label": "GPT Image 2 Edit",
            "family": "openai",
            "default": False,
        },
    ],
    "upscale": [
        {"id": "fal-ai/esrgan", "label": "ESRGAN", "family": "upscale", "default": True},
        {
            "id": "fal-ai/seedvr/upscale/image",
            "label": "SeedVR2",
            "family": "upscale",
            "default": False,
        },
        {
            "id": "fal-ai/topaz/upscale/image",
            "label": "Topaz",
            "family": "upscale",
            "default": False,
        },
        {
            "id": "fal-ai/recraft/upscale/crisp",
            "label": "Recraft Crisp",
            "family": "upscale",
            "default": False,
        },
        {
            "id": "fal-ai/ideogram/upscale",
            "label": "Ideogram Upscale",
            "family": "upscale",
            "default": False,
        },
    ],
    "removeBackground": [
        {"id": "fal-ai/birefnet", "label": "BiRefNet", "family": "rembg", "default": True},
        {
            "id": "fal-ai/bria/background/remove",
            "label": "Bria RMBG 2.0",
            "family": "rembg",
            "default": False,
        },
    ],
}

ALLOW_LISTS = {
    capability: {entry["id"] for entry in models}
    for capability, models in MODEL_CATALOG.items()
}

# Placeholder product pricing — integers on User.credits_remaining.
CREDIT_COSTS = {
    "textToImage": Decimal("1"),
    "edit": Decimal("1"),
    "multiEdit": Decimal("2"),
    "upscale": Decimal("1"),
    "removeBackground": Decimal("1"),  # whole credits; fractional later if needed
}

ASPECT_TO_FLUX_SIZE = {
    "1:1": "square_hd",
    "16:9": "landscape_16_9",
    "9:16": "portrait_16_9",
    "4:3": "landscape_4_3",
    "3:4": "portrait_4_3",
}

FLUX_MODELS = {
    "fal-ai/flux/dev",
    "fal-ai/flux/schnell",
    "fal-ai/flux-pro/kontext",
    "fal-ai/flux-pro/v1.1",
    "fal-ai/flux-pro/v1.1-ultra",
}

NANO_MODELS = {
    "fal-ai/nano-banana-2",
    "fal-ai/nano-banana-pro",
    "fal-ai/nano-banana-2/edit",
    "fal-ai/nano-banana-pro/edit",
}

# Partner OpenAI models on fal (ids are `openai/…`, not `fal-ai/openai/…`).
OPENAI_MODELS = {
    "openai/gpt-image-2",
    "openai/gpt-image-2/edit",
}

SINGULAR_IMAGE_URL_MODELS = {
    "fal-ai/esrgan",
    "fal-ai/seedvr/upscale/image",
    "fal-ai/topaz/upscale/image",
    "fal-ai/recraft/upscale/crisp",
    "fal-ai/ideogram/upscale",
    "fal-ai/birefnet",
    "fal-ai/bria/background/remove",
    "fal-ai/flux-pro/kontext",
}

REMBG_MODEL_MAP = {
    "light": "General Use (Light)",
    "heavy": "General Use (Heavy)",
    "portrait": "Portrait",
}


def resolve_model(capability: str, model: str | None) -> str:
    chosen = (model or "").strip() or DEFAULT_MODELS[capability]
    if chosen not in ALLOW_LISTS[capability]:
        raise ValueError(f"Model not allowed for {capability}: {chosen}")
    return chosen


def credit_cost(capability: str, num_images: int = 1) -> Decimal:
    base = CREDIT_COSTS[capability]
    if capability == "textToImage":
        return base * max(1, num_images)
    return base
