# Backend Guide — Library Assets (Videos + Images)

> Audience: backend team  
> Goal: One library API so the FE **Library** page can show Videos and Images, newest first  
> Related FE: `src/pages/LibraryPage.jsx`, `src/utils/library.js`  
> Images already created via: `POST/GET /api/projects/:id/images/jobs`

---

## 1. Problem

Today image jobs are created with fal, but the Library UI was video-only mock data. Users expect:

- All **images** and **videos** for the active project  
- Tabs: **All** | **Videos** | **Images**  
- Sorted **`createdAt` DESC** (latest first)  
- Actions: view, publish, download, delete  

Images must be **persisted on the backend** when a job succeeds (durable CDN URL), not only temporary fal URLs.

---

## 2. Recommended model — `LibraryAsset`

One row per publishable / browsable asset.

| Field | Type | Notes |
| ----- | ---- | ----- |
| `id` | uuid | PK |
| `projectId` | uuid | Scoped to project |
| `mediaType` | enum | `image` \| `video` |
| `title` | string | From prompt or user edit |
| `status` | enum | `ready` \| `generating` \| `published` \| `scheduled` \| `failed` |
| `thumbnailUrl` | string \| null | Poster / image URL |
| `sourceUrl` | string | Durable CDN URL (required when ready) |
| `prompt` | string \| null | Especially for AI images |
| `model` | string \| null | fal / video model id |
| `capability` | string \| null | e.g. `textToImage`, `edit` |
| `durationSeconds` | int \| null | Videos only |
| `width` / `height` | int \| null | |
| `jobId` | string \| null | Link to image/video job |
| `createdAt` | datetime | Sort key |
| `updatedAt` | datetime | |

**When to create / update**

| Event | Action |
| ----- | ------ |
| Image job → `succeeded` | Upsert asset `mediaType=image`, `status=ready`, copy fal URL → your CDN → `sourceUrl` |
| Image job → `failed` | Optional: asset `status=failed` or skip |
| Video job → ready | Same for `mediaType=video` |
| User publishes | Set `status=published` |

---

## 3. Endpoints

### 3.1 List library (primary)

```
GET /api/projects/:projectId/library?mediaType=all|image|video&limit=50&cursor=
```

Auth + project ownership required.

`200`:

```json
{
  "items": [
    {
      "id": "…",
      "projectId": "…",
      "mediaType": "image",
      "title": "Product shot on marble",
      "status": "ready",
      "thumbnailUrl": "https://cdn…/thumb.jpg",
      "sourceUrl": "https://cdn…/out.png",
      "prompt": "…",
      "model": "fal-ai/flux/dev",
      "capability": "textToImage",
      "durationSeconds": null,
      "createdAt": "2026-07-19T12:00:00Z",
      "updatedAt": "2026-07-19T12:00:00Z"
    }
  ],
  "nextCursor": null
}
```

**Default sort:** `createdAt DESC`.

### 3.2 Fallback until library table ships

If you have not built `LibraryAsset` yet, FE can temporarily use:

```
GET /api/projects/:projectId/images/jobs?limit=50
```

and map succeeded jobs → image cards.  
**Still required:** durable URLs on job success (copy off fal).

Videos: expose

```
GET /api/projects/:projectId/videos?limit=50
```

same shape as library items with `mediaType: "video"`.

### 3.3 Cancel in-progress job

Images (already in image-gen guide):

```
POST /api/projects/:projectId/images/jobs/:jobId/cancel
```

Videos (mirror the same pattern):

```
POST /api/projects/:projectId/videos/:id/cancel
# or
POST /api/projects/:projectId/videos/jobs/:jobId/cancel
```

FE shows **Cancel** only when `status === generating`.

### 3.4 Delete (optional)

```
DELETE /api/projects/:projectId/library/:assetId
```

Soft-delete preferred.

---

## 4. FE usage (already implemented)

| Tab | Request |
| --- | ------- |
| All | Prefer `GET …/library?mediaType=all` |
| Videos | `mediaType=video` (or videos endpoint) |
| Images | `mediaType=image` (or flatten image jobs) |

UI: `src/pages/LibraryPage.jsx` — tabs All / Videos / Images, newest first.

---

## 5. Checklist for backend

- [x] On image job success: persist durable `sourceUrl` + library row  
- [x] `GET …/library` with `mediaType` filter + `createdAt DESC`  
- [x] Do not return temporary fal URLs as the only copy  
- [x] Scope by `projectId` + owner  
- [x] Return empty `items: []` (not 404) when the project has no assets  
- [x] Soft `DELETE …/library/:assetId`  
- [x] Generating placeholder on job create; failed/cancel sync  

Backfill existing jobs: `python manage.py backfill_library`  
FE contract: `frontend-library.md`

---

*Pair with `docs/backend-image-generation.md` for job create/poll.*
