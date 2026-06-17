from typing import Any
from urllib.parse import urljoin

import httpx

from app.config import settings
from app.schemas import TextToImageRequest, normalize_style

IMAGE_CACHE: dict[str, dict[str, Any]] = {}


class FluxClientError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _absolute_url(path_or_url: str) -> str:
    return urljoin(f"{settings.dgx_flux_api_url}/", path_or_url.lstrip("/"))


async def _download_image(source_image_url: str) -> tuple[bytes, str]:
    async with httpx.AsyncClient(timeout=settings.dgx_request_timeout) as client:
        try:
            image_response = await client.get(source_image_url)
            image_response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise FluxClientError(
                f"DGX1 image download failed: {exc.response.text}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:
            raise FluxClientError(f"Could not download DGX1 image: {exc}") from exc

    mime_type = image_response.headers.get("content-type", "image/png")
    mime_type = mime_type.split(";")[0] or "image/png"
    return image_response.content, mime_type


async def _cache_image(job_id: str, source_image_url: str) -> dict[str, Any]:
    cached = IMAGE_CACHE.get(job_id)
    if cached and cached.get("content"):
        return cached

    content, mime_type = await _download_image(source_image_url)
    cached = {
        **(cached or {}),
        "source_image_url": source_image_url,
        "content": content,
        "mime_type": mime_type,
    }
    IMAGE_CACHE[job_id] = cached
    return cached


async def get_dgx_health() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=8) as client:
        response = await client.get(f"{settings.dgx_flux_api_url}/health")
        response.raise_for_status()
        return response.json()


async def start_text_to_image(payload: TextToImageRequest) -> dict[str, Any]:
    data: dict[str, str] = {
        "mode": "text2img",
        "prompt": payload.prompt.strip(),
        "style": normalize_style(payload.style),
        "aspect_ratio": payload.aspect_ratio,
        "resolution": payload.resolution,
    }
    if payload.seed is not None:
        data["seed"] = str(payload.seed)

    async with httpx.AsyncClient(timeout=settings.dgx_start_timeout) as client:
        try:
            create_response = await client.post(
                f"{settings.dgx_flux_api_url}/generate",
                data=data,
            )
            create_response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise FluxClientError(
                f"DGX1 rejected the generation request: {exc.response.text}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:
            raise FluxClientError(f"Could not reach DGX1 Flux API: {exc}") from exc

        create_data = create_response.json()
        job_id = create_data.get("job_id")
        if not job_id:
            raise FluxClientError("DGX1 Flux API did not return a job_id.")

        return {
            "job_id": job_id,
            "status": create_data.get("status", "queued"),
            "mode": create_data.get("mode", "text2img"),
        }


async def get_text_to_image_status(job_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            status_response = await client.get(f"{settings.dgx_flux_api_url}/status/{job_id}")
            status_response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise FluxClientError(
                f"DGX1 status check failed: {exc.response.text}",
                status_code=exc.response.status_code,
            ) from exc
        except httpx.RequestError as exc:
            raise FluxClientError(f"Could not poll DGX1 Flux API: {exc}") from exc

    status_data = status_response.json()
    response = {
        "job_id": job_id,
        "status": status_data.get("status"),
        "elapsed": status_data.get("elapsed"),
        "full_prompt": status_data.get("full_prompt"),
        "width": status_data.get("width"),
        "height": status_data.get("height"),
        "dgx_status": status_data,
    }

    if status_data.get("status") == "done":
        output_url = status_data.get("output_url")
        if not output_url:
            raise FluxClientError("DGX1 job finished without an output_url.")
        response["image_url"] = f"/api/images/text-to-image/{job_id}/file"
        response["source_image_url"] = _absolute_url(output_url)
        cached = IMAGE_CACHE.setdefault(job_id, {})
        cached.update(
            {
                "source_image_url": response["source_image_url"],
                "elapsed": response.get("elapsed"),
                "full_prompt": response.get("full_prompt"),
                "width": response.get("width"),
                "height": response.get("height"),
            }
        )
        await _cache_image(job_id, response["source_image_url"])

    if status_data.get("status") == "error":
        response["error"] = status_data.get("error", "unknown error")

    return response


async def fetch_text_to_image_file(job_id: str) -> tuple[bytes, str]:
    cached = IMAGE_CACHE.get(job_id)
    if cached and cached.get("content"):
        return cached["content"], cached.get("mime_type", "image/png")

    direct_source_url = _absolute_url(f"/output/ad_{job_id}.png")
    try:
        cached = await _cache_image(job_id, direct_source_url)
        return cached["content"], cached.get("mime_type", "image/png")
    except FluxClientError:
        status_data = await get_text_to_image_status(job_id)
        if status_data.get("status") != "done":
            raise FluxClientError("Image is not ready yet.", status_code=409)

        source_image_url = status_data.get("source_image_url")
        if not source_image_url:
            raise FluxClientError("DGX1 job finished without an output image.")

        cached = await _cache_image(job_id, source_image_url)
        return cached["content"], cached.get("mime_type", "image/png")
