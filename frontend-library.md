# Frontend Guide — Library Assets

> Audience: frontend team  
> Base URL: `VITE_API_URL` (default `http://localhost:8000`)  
> Auth: `Authorization: Bearer <accessToken>` on every call  
> Scope: active project (`projectId`)

Prefer this API over mapping image jobs in the Library page.

---

## Endpoints

| Method | Path | Purpose |
| ------ | ---- | ------- |
| `GET` | `/api/projects/:projectId/library` | List images + videos |
| `DELETE` | `/api/projects/:projectId/library/:assetId` | Soft-delete (204) |

Cancel in-progress generations via the existing image-job cancel endpoint (not library).

---

### 1. List — `GET /api/projects/:projectId/library`

Query params:

| Param | Default | Notes |
| ----- | ------- | ----- |
| `mediaType` | `all` | `all` \| `image` \| `video` |
| `limit` | `50` | Max `100` |
| `cursor` | (none) | Opaque offset string from prior `nextCursor` |

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
      "thumbnailUrl": "http://localhost:8000/media/…/out-0.png",
      "sourceUrl": "http://localhost:8000/media/…/out-0.png",
      "prompt": "…",
      "model": "fal-ai/flux/dev",
      "capability": "textToImage",
      "durationSeconds": null,
      "width": 1024,
      "height": 1024,
      "jobId": "…",
      "createdAt": "2026-07-19T12:00:00Z",
      "updatedAt": "2026-07-19T12:00:00Z"
    }
  ],
  "nextCursor": null
}
```

| Field | Use |
| ----- | --- |
| `status` | `generating` → show spinner / Cancel; `ready` → view/download/publish; `failed` → error card |
| `sourceUrl` / `thumbnailUrl` | Durable app media URLs (not temporary fal CDN) |
| `jobId` | Cancel: `POST …/images/jobs/:jobId/cancel` while `generating` |
| `durationSeconds` | Videos only (null for images) |

Sort is always **newest first** (`createdAt` DESC). Empty library → `{ "items": [], "nextCursor": null }` (not 404).

Tabs:

| Tab | Request |
| --- | ------- |
| All | `?mediaType=all` |
| Videos | `?mediaType=video` (may be empty until video gen ships) |
| Images | `?mediaType=image` |

---

### 2. Delete — `DELETE /api/projects/:projectId/library/:assetId`

- Soft-delete; asset disappears from subsequent lists
- Success: `204 No Content`
- Wrong project / already deleted: `404`

---

### 3. When assets appear

| Event | Library row |
| ----- | ----------- |
| Image job submitted | `status=generating` |
| Job succeeds | `status=ready` + durable URLs |
| Job fails / cancel | `status=failed` |

Refresh the library after job create / poll / cancel so cards stay in sync.

---

*See `frontend-image-generation.md` for job create/poll.*
