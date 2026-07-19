# Admart

AI social-media platform: create images (and later videos), manage a per-project library, connect social accounts, and publish.

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
| Library list/detail + soft-delete | ✅ | ✅ `/library` |
| Social accounts list / OAuth connect URL / disconnect / callback | ✅ YouTube (+ Meta stubs) | ✅ `/social` |

### Frontend pages that are mostly mock / not backed by API yet

| Route | Notes |
|---|---|
| `/create` (Wizard) | Still calls **removed** endpoints `/api/images/text-to-image` — **broken**. Use `/image-gen` instead. |
| `/progress`, `/result`, `/publish` | Video pipeline UI; no VideoAsset/Publication APIs yet |
| `/templates`, `/calendar`, `/analytics`, `/notifications` | Local/mock data |
| `/brand-kit`, `/settings` | Mostly local UI; brand fields exist on User/Project but pages are not fully API-driven |
| `/dashboard` | Shell UI; not a full analytics backend |

### Planned (models/API not present)

`VideoAsset`, `Publication`, analytics sync, TikTok OAuth, agent/automation loop.

---

## Domain model (actual Django models)

```
User ──owns──► Project ──► SocialAccount (youtube|tiktok|instagram|facebook)
                │
                ├──► ImageJob / ImageUpload
                └──► LibraryAsset (image|video metadata; soft-delete via deleted_at)
```

- **User**: email login, plan, `credits_total` / `credits_used` / `credits_remaining`, `onboarding_completed`, `active_project`, brand kit fields.
- **Project**: workspace + per-project brand kit; parent for social + content.
- **SocialAccount**: one row per `(project, platform)`; tokens Fernet-encrypted; never returned by serializers.
- **ImageJob**: fal queue job (`textToImage`, `edit`, `multiEdit`, `upscale`, `removeBackground`).
- **LibraryAsset**: browsable assets; succeeded image jobs sync into the library.

Credits are integers on `User` (reserved/refunded around image jobs). History is derived from recent `ImageJob` rows — there is no separate ledger table.

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
| GET/DELETE | `/api/projects/{id}/library/{assetId}` | DELETE → soft-delete |

Default image models (from `content/catalog.py`): Flux Dev (textToImage), Nano Banana 2 Edit, ESRGAN, BiRefNet, etc.

---

## Frontend structure

```
src/
  App.jsx                 # routes
  utils/api.js            # Axios + JWT refresh (VITE_API_URL)
  utils/projects.js       # projects + social helpers
  utils/imageGeneration.js
  utils/library.js
  utils/credits.js
  pages/                  # route screens
  components/             # AppLayout, AdmartSidebar, Topbar, …
```

Key wired screens: Auth*, Onboarding, ImageGen, Library, Social, Billing, Project switcher.

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

- **YouTube**: OAuth connect URL + callback implemented; redirects to `{FRONTEND_URL}/social?connected=youtube`.
- **TikTok**: model allows it; connect URL returns **501** until implemented.
- **Facebook / Instagram**: Meta app env vars present; publish scopes gated by `FACEBOOK_PUBLISH_ENABLED` / `INSTAGRAM_PUBLISH_ENABLED`.

---

## Known gaps (do not document as done)

1. **Wizard `/create`** still hits deleted `/api/images/text-to-image*` — use **`/image-gen`**.
2. No video generation / publish / analytics APIs yet.
3. `requirements.txt` has no pinned versions; fal is called via `requests` (no fal SDK package).

For live request/response shapes, prefer **`/api/docs/`** over this README.
```
