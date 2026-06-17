"""
Admart DGX1 FLUX text-to-image API.

Copy this file to the DGX1 server that has your FLUX model and run it there:

    pip install fastapi uvicorn diffusers transformers accelerate torch pillow python-multipart
    export FLUX_MODEL_PATH=/mnt/Storage/carl/models/flux1-schnell
    export CUDA_VISIBLE_DEVICES=4,5,6,7
    python dgx_flux_text2image_server.py

The local Admart backend calls this service through DGX_FLUX_API_URL.
"""

import asyncio
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image


MODEL = os.getenv("FLUX_MODEL_PATH", "/mnt/Storage/carl/models/flux1-schnell")
GPUS = os.getenv("CUDA_VISIBLE_DEVICES", "4,5,6,7")
HOST = os.getenv("FLUX_HOST", "0.0.0.0")
PORT = int(os.getenv("FLUX_PORT", "8001"))
OUT_DIR = Path(os.getenv("FLUX_OUTPUT_DIR", "ad_outputs"))
T2I_STEPS = int(os.getenv("FLUX_T2I_STEPS", "4"))
FLUX_DTYPE = os.getenv("FLUX_DTYPE", "bfloat16").lower()
FLUX_DEVICE_MAP = os.getenv("FLUX_DEVICE_MAP", "balanced")
FLUX_GPU_MEMORY_LIMIT_GIB = int(os.getenv("FLUX_GPU_MEMORY_LIMIT_GIB", "22"))
FLUX_CPU_MEMORY_LIMIT = os.getenv("FLUX_CPU_MEMORY_LIMIT", "96GiB")
FLUX_MAX_GENERATION_RESOLUTION = int(os.getenv("FLUX_MAX_GENERATION_RESOLUTION", "720"))

os.environ["CUDA_VISIBLE_DEVICES"] = GPUS
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import torch

OUT_DIR.mkdir(exist_ok=True, parents=True)
LANCZOS = getattr(Image, "Resampling", Image).LANCZOS

app = FastAPI(title="Admart DGX1 FLUX API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_t2i_pipe = None
executor = ThreadPoolExecutor(max_workers=1)
jobs = {}

AD_STYLES = {
    "luxury": "ultra-luxury dark dramatic background, golden accent lighting, cinematic studio lighting, premium product photography, award-winning commercial advertisement",
    "minimalist": "clean minimalist pure white background, soft diffused lighting, elegant modern product photography, high-end brand aesthetic, negative space",
    "lifestyle": "lifestyle advertisement, aspirational golden hour lighting, vibrant colors, Instagram-worthy composition, warm cinematic grade",
    "tech": "futuristic tech advertisement, dark background with neon accent lighting, holographic elements, cyberpunk aesthetic, ultra-sharp details",
    "nature": "eco-friendly advertisement, lush green environment, natural soft lighting, organic textures, sustainable brand feel, fresh clean aesthetic",
    "bold": "bold striking advertisement, vivid saturated colors, dramatic contrast, high-energy commercial composition, eye-catching visual impact",
}

ASPECT_RATIOS = {
    "1:1": (1, 1),
    "16:9": (16, 9),
    "9:16": (9, 16),
    "4:5": (4, 5),
}


def _torch_dtype():
    if FLUX_DTYPE == "float16":
        return torch.float16
    if FLUX_DTYPE == "float32":
        return torch.float32
    return torch.bfloat16


def _round_to_multiple(value: float, multiple: int = 8) -> int:
    return max(multiple, int(round(value / multiple) * multiple))


def _clear_cuda_cache():
    if not torch.cuda.is_available():
        return

    for device_index in range(torch.cuda.device_count()):
        with torch.cuda.device(device_index):
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()


def _gpu_max_memory() -> dict:
    if not torch.cuda.is_available():
        return {}

    max_memory = {
        device_index: f"{FLUX_GPU_MEMORY_LIMIT_GIB}GiB"
        for device_index in range(torch.cuda.device_count())
    }
    max_memory["cpu"] = FLUX_CPU_MEMORY_LIMIT
    return max_memory


def _resolve_size(resolution: str, aspect_ratio: str) -> tuple[int, int]:
    if resolution not in {"480", "720", "1080"}:
        raise ValueError("resolution must be one of 480, 720, 1080")
    if aspect_ratio not in ASPECT_RATIOS:
        raise ValueError("aspect_ratio must be one of 1:1, 16:9, 9:16, 4:5")

    height = int(resolution)
    width_ratio, height_ratio = ASPECT_RATIOS[aspect_ratio]
    width = _round_to_multiple(height * width_ratio / height_ratio)
    return height, width


def _resolve_generation_size(resolution: str, aspect_ratio: str) -> tuple[int, int]:
    requested_height, requested_width = _resolve_size(resolution, aspect_ratio)
    generation_height = min(requested_height, FLUX_MAX_GENERATION_RESOLUTION)

    if generation_height == requested_height:
        return requested_height, requested_width

    width_ratio, height_ratio = ASPECT_RATIOS[aspect_ratio]
    generation_width = _round_to_multiple(generation_height * width_ratio / height_ratio)
    return generation_height, generation_width


def _generation_attempt_sizes(generation_height: int, aspect_ratio: str) -> list[tuple[int, int]]:
    width_ratio, height_ratio = ASPECT_RATIOS[aspect_ratio]
    heights = [generation_height]
    for fallback_height in (720, 480):
        if fallback_height < generation_height and fallback_height not in heights:
            heights.append(fallback_height)

    return [
        (height, _round_to_multiple(height * width_ratio / height_ratio))
        for height in heights
    ]


def _is_cuda_oom(exc: Exception) -> bool:
    return isinstance(exc, torch.cuda.OutOfMemoryError) or "CUDA out of memory" in str(exc)


def _build_prompt(prompt: str, style: str) -> str:
    style_suffix = AD_STYLES.get(style, AD_STYLES["luxury"])
    return (
        f"{prompt.strip()}, {style_suffix}, professional advertisement photography, "
        "no text overlay, no watermark"
    )


def get_t2i_pipe():
    global _t2i_pipe
    if _t2i_pipe is None:
        from diffusers import FluxPipeline

        print("Loading FluxPipeline for text-to-image...")
        load_kwargs = {
            "torch_dtype": _torch_dtype(),
            "device_map": FLUX_DEVICE_MAP,
        }
        max_memory = _gpu_max_memory()
        if max_memory:
            load_kwargs["max_memory"] = max_memory

        _t2i_pipe = FluxPipeline.from_pretrained(MODEL, **load_kwargs)
        _t2i_pipe.transformer.config.guidance_embeds = False
        _t2i_pipe.set_progress_bar_config(disable=True)
        if hasattr(_t2i_pipe, "vae") and hasattr(_t2i_pipe.vae, "enable_tiling"):
            _t2i_pipe.vae.enable_tiling()
        if hasattr(_t2i_pipe, "vae") and hasattr(_t2i_pipe.vae, "enable_slicing"):
            _t2i_pipe.vae.enable_slicing()
        print("Flux text-to-image pipeline ready.")
    return _t2i_pipe


def run_text2img(
    job_id: str,
    prompt: str,
    style: str,
    resolution: str,
    aspect_ratio: str,
    seed: int | None,
):
    try:
        height, width = _resolve_size(resolution, aspect_ratio)
        generation_height, generation_width = _resolve_generation_size(resolution, aspect_ratio)
        jobs[job_id]["status"] = "loading_model"
        pipe = get_t2i_pipe()
        full_prompt = _build_prompt(prompt, style)
        jobs[job_id].update(
            {
                "status": "generating",
                "full_prompt": full_prompt,
                "height": height,
                "width": width,
                "generation_height": generation_height,
                "generation_width": generation_width,
            }
        )

        t0 = time.perf_counter()
        result = None
        actual_generation_height = generation_height
        actual_generation_width = generation_width
        attempts = _generation_attempt_sizes(generation_height, aspect_ratio)
        for attempt_index, (attempt_height, attempt_width) in enumerate(attempts):
            try:
                jobs[job_id].update(
                    {
                        "generation_height": attempt_height,
                        "generation_width": attempt_width,
                    }
                )
                _clear_cuda_cache()
                generator = None
                if seed is not None:
                    generator = torch.Generator(device="cpu").manual_seed(seed)

                with torch.inference_mode():
                    result = pipe(
                        prompt=full_prompt,
                        height=attempt_height,
                        width=attempt_width,
                        num_inference_steps=T2I_STEPS,
                        guidance_scale=0.0,
                        generator=generator,
                    )
                actual_generation_height = attempt_height
                actual_generation_width = attempt_width
                break
            except Exception as exc:
                _clear_cuda_cache()
                if _is_cuda_oom(exc) and attempt_index < len(attempts) - 1:
                    next_height, next_width = attempts[attempt_index + 1]
                    print(
                        "[text2img] CUDA OOM at "
                        f"{attempt_width}x{attempt_height}; retrying at {next_width}x{next_height}"
                    )
                    continue
                raise

        if result is None:
            raise RuntimeError("FLUX generation did not return a result.")

        elapsed = time.perf_counter() - t0

        image = result.images[0]
        if (actual_generation_height, actual_generation_width) != (height, width):
            image = image.resize((width, height), LANCZOS)

        out_name = f"ad_{job_id}.png"
        image.save(str(OUT_DIR / out_name))
        del result
        del image
        _clear_cuda_cache()
        jobs[job_id].update(
            {
                "status": "done",
                "output_file": out_name,
                "elapsed": round(elapsed, 1),
            }
        )
        print(f"[text2img] Job {job_id} done in {elapsed:.1f}s")
    except Exception as exc:
        jobs[job_id].update({"status": "error", "error": str(exc)})
        print(f"[text2img] Job {job_id} failed: {exc}")


@app.get("/health")
async def health():
    return {
        "status": "running",
        "model": MODEL,
        "gpu": GPUS,
        "dtype": FLUX_DTYPE,
        "device_map": FLUX_DEVICE_MAP,
        "gpu_memory_limit_gib": FLUX_GPU_MEMORY_LIMIT_GIB,
        "max_generation_resolution": FLUX_MAX_GENERATION_RESOLUTION,
        "t2i_loaded": _t2i_pipe is not None,
    }


@app.get("/styles")
async def get_styles():
    return {"styles": list(AD_STYLES.keys())}


@app.post("/generate")
async def generate(
    mode: str = Form(default="text2img"),
    prompt: str = Form(...),
    style: str = Form(default="luxury"),
    resolution: str = Form(default="720"),
    aspect_ratio: str = Form(default="1:1"),
    seed: int | None = Form(default=None),
):
    if mode != "text2img":
        raise HTTPException(400, "Only text2img is enabled in this first API version.")
    if not prompt.strip():
        raise HTTPException(400, "Prompt is required.")

    try:
        height, width = _resolve_size(resolution, aspect_ratio)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    job_id = uuid.uuid4().hex[:12]
    jobs[job_id] = {
        "status": "queued",
        "mode": mode,
        "prompt": prompt,
        "style": style,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "height": height,
        "width": width,
        "seed": seed,
        "output_file": None,
        "full_prompt": None,
        "elapsed": None,
        "error": None,
    }

    loop = asyncio.get_running_loop()
    loop.run_in_executor(
        executor,
        run_text2img,
        job_id,
        prompt,
        style,
        resolution,
        aspect_ratio,
        seed,
    )
    return {"job_id": job_id, "status": "queued", "mode": mode}


@app.get("/status/{job_id}")
async def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    response = {
        "job_id": job_id,
        "status": job["status"],
        "mode": job["mode"],
        "style": job["style"],
        "prompt": job["prompt"],
        "resolution": job["resolution"],
        "aspect_ratio": job["aspect_ratio"],
        "height": job["height"],
        "width": job["width"],
        "generation_height": job.get("generation_height"),
        "generation_width": job.get("generation_width"),
        "full_prompt": job.get("full_prompt"),
    }
    if job["status"] == "done":
        response["output_url"] = f"/output/{job['output_file']}"
        response["elapsed"] = job["elapsed"]
    if job["status"] == "error":
        response["error"] = job["error"]
    return response


@app.get("/output/{filename}")
async def serve_output(filename: str):
    path = OUT_DIR / filename
    if not path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(str(path), media_type="image/png")


if __name__ == "__main__":
    import uvicorn

    print("Admart DGX1 FLUX text-to-image API")
    print(f"Model: {MODEL}")
    print(f"GPUs : {GPUS}")
    print(f"Open : http://{HOST}:{PORT}/health")
    uvicorn.run("dgx_flux_text2image_server:app", host=HOST, port=PORT, reload=False)
