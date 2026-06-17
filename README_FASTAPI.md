# Admart FastAPI Text-to-Image Backend

This folder already contains the starter Django project. The FastAPI service added here is separate and currently handles only Text to Image.

## 1. Run the DGX1 Flux API

Copy `dgx_flux_text2image_server.py` to the DGX1 server and run:

```bash
pip install fastapi uvicorn diffusers transformers accelerate torch pillow python-multipart
export FLUX_MODEL_PATH=/mnt/Storage/carl/models/flux1-schnell
export CUDA_VISIBLE_DEVICES=4,5,6,7
python dgx_flux_text2image_server.py
```

Check:

```bash
curl http://100.104.174.12:8001/health
```

## 2. Run the local FastAPI proxy

From this backend folder on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-fastapi.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Check:

```powershell
curl http://127.0.0.1:8000/health
```

## 3. Frontend environment

The frontend defaults to `http://localhost:8000`. To override it, create a frontend `.env` file:

```text
VITE_ADMART_API_URL=http://localhost:8000
```

## Text-to-image endpoint

```http
POST /api/images/text-to-image
Content-Type: application/json
```

```json
{
  "prompt": "Premium skincare bottle on white marble",
  "style": "Cinematic",
  "aspect_ratio": "1:1",
  "resolution": "720"
}
```

The response includes `image_base64`, which the React app can render directly.
