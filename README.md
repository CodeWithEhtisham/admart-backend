# Admart

AI social-media platform: create images and videos via fal.ai, manage a per-project library, connect social accounts, and publish.

This README is the **single project doc** for both repos. The same file lives in:

- Backend: https://github.com/CodeWithEhtisham/admart-backend
- Frontend: https://github.com/CodeWithEhtisham/Admart-frontend

Verified against the codebase on **2026-07-19** (`staging`). Older `*.md` specs were removed; trust this file and the OpenAPI schema.

---

## Repos & stack

| | Backend | Frontend |
|---|---|---|
| Path | `admart-backend` | `Admart-frontend` |
| Branch | `staging` | `staging` |
| Stack | Django 6 + DRF + SimpleJWT + Spectacular + CORS | React 19 + Vite 8 + Tailwind 4 + React Router 7 + Axios |
| Default URL | `http://localhost:8000` | `http://localhost:5173` |
| API docs | `/api/docs/` (Swagger), `/api/redoc/`, `/api/schema/` | — |

Django apps: `config`, `users`, `projects`, `content`.

---

## What is real vs UI-only

### Implemented end-to-end (API + wired UI)

| Area | Backend | Frontend |
|---|---|---|
| Auth (register/login/refresh/logout, forgot/reset password, Google OAuth, `/me`) | ✅ | ✅ Auth pages |
| Onboarding → create first project | ✅ projects API | ✅ `/onboarding` |
| Projects CRUD + activate + active project | ✅ | ✅ Project dropdown |
| Credits balance / costs / history | ✅ | ✅ Billing + sidebar |
| Image jobs (fal.ai): create, poll, cancel, upload, model catalog | ✅ | ✅ `/image-gen` |
| Video jobs (fal.ai): create, poll, cancel, frame upload, model catalog | ✅ | ✅ `/video-gen` (also `/create`) |
| Library list/detail + soft-delete + user upload | ✅ | ✅ `/library` (images + videos) |
| Social accounts list / OAuth connect URL / disconnect / callback | ✅ YouTube (+ Meta stubs) | ✅ `/social` |

### Frontend pages that are mostly mock / not backed by API yet

| Route | Notes |
|---|---|
| `/progress`, `/result` | Result chrome; publish is backed by `/api/projects/:id/publish` and `/ads/boost` |
| `/templates`, `/calendar`, `/analytics`, `/notifications` | Local/mock data |
| `/brand-kit`, `/settings` | Mostly local UI; brand fields exist on User/Project but pages are not fully API-driven |
| `/dashboard` | Shell UI; not a full analytics backend |

### Planned

Publication / analytics sync, full Ads Manager. Expand video catalog beyond curated set as needed.

---

## Domain model (actual Django models)

```
User ──owns──► Project ──► SocialAccount (youtube|tiktok|instagram|facebook)
                │
                ├──► ImageJob / ImageUpload
                ├──► VideoJob
                └──► LibraryAsset (image|video; soft-delete via deleted_at)
```

- **User**: email login, plan, `credits_total` / `credits_used` / `credits_remaining`, `onboarding_completed`, `active_project`, brand kit fields.
- **Project**: workspace + per-project brand kit; parent for social + content.
- **SocialAccount**: one row per `(project, platform)`; tokens Fernet-encrypted; never returned by serializers.
- **ImageJob**: fal queue job (`textToImage`, `edit`, `multiEdit`, `upscale`, `removeBackground`).
- **VideoJob**: fal queue job (`textToVideo`, `imageToVideo`, `firstLastFrame`) with per-model field profiles in `content/video_catalog.py`.
- **LibraryAsset**: browsable assets; succeeded image/video jobs sync into the library.

Credits are integers on `User` (reserved/refunded around jobs). History merges recent `ImageJob` + `VideoJob` rows.

---

## API map (authoritative)

Auth base: `/api/auth/`

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/auth/register` | Sign up |
| POST | `/api/auth/login` | JWT pair |
| POST | `/api/auth/refresh` | Refresh access |
| POST | `/api/auth/logout` | Blacklist refresh |
| POST | `/api/auth/google` | Google code exchange |
| POST | `/api/auth/forgot-password` | Request reset |
| POST | `/api/auth/reset-password` | Complete reset |
| GET/PATCH | `/api/auth/me` | Current user |
| POST | `/api/auth/onboarding/complete` | Mark onboarding done |

Credits:

| Method | Path |
|---|---|
| GET | `/api/credits` |
| GET | `/api/credits/costs` |
| GET | `/api/credits/history` |

Projects & social:

| Method | Path |
|---|---|
| GET/POST | `/api/projects` |
| GET/PATCH/DELETE | `/api/projects/{id}` |
| POST | `/api/projects/{id}/activate` |
| GET | `/api/projects/{id}/social/accounts` |
| GET | `/api/projects/{id}/social/connect/{platform}/url` |
| POST | `/api/projects/{id}/social/connect/{platform}` |
| DELETE | `/api/projects/{id}/social/disconnect/{platform}` |
| GET | `/api/social/callback/{platform}` | Provider redirect |

Images & library (project-scoped):

| Method | Path |
|---|---|
| GET | `/api/images/models` | Global catalog |
| GET | `/api/projects/{id}/images/models` | Same, project path |
| GET/POST | `/api/projects/{id}/images/jobs` |
| GET | `/api/projects/{id}/images/jobs/{jobId}` |
| POST | `/api/projects/{id}/images/jobs/{jobId}/cancel` |
| POST | `/api/projects/{id}/images/uploads` | multipart |
| GET | `/api/projects/{id}/library` |
| POST | `/api/projects/{id}/library/uploads` | User image (jpeg/png/webp ≤15MB) or video (mp4/mov/webm ≤200MB) |
| GET/DELETE | `/api/projects/{id}/library/{assetId}` | DELETE → soft-delete |

Default image models (from `content/catalog.py`): Flux Dev (textToImage), Nano Banana 2 Edit, ESRGAN, BiRefNet, etc.

Videos (project-scoped):

| Method | Path |
|---|---|
| GET | `/api/videos/models` | Curated catalog + field profiles |
| GET | `/api/projects/{id}/videos/models` |
| GET/POST | `/api/projects/{id}/videos/jobs` |
| GET | `/api/projects/{id}/videos/jobs/{jobId}` | Poll-on-read |
| POST | `/api/projects/{id}/videos/jobs/{jobId}/cancel` |
| POST | `/api/projects/{id}/videos/uploads` | Frame images (same rules as image upload) |

**Video capabilities:** `textToVideo` (prompt only) · `imageToVideo` (prompt + start image) · `firstLastFrame` (prompt + start + end).  
Each catalog entry declares `inputs` and `fields` (duration, aspect, resolution, audio, …) and `falImageKeys` so the API maps to the correct fal args (`image_url`, `first_frame_url`/`last_frame_url`, `end_image_url`, `tail_image_url`, …).

Curated models include Veo 3.1, Seedance 2.0, Kling, Hailuo, Wan, PixVerse, LTX (see `content/video_catalog.py`).

---

## Frontend structure

```
src/
  App.jsx                 # routes
  utils/api.js            # Axios + JWT refresh (VITE_API_URL)
  utils/projects.js       # projects + social helpers
  utils/imageGeneration.js
  utils/videoGeneration.js
  utils/library.js
  utils/credits.js
  pages/                  # route screens
  components/             # AppLayout, AdmartSidebar, Topbar, …
```

Key wired screens: Auth*, Onboarding, ImageGen, VideoGen, Library, Social, Billing, Project switcher.

Env:

```bash
# Admart-frontend/.env  (name must match code)
VITE_API_URL=http://localhost:8000
```

---

## Local setup

### Backend

```bash
cd admart-backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set FAL_KEY, Google/YouTube OAuth, SOCIAL_TOKEN_ENCRYPTION_KEY as needed
python manage.py migrate
python manage.py runserver
```

Useful `.env` keys: `FRONTEND_URL`, `GOOGLE_OAUTH_*`, `YOUTUBE_OAUTH_REDIRECT_URI`, `META_*`, `FAL_KEY`, `MEDIA_BASE_URL`, `SOCIAL_TOKEN_ENCRYPTION_KEY`.

### Frontend

```bash
cd Admart-frontend
npm install
echo 'VITE_API_URL=http://localhost:8000' > .env
npm run dev
```

---

## OAuth notes (social)

- **YouTube / Facebook / Instagram / TikTok / Snapchat**: connect URL + callback implemented; redirects to `{FRONTEND_URL}/social?connected=<platform>`.
- **Publishing scopes** stay off until App Review: `FACEBOOK_PUBLISH_ENABLED`, `INSTAGRAM_PUBLISH_ENABLED`, `TIKTOK_PUBLISH_ENABLED`.
- **TikTok** redirect URI must be `https` (ngrok locally). **Snapchat Login Kit** is identity only (no organic post).
- **Ads accounts** (Meta / TikTok / Snap) use separate OAuth at `/api/projects/:id/ads/connect/<provider>/url` and `/api/ads/callback/<provider>`. Do not mix ads scopes into organic Connect.
- **Meta Invalid Scopes** on Connect Meta Ads: a Facebook Login + “App Ads Manager” app cannot add Marketing API. Create a second **Business** app with use case **Create & manage ads with Marketing API**, set `META_ADS_APP_ID` / `META_ADS_APP_SECRET`, and add `{BACKEND}/api/ads/callback/meta` as that app’s redirect URI. Keep `META_APP_*` for organic Facebook Login.
- Fill portal credentials in `.env` (`INSTAGRAM_APP_*`, `TIKTOK_CLIENT_*`, `SNAPCHAT_CLIENT_*`) and restart Django.

---

## Known gaps (do not document as done)

1. Facebook/Instagram/TikTok organic post needs App Review (`*_PUBLISH_ENABLED`). Full Ads Manager (audiences, reporting, Google/YouTube ads) is later.
2. Video catalog is curated (not all ~141 fal endpoints); some partner models may 502 if the account lacks access — swap ids in `video_catalog.py`.
3. `requirements.txt` has no pinned versions; fal is called via `requests` (no fal SDK package).

For live request/response shapes, prefer **`/api/docs/`** over this README.
