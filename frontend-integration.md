# Frontend Integration Guide — Projects & Social Accounts

> Audience: frontend team
> Base URL: `VITE_API_URL` (default `http://localhost:8000`)
> Auth: all endpoints below require `Authorization: Bearer <accessToken>` unless noted.
> All request/response bodies are JSON. Timestamps are ISO-8601 strings.

## 1. Mental model

```
User ──owns──> Project (many) ──has──> SocialAccount (many)
                              └──has──> Brand Kit / settings
```

- A **user** owns many **projects**. One project per brand / set of social accounts.
- Each **project** carries its **own** social media accounts and brand kit. Switching
  project switches the whole working context.
- The user has one **active project** at a time. It is stored on the server, so it is
  remembered across logout/login.

> Single-owner for now. Sharing projects with other users is planned but not yet available.

## 2. Post-login routing

After login you get the user object back (see §3). Use it to route:

```mermaid
flowchart TD
    A[Login success] --> B{user.projectCount > 0?}
    B -- No --> C[navigate /onboarding]
    B -- Yes --> D{user.activeProjectId set?}
    D -- Yes --> E[Use that project]
    D -- No --> F[Use projects[0] from GET /api/projects]
    E --> G[navigate /dashboard]
    F --> G
```

- `projectCount === 0` → send the user to **onboarding** (they must create a project).
- Otherwise → use `activeProjectId` (the last project they activated; remembered across
  sessions) and go to the dashboard.
- `activeProjectId` is also returned directly by login and `GET /api/auth/me`, so you can
  route without a second request.

## 3. Auth endpoints (existing + additions)

### `POST /api/auth/login`

**Request**

```json
{ "email": "jane@example.com", "password": "Secret123!" }
```

**200 Response**

```json
{
  "accessToken": "...",
  "refreshToken": "...",
  "user": {
    "id": "...",
    "email": "jane@example.com",
    "firstName": "Jane",
    "lastName": "Smith",
    "plan": "free",
    "creditsRemaining": 5,
    "onboardingCompleted": true,
    "projectCount": 2,
    "activeProjectId": "5f1c0c2e-...",
    "brandKit": { "brandName": "", "industry": "", "brandColorHex": "#2563eb", "logoUrl": null }
  }
}
```

> `projectCount` and `activeProjectId` are the new fields used for routing.
> `register`, `google`, and `GET /api/auth/me` return the same `user` shape.

### `POST /api/auth/onboarding/complete`

Creates the user's **first project** (with its brand kit + connected platforms) and makes it
active. Call this from the onboarding page instead of writing the brand kit to the user.

**Request** (all fields optional)

```json
{
  "projectName": "My Brand",
  "connectedPlatforms": ["tiktok", "youtube"],
  "brandName": "My Brand",
  "industry": "SaaS",
  "brandColorHex": "#7c3aed"
}
```

**200 Response** — the updated `user` object (`projectCount` is now ≥ 1, `activeProjectId`
points at the new project).

## 4. Project endpoints

A project object looks like:

```json
{
  "id": "5f1c0c2e-...",
  "name": "Summer Campaign",
  "icon": "☀",
  "color": "#7c3aed",
  "org": "Admart",
  "brandKit": { "brandName": "...", "industry": "...", "brandColorHex": "#7c3aed", "logoUrl": null },
  "lastAccessedAt": "2026-06-22T10:15:00Z",
  "createdAt": "2026-05-01T09:00:00Z",
  "updatedAt": "2026-06-22T10:15:00Z"
}
```

### `GET /api/projects` — list projects

Ordered most-recently-used first, so `projects[0]` is the auto-active project when no
explicit selection exists.

**200 Response**

```json
{
  "projects": [ { /* project */ } ],
  "activeProjectId": "5f1c0c2e-..."
}
```

- Empty `projects: []` → show onboarding.

### `POST /api/projects` — create a project

The new project becomes active immediately.

**Request**

```json
{ "name": "My First Project", "icon": "▶", "color": "#2563eb", "org": "Personal" }
```

- `name` required (1–80 chars). `icon`, `color`, `org` optional.
- You may also send brand kit fields: `brand_name`, `brand_industry`, `brand_color_hex`,
  `brand_logo_url` (snake_case).

**201 Response** — the created project object.
**400** — validation error, e.g. `{ "name": ["This field may not be blank."] }`.

### `GET /api/projects/:id` — single project

`200` → project object. `404` if it does not exist or is not yours.

### `PATCH /api/projects/:id` — update

Partial update of `name` / `icon` / `color` / `org` / brand kit fields. `200` → updated project.

### `DELETE /api/projects/:id` — delete

`204` on success. If it was the active project, the server clears the pointer and the next
list falls back to the most recent project.

### `POST /api/projects/:id/activate` — switch / mark active

Call this in the project dropdown's `selectProject()` and when the workspace loads a project.

**200 Response**

```json
{ "activeProjectId": "5f1c0c2e-..." }
```

This is what makes the selection sticky across logout/login.

## 5. Social accounts (scoped to a project)

Platforms: `tiktok`, `youtube`, `instagram`, `facebook`. A social account object:

```json
{
  "id": "...",
  "projectId": "5f1c0c2e-...",
  "platform": "tiktok",
  "handle": "@jane_tiktok",
  "displayName": "Jane Smith",
  "connected": true,
  "avatarUrl": null,
  "tokenExpiresAt": null,
  "createdAt": "2026-06-22T10:15:00Z"
}
```

### `GET /api/projects/:id/social/accounts`

`200` → array of social account objects for that project.

### `POST /api/projects/:id/social/connect/:platform`

Connects (or re-activates) a platform for the project. `201` if newly created, `200` if it
already existed. `400` for an unknown platform. `404` if the project is not yours.

### `DELETE /api/projects/:id/social/disconnect/:platform`

Soft-disconnect (sets `connected: false`). `200` on success, `404` if not connected.

> The same platform can be connected in multiple projects independently — connections are
> per project, not per user.

## 6. Errors

| Status | When                                    |
| ------ | --------------------------------------- |
| 401    | Missing/expired token                   |
| 404    | Resource not found or not owned by user |
| 400    | Validation failed                       |

> Accessing another user's project returns `404` (not `403`) so existence is not leaked.

## 7. Suggested frontend changes

1. **AuthPage** — after login, branch on `user.projectCount` / `user.activeProjectId`
   instead of `onboardingCompleted`.
2. **OnboardingPage** — replace local-only project creation with
   `POST /api/auth/onboarding/complete` (or `POST /api/projects`), then go to `/dashboard`.
3. **ProjectDropdown** — load from `GET /api/projects`, call
   `POST /api/projects/:id/activate` in `selectProject()`, and create via `POST /api/projects`.
4. **Settings / Social** — read & mutate via the project-scoped
   `/api/projects/:id/social/*` endpoints using the active project id.
