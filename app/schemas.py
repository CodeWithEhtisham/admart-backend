from typing import Any, Literal

from pydantic import BaseModel, Field


Resolution = Literal["480", "720", "1080"]
AspectRatio = Literal["1:1", "16:9", "9:16", "4:5"]

STYLE_ALIASES = {
    "cinematic": "luxury",
    "minimal": "minimalist",
    "dynamic": "bold",
    "corporate": "tech",
    "artistic": "lifestyle",
    "custom": "luxury",
    "luxury": "luxury",
    "minimalist": "minimalist",
    "lifestyle": "lifestyle",
    "tech": "tech",
    "nature": "nature",
    "bold": "bold",
}


def normalize_style(style: str) -> str:
    return STYLE_ALIASES.get(style.strip().lower(), "luxury")


class TextToImageRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    style: str = Field(default="Cinematic", max_length=80)
    aspect_ratio: AspectRatio = "1:1"
    resolution: Resolution = "720"
    seed: int | None = Field(default=None, ge=0)


class TextToImageJobResponse(BaseModel):
    job_id: str
    status: str
    mode: str = "text2img"


class TextToImageStatusResponse(BaseModel):
    job_id: str
    status: str
    image_url: str | None = None
    source_image_url: str | None = None
    image_base64: str | None = None
    mime_type: str | None = "image/png"
    elapsed: float | None = None
    full_prompt: str | None = None
    width: int | None = None
    height: int | None = None
    error: str | None = None
    dgx_status: dict[str, Any] | None = None
