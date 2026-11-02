# Admart Auth — Backend spec (Django)

> **Pass this file to backend.** It is the contract. Frontend is already live against it.  
> Brand: **Admart**. Clerk is gone. Do not verify Clerk or Firebase tokens.  
> Date: 2026-08-31

---

## Do this now (blocker)

**Sign in must not create accounts.** Users Sign up first, then Sign in.

Today `POST /api/auth/google` find-or-creates, so a Gmail with no Admart user still gets a JWT. Stop that.

| User clicked | Body from web | Backend |
| ------------ | ------------- | ------- |
| **Sign in** | `intent: "login"`, `createAccount: false` | User exists → JWT. Missing → **404** `no_account`. **Do not create.** |
| **Sign up** | `intent: "register"`, `createAccount: true` | Missing → create + JWT. Exists → JWT (or 409 if you want them to Sign in). |

Exact 404 body (use this `code` and `message`):

```json
{
  "code": "no_account",
  "message": "There is no Admart account for this email. Please sign up first, then sign in."
}
```

HTTP **404**, never **401** on `/api/auth/google` (401 triggers the web refresh interceptor).

Same product rule for email: `POST /api/auth/login` if the email has no `User` → same 404 + `no_account`. Wrong password stays 401.

**Out of scope for this change:** Facebook, Apple, email-verify SMTP, MFA, refactoring JWT.

---

## 1. Decision

**Admart owns the user and the session.** Google / Facebook / Apple only prove who the person is.

| Layer | Role |
| ----- | ---- |
| Google / Facebook / Apple | Identity provider |
| Django `User` + SimpleJWT | Source of truth: user row, access + refresh |
| Web / Android / iOS | Call **only** `/api/auth/*`; store **Admart** tokens |

Email/password and Google return the **same JWT pair**.

---

## 2. Why not Clerk or Firebase as the long-term system

| | Clerk | Firebase Auth | Admart JWT + Google OIDC |
| --- | --- | --- | --- |
| Who owns the user | Clerk | Google/Firebase | **Django `User`** |
| Mobile | Their SDKs | Their SDKs | **Same REST API** |
| Cost (email + Google) | Hobby then Pro | Identity Platform after free tier | **$0** (Google Sign-In is free) |

Firebase is still useful later for **FCM, Crashlytics, Analytics** — not for “who is logged in.”

---

## 3. Response contract (all login paths)

Every successful `register` / `login` / `google` **must** return camelCase:

```json
{
  "accessToken": "…",
  "refreshToken": "…",
  "user": {
    "id": "…",
    "email": "user@example.com",
    "firstName": "…",
    "lastName": "…",
    "emailVerified": true
  }
}
```

`access` / `refresh` aliases are OK if SimpleJWT defaults are easier; prefer `accessToken` / `refreshToken`.

Authenticated APIs:

```
Authorization: Bearer <accessToken>
```

| Method | Path | Status | Notes |
| ------ | ---- | ------ | ----- |
| `POST` | `/api/auth/register` | live | Email + password. **Creates** the user. |
| `POST` | `/api/auth/login` | live | Email + password. **Never creates.** Missing email → 404 `no_account`. |
| `POST` | `/api/auth/google` | **change now** | Auth code + `intent` / `createAccount`. See §4. |
| `POST` | `/api/auth/refresh` | live | `{ "refresh": "…" }` or `{ "refreshToken": "…" }` |
| `POST` | `/api/auth/logout` | live | Blacklist refresh |
| `GET` / `PATCH` | `/api/auth/me` | live | Current user |
| `POST` | `/api/auth/forgot-password` | live | |
| `POST` | `/api/auth/reset-password` | live | |
| `POST` | `/api/auth/verify-email` | later | |
| `POST` | `/api/auth/resend-verification` | later | |
| `POST` | `/api/auth/facebook` | later | |
| `POST` | `/api/auth/apple` | later | |

---

## 4. Google — implement / fix this now

Web uses the **authorization-code** flow. Clerk is gone.

```
Browser  →  Google authorize
         ←  redirect /auth-callback?code=…
Frontend →  POST /api/auth/google
Backend  →  Google token endpoint (code + client_secret + redirect_uri)
         →  verify id_token
         →  find User (login) OR find/create User (register)
         →  Admart JWT  OR  404 no_account
```

### 4.1 Request (frontend already sends this)

`POST /api/auth/google`

**Sign in**

```json
{
  "code": "4/0AX4XfWh…",
  "redirectUri": "http://localhost:5173/auth-callback",
  "redirect_uri": "http://localhost:5173/auth-callback",
  "intent": "login",
  "createAccount": false
}
```

**Sign up**

```json
{
  "code": "4/0AX4XfWh…",
  "redirectUri": "http://localhost:5173/auth-callback",
  "redirect_uri": "http://localhost:5173/auth-callback",
  "intent": "register",
  "createAccount": true
}
```

| Field | Required | Notes |
| ----- | -------- | ----- |
| `code` | yes | One-time Google auth code |
| `redirectUri` / `redirect_uri` | yes | Accept either. Must match Google authorize URL + Cloud console |
| `intent` | yes | `login` or `register` |
| `createAccount` | yes | `true` only on Sign up. Treat as `login` if both missing (safe default: do not create) |

Default if `intent` / `createAccount` omitted: **login** (do not create).

### 4.2 After Google identity is verified

Look up `User` by Google `sub`, else by verified email.

| `intent` | User exists | User missing |
| -------- | ----------- | ------------ |
| `login` (`createAccount: false`) | Issue JWT | **404** `no_account`. **Do not create.** |
| `register` (`createAccount: true`) | Issue JWT (same as login) **or** `409` `{ "code": "account_exists" }` | Create user, store `sub`, `email_verified=true` if Google says so, then JWT |

One `User` per verified email. If they registered with password then later Google the same email → link, do not duplicate.

### 4.3 Steps

1. Reject if `code` is missing (`400`).
2. `POST https://oauth2.googleapis.com/token` with `code`, `client_id`, `client_secret` (server only), `redirect_uri` from the request, `grant_type=authorization_code`.
3. Read `id_token` from Google.
4. Verify `id_token`: JWKS signature, `iss`, `aud` = web client id, `exp`.
5. Require `email_verified === true`. Else `400`.
6. Lookup by `sub`, else email.
7. Apply §4.2 (login vs register). **This is the bug to fix.**
8. Return Admart SimpleJWT — **same shape as email login**. Discard Google tokens.

### 4.4 Env

```
GOOGLE_OAUTH_CLIENT_ID=      # same as frontend VITE_GOOGLE_CLIENT_ID
GOOGLE_OAUTH_CLIENT_SECRET=  # server only — never in the frontend
```

Google Cloud authorized redirect URIs:

```
http://localhost:5173/auth-callback
http://127.0.0.1:5173/auth-callback
https://<production-frontend>/auth-callback
```

Optional later (Android/iOS): same endpoint also accepts `{ "idToken": "…" }`. If present, skip code exchange and verify the JWT.

### 4.5 Errors

| Case | HTTP | Body |
| ---- | ---- | ---- |
| Missing `code` | `400` | `{ "message": "Missing authorization code." }` |
| Bad / expired / used code | `400` | `{ "message": "Google sign-in failed." }` |
| Google email not verified | `400` | `{ "message": "Google email is not verified." }` |
| Sign in, no Admart user | **`404`** | `{ "code": "no_account", "message": "There is no Admart account for this email. Please sign up first, then sign in." }` |
| Server misconfig | `500` | generic message; log details |

**Never 401** on this route.

---

## 5. Email login (same product rule)

`POST /api/auth/login` already cannot create a user.

If the email has **no** `User` row:

```json
HTTP 404
{ "code": "no_account", "message": "There is no Admart account for this email. Please sign up first, then sign in." }
```

Wrong password: keep **401**. Do not say “no account” for a bad password.

`POST /api/auth/register` is the only email path that creates a user.

---

## 6. How to verify (backend)

1. **Google Sign in** with a Gmail that has **no** Admart `User` → 404 `no_account`. No new row in the DB.
2. **Google Sign up** with that same Gmail → 200 + JWT + new `User` (store Google `sub`).
3. **Google Sign in** again with that Gmail → 200 + JWT. No second user.
4. **Email login** with an unknown address → 404 `no_account`.
5. **Email login** with a real user + wrong password → 401.
6. Failed / reused Google `code` → 400, not 401.

Web UI already shows “No account found” + Sign up first when it gets that 404.

---

## 7. Later (not this ticket)

### Facebook / Apple login

```
POST /api/auth/facebook  { "accessToken": "…" }
POST /api/auth/apple     { "identityToken": "…" }
```

Same JWT contract. Do not mix Facebook **Login** with Facebook **Publish** (Page tokens live on `SocialAccount`).

If iOS offers Google/Facebook, Apple typically requires **Sign in with Apple**.

### Email verification

Parallel to password reset:

1. `register` → `email_verified=false` + one-time token/code (TTL 15–60 min).
2. `POST /api/auth/verify-email`
3. Until verified: block generation, credits, publish.
4. `POST /api/auth/resend-verification` rate-limited (e.g. 1/min, 5/hour).

SMTP: Gmail for local; Resend / Postmark / SES in production. Google users: `email_verified=true` only if Google asserts it.

---

## 8. Security baseline

- Hash passwords with Django. Never store plaintext.
- Verify Google tokens **on the server**. Never trust the client.
- `aud` must match our web client id. `client_secret` never leaves the server.
- Rate-limit `login`, `register`, `forgot-password`, `/api/auth/google`.
- HTTPS in staging/prod.
- One user per verified email across providers.
- Refresh rotatable + blacklist on `POST /api/auth/logout`.

---

## 9. Frontend (already shipped — do not wait on it)

- Clerk removed. No Clerk JWT.
- Email → `/api/auth/register` and `/api/auth/login`
- Google → Google authorize → `/auth-callback` → `POST /api/auth/google` with `code`, `redirectUri`, `intent`, `createAccount`
- Session: `localStorage` `accessToken`, `refreshToken`, `user`

Frontend env: `VITE_GOOGLE_CLIENT_ID` = same web client id as `GOOGLE_OAUTH_CLIENT_ID`.

---

## 10. Checklist

**This ticket**

- [x] `POST /api/auth/google` reads `intent` + `createAccount`
- [x] Default missing flags → **login** (do not create)
- [x] Login + missing user → **404** `{ "code": "no_account", "message": "There is no Admart account for this email. Please sign up first, then sign in." }`
- [x] Register + missing user → create + JWT
- [x] No 401 on failed Google exchange (use 400)
- [x] Verify `id_token` (`iss`, `aud`, `exp`, signature)
- [x] Link by verified email; store Google `sub`
- [x] Email login missing user → same 404 `no_account`; wrong password → 401
- [x] Tests / manual checks in §6 pass

**Later**

- [ ] `idToken` on the same Google endpoint for mobile
- [ ] Verify-email + resend + SES/Resend
- [ ] Rate limits
- [ ] `POST /api/auth/facebook` and `POST /api/auth/apple`

---

## 11. Do not

- Verify Clerk JWTs
- Auto-create a user on Google **Sign in**
- Return 401 from `/api/auth/google`
- Put `GOOGLE_OAUTH_CLIENT_SECRET` in the frontend
- Create a second `User` for the same verified email
- Replace Clerk with Firebase Auth
- Ship Facebook/Apple/verify-email in this change

---

*Ship §4 + §5. Web already handles the 404.*
