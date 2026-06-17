from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.schemas import TextToImageJobResponse, TextToImageRequest, TextToImageStatusResponse
from app.services.flux_client import (
    FluxClientError,
    fetch_text_to_image_file,
    get_dgx_health,
    get_text_to_image_status,
    start_text_to_image,
)


app = FastAPI(title="Admart Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    dgx = None
    try:
        dgx = await get_dgx_health()
    except Exception as exc:
        dgx = {"status": "unreachable", "error": str(exc)}

    return {
        "status": "running",
        "service": "admart-backend",
        "dgx_flux_api_url": settings.dgx_flux_api_url,
        "dgx": dgx,
    }


@app.post("/api/images/text-to-image", response_model=TextToImageJobResponse)
async def text_to_image(payload: TextToImageRequest):
    try:
        return await start_text_to_image(payload)
    except FluxClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/api/images/text-to-image/{job_id}", response_model=TextToImageStatusResponse)
async def text_to_image_status(job_id: str):
    try:
        return await get_text_to_image_status(job_id)
    except FluxClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.get("/api/images/text-to-image/{job_id}/file")
async def text_to_image_file(job_id: str):
    try:
        content, media_type = await fetch_text_to_image_file(job_id)
        return Response(content=content, media_type=media_type)
    except FluxClientError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@app.post("/api/text-to-image", response_model=TextToImageJobResponse, include_in_schema=False)
async def text_to_image_alias(payload: TextToImageRequest):
    return await text_to_image(payload)
