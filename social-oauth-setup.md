# Social OAuth Setup — Local & Production

> Audience: backend / devops
> Scope: connecting social accounts (YouTube, Facebook, Instagram) for publishing + analytics.
> Companion: `backend-social-accounts.md` (API contract), `ARCHITECTURE.md` (system overview).

This is the canonical setup guide for the social-account OAuth integrations. It covers the
provider dashboards (Google Cloud, Meta), the environment variables, and the differences
between a **local/dev** setup and a **production** one.

## 0. How the flow works (recap)

1. Frontend → `GET /api/projects/:id/social/connect/:platform/url` → backend returns a signed
   `authUrl`.
2. Browser is redirected to the provider; user approves.
3. Provider → `GET /api/social/callback/:platform?code&state` → backend verifies `state`,
   exchanges the code, stores **encrypted** tokens, fetches the profile.
4. Backend 302-redirects to `FRONTEND_URL/social?connected=:platform`.

Implemented providers: **youtube** (Google), **facebook** + **instagram** (Meta).
**tiktok** returns `501` until built.

## 1. Environment variables

| Variable | Used for | Local default | Production |
| -------- | -------- | ------------- | ---------- |
| `FRONTEND_URL` | Where callbacks redirect back to | `http://localhost:5173` | your app's https URL |
| `GOOGLE_OAUTH_CLIENT_ID` | YouTube/Google OAuth | — | from Google Cloud |
| `GOOGLE_OAUTH_CLIENT_SECRET` | YouTube/Google OAuth | — | from Google Cloud |
| `YOUTUBE_OAUTH_REDIRECT_URI` | Google redirect | `http://localhost:8000/api/social/callback/youtube` | `https://api.<domain>/api/social/callback/youtube` |
| `META_APP_ID` | Facebook + Instagram | — | from Meta app |
| `META_APP_SECRET` | Facebook + Instagram | — | from Meta app |
| `FACEBOOK_OAUTH_REDIRECT_URI` | FB redirect | `http://localhost:8000/api/social/callback/facebook` | `https://api.<domain>/api/social/callback/facebook` |
| `INSTAGRAM_OAUTH_REDIRECT_URI` | IG redirect | `http://localhost:8000/api/social/callback/instagram` | `https://api.<domain>/api/social/callback/instagram` |
| `SOCIAL_TOKEN_ENCRYPTION_KEY` | Encrypt stored tokens (Fernet) | optional (derived from `SECRET_KEY`) | **required** — set a real key |

> The redirect URIs must match the provider dashboard **exactly** (scheme, host, port, path).

### Generate a token encryption key (for production)

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
Put the output in `SOCIAL_TOKEN_ENCRYPTION_KEY`. **Do not change it after tokens are stored** —
existing tokens become undecryptable. Rotating it requires re-connecting all accounts.

## 2. YouTube (Google Cloud) — local setup

1. **Create project:** https://console.cloud.google.com → New Project (`admart-social`).
2. **Enable API:** APIs & Services → Library → enable **YouTube Data API v3**.
3. **OAuth consent screen:** External; add app name + support email.
4. **Scopes:** add `.../auth/youtube.readonly` and `.../auth/youtube.upload`.
5. **Test users:** add the Google account(s) whose YouTube channel you'll connect.
6. **Credentials → Create OAuth client ID → Web application:**
   - Authorized redirect URI: `http://localhost:8000/api/social/callback/youtube`
   - Copy **Client ID** + **Client Secret**.
7. Put values in `.env` (`GOOGLE_OAUTH_CLIENT_ID/SECRET`).

## 3. Meta (Facebook + Instagram) — local setup

> **One Meta app powers both Facebook and Instagram.**

1. **Create app:** https://developers.facebook.com → Create App → use case **Other** →
   type **Business**. (Skip business portfolio; skip publishing requirements — they're info-only.)
2. **App ID/Secret:** App settings → Basic → copy **App ID** + **App Secret** → `.env`
   (`META_APP_ID`, `META_APP_SECRET`).
3. **Facebook Login → redirect URIs:** in the Facebook Login use case **Settings**, set
   *Valid OAuth Redirect URIs*:
   - `http://localhost:8000/api/social/callback/facebook`
   - `http://localhost:8000/api/social/callback/instagram`
   Enable **Client OAuth login** + **Web OAuth login**.
4. **Instagram (add as a PRODUCT, not a use case):** Dashboard → **Add Product** → **Instagram**
   → **API setup with Facebook login** (the variant for IG Business accounts linked to a Page).
   See the [official guide](https://developers.facebook.com/docs/instagram-platform/create-an-instagram-app).
5. **Permissions** (added per use case; full grant needs App Review for production):
   - Facebook: `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `public_profile`
   - Instagram: `instagram_basic`, `instagram_content_publish`, `pages_show_list`
6. **App roles → Roles:** ensure your account is Admin/Developer/Tester. Keep app in
   **Development** mode.

### Meta scopes: "connect now" vs "publish later"

Requesting a scope your Meta app hasn't enabled makes Meta reject the **entire** consent screen
with `Invalid Scopes`. So Meta connect requests only `public_profile` by default; the publishing
scopes are gated behind flags in `projects/oauth.py`:

```python
FACEBOOK_PUBLISH_ENABLED = False   # pages_show_list, pages_read_engagement, pages_manage_posts
INSTAGRAM_PUBLISH_ENABLED = False  # instagram_basic, instagram_content_publish, pages_*, business_management
```

Flip a flag to `True` **only after** those permissions are (a) added to the Meta app via the
relevant product/use case and (b) approved through **App Review** (+ Business Verification).
Until then, leave them `False` so users can still connect.

### Prerequisites for Instagram testing
- A **Facebook Page**.
- An **Instagram Professional (Business/Creator)** account **linked to that Page**.
  Without the link, IG connect succeeds but returns an empty profile.

> **Alternative — "Instagram API with Instagram login":** a newer variant that needs **no
> Facebook Page** (users log in directly with Instagram). It uses a different OAuth endpoint and
> the `instagram_business_*` scopes. Our backend currently implements the **Facebook-login**
> variant; switching is a provider change in `projects/oauth.py` if we decide users shouldn't
> need a Facebook Page.

## 4. Local smoke test (no frontend needed)

Verify a provider builds a valid authorize URL with your real credentials:

```bash
python -c "
import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings'); django.setup()
from projects import oauth
print(oauth.PROVIDERS['youtube'].build_auth_url('demo-state'))
print(oauth.PROVIDERS['facebook'].build_auth_url('demo-state'))
"
```

End-to-end (server running, with a project + bearer token):

```bash
# 1) get the authorize URL
curl -H "Authorization: Bearer <accessToken>" \
  http://localhost:8000/api/projects/<projectId>/social/connect/youtube/url
# 2) open the returned authUrl in a browser logged in as a TEST USER
# 3) after approving you land on http://localhost:5173/social?connected=youtube
# 4) confirm:
curl -H "Authorization: Bearer <accessToken>" \
  http://localhost:8000/api/projects/<projectId>/social/accounts
```

## 5. Production setup — what changes

Same providers, but tighten everything:

### 5.1 Redirect URIs & domains
- Use **HTTPS** redirect URIs on your real API domain, e.g.
  `https://api.<domain>/api/social/callback/youtube` (and `/facebook`, `/instagram`).
- Add the production URIs in **both** dashboards (keep localhost ones for dev or use a separate
  set of credentials per environment — recommended).
- Set `FRONTEND_URL=https://app.<domain>` so callbacks return to the real app.
- Google: add your domain under **Authorized domains**. Meta: add it under **App Domains** and
  configure the Privacy Policy + Terms URLs (required for review).

### 5.2 Verification & review (the long pole — start early)
- **Google / YouTube:** `youtube.upload` is a *sensitive* scope. Until the project passes the
  **YouTube API Services audit**, uploaded videos are **forced to private**. Submit for audit
  before launch (takes time).
- **Meta:** publishing scopes (`pages_manage_posts`, `instagram_content_publish`) require
  **App Review** + **Business Verification**. Each permission needs its own submission with a
  screencast of the full flow. Plan **2–4 weeks per round**. Until approved, only app
  roles/test users can connect; the app stays in Development mode.

### 5.3 Quotas
- **YouTube:** default 10,000 units/day; `videos.insert` ≈ 1,600 units (~6 uploads/day). Request
  a **quota increase** before real volume; handle `403 quotaExceeded` gracefully.
- **Meta:** rate limits are per-app/per-user; monitor and back off on throttling.

### 5.4 Secrets & security
- Set an explicit `SOCIAL_TOKEN_ENCRYPTION_KEY` (don't rely on the `SECRET_KEY`-derived dev key).
- Store all secrets in a secrets manager (not committed `.env`).
- Set `DEBUG=False`, a strong `SECRET_KEY`, and correct `ALLOWED_HOSTS` / `CORS_ORIGINS`.
- Tokens are encrypted at rest and never returned by any serializer — keep it that way.

### 5.5 Per-environment apps (recommended)
Use **separate OAuth apps/credentials** for dev, staging, and production so a misconfigured dev
redirect can't affect production, and so you can be in "Development mode" in one and "Live" in
another.

## 6. Troubleshooting

| Symptom | Cause / fix |
| ------- | ----------- |
| `redirect_uri_mismatch` (Google) / `URL blocked` (Meta) | Redirect URI not registered or not exact. Match scheme/host/port/path. |
| "Access blocked: app not verified" / only you can connect | App in Testing/Development mode — add the account as a test user/role, or complete review. |
| Uploaded YouTube videos are private | Expected until the YouTube API audit passes. Not a bug. |
| Instagram connects but profile is empty | IG account isn't Professional, or isn't linked to a Facebook Page. |
| `Invalid Scopes` (Meta) | The corresponding product/use case isn't added to the app. |
| Empty `client_id` in authUrl | Credentials missing from `.env`; restart server after editing `.env`. |
| Tokens won't decrypt after deploy | `SOCIAL_TOKEN_ENCRYPTION_KEY` changed. Keep it stable; re-connect accounts if rotated. |
