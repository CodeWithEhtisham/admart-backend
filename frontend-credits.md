# Frontend Guide — Credits

> Audience: frontend team  
> Base URL: `VITE_API_URL` (default `http://localhost:8000`)  
> Auth: `Authorization: Bearer <accessToken>` on every call

## Endpoints

| Method | Path | Purpose |
| ------ | ---- | ------- |
| `GET` | `/api/credits` | Current balance |
| `GET` | `/api/credits/costs` | Price per image capability |
| `GET` | `/api/credits/history?limit=20` | Recent spends (image jobs) |

`creditsRemaining` still appears on `/api/auth/me` and on image job `202` / `402` responses — use this dedicated API for the credits page / badge refresh.

---

### 1. Balance — `GET /api/credits`

```json
{
  "plan": "free",
  "creditsTotal": 100,
  "creditsUsed": 0,
  "creditsRemaining": 100,
  "creditsResetAt": null,
  "canGenerate": true
}
```

| Field | Use |
| ----- | --- |
| `creditsRemaining` | **Show this** in the badge; disable Generate when `0` |
| `creditsTotal` | Plan allotment only — do **not** gate UI on this |
| `creditsUsed` | Optional “used this period” |
| `canGenerate` | Shortcut for `creditsRemaining > 0` |

---

### 2. Costs — `GET /api/credits/costs`

```json
{
  "currency": "credits",
  "items": [
    {
      "capability": "textToImage",
      "credits": 1,
      "perImage": true,
      "notes": "Cost × numImages"
    },
    {
      "capability": "edit",
      "credits": 1,
      "perImage": false,
      "notes": "Flat cost per job"
    }
  ],
  "byCapability": {
    "textToImage": 1,
    "edit": 1,
    "multiEdit": 2,
    "upscale": 1,
    "removeBackground": 1
  }
}
```

Estimate before Generate:

```ts
const cost =
  capability === "textToImage"
    ? byCapability.textToImage * (numImages || 1)
    : byCapability[capability];
```

---

### 3. History — `GET /api/credits/history?limit=20`

```json
{
  "items": [
    {
      "id": "…",
      "projectId": "…",
      "capability": "textToImage",
      "model": "fal-ai/flux/dev",
      "status": "succeeded",
      "credits": 1,
      "prompt": "Create an image of a cat",
      "createdAt": "2026-07-18T12:00:00Z"
    }
  ]
}
```

---

## Suggested FE usage

```ts
// Badge on mount / after generate
const { creditsRemaining, canGenerate } = await api.get("/api/credits");

// Pricing tooltip next to Generate
const { byCapability } = await api.get("/api/credits/costs");

// After POST …/images/jobs → 202
setCreditsRemaining(job.creditsRemaining);

// On 402
if (err.code === "INSUFFICIENT_CREDITS") {
  setCreditsRemaining(err.creditsRemaining ?? 0);
  openPaywall();
}
```
