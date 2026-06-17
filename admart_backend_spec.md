# Admart (Vidify) — Complete Backend Agent Specification

> **Purpose**: This document is the single source of truth for the backend agent. Read every section before writing a single line of code. The frontend is a fully-built React (Vite + Tailwind v4) SPA. Your job is to build the server that powers it.

---

## 1. Project Overview

**App name**: Vidify (marketed as Admart)  
**Type**: AI-powered video creation & social media publishing SaaS  
**Frontend stack**: React 19, React Router v7, Tailwind CSS v4, Vite 8  
**Backend to build**: REST API server (Node.js / Python / any — your choice)  
**Primary AI feature**: Flux Pro image generation model (via Replicate or fal.ai)  

---

## 2. Complete Frontend Anatomy

### 2.1 Application Shell

The app is a client-side SPA with **19 routes** plus a 404. All authenticated routes use a **collapsible sidebar** (`VidifySidebar`) fixed on the left (260px wide, collapses to 72px on dashboard). The sidebar is dark-themed with:

- **Brand logo**: "V" gradient icon + "idify" wordmark
- **4 navigation groups**: Main, Publish, Analyze, Settings
- **Bottom credits widget**: Progress bar showing `42 / 200` credits remaining (gradient fill from `accent-blue` → `accent-violet`)

All authenticated pages share the same topbar: breadcrumb left, search bar center (⌘K shortcut), notifications bell, dark/light toggle, user avatar "E" right.

---

### 2.2 Route Map & Page Details

#### `/` — LandingPage

**Visual**: Full-page marketing site, dark background with glowing blue/violet radial blurs in hero.

**Sections**:
1. **Sticky header** (h-16, backdrop-blur): Logo + nav links (Product, Pricing, Examples, Docs) + "Log in" ghost button + "Get Started Free" gradient CTA
2. **Hero section** (min-h-screen, split layout):
   - Left: Badge pill "AI-Powered Video Creation Platform" with pulsing dot → h1 "Create AI Videos. Publish Everywhere. Instantly." (gradient on "Publish Everywhere.") → subtitle → email capture form + "Start for Free" CTA → "No credit card · 5 free credits · Cancel anytime"
   - Right: 2×2 staggered grid of VideoCards (showcase videos for TikTok / YouTube / Instagram / Facebook)
3. **Stats bar**: 10,000+ Videos Created · 500+ Active Creators · 4 Platforms Supported · 99.9% Uptime
4. **How it works** (3 cards): Type Your Idea → AI Generates → Auto-Publish (numbered 01/02/03 with gradient rings)
5. **Features grid** (6 features): Text to Video, Image to Video, AI Voiceover, Smart Captions, Auto SEO Tags, Cross-Platform Publish
6. **Pricing section** (4 plans): Free $0/5cr · Starter $19/50cr · Pro $49/200cr (most popular) · Agency $99/500cr
7. **CTA banner**: Blue/violet gradient border card
8. **Footer**: 5-column links + copyright

**Backend needs**: Email capture endpoint, pricing tiers data

---

#### `/auth` — AuthPage

**Visual**: Split layout. Left panel = form (520px fixed). Right panel = floating showcase cards with ambient blobs.

**Top**: Floating pill switcher "Sign In / Create Account" (positioned `fixed top-6` center, z-60)

**Sign In tab**:
- Logo + "Welcome back" h1
- "Continue with Google" button (white bg, Google icon SVG)
- Divider "or continue with email"
- Email field (`signin-email`)
- Password field (`signin-password`)
- "Remember me" checkbox + "Forgot password?" link
- "Sign In →" gradient submit button → navigates to `/onboarding`
- "Don't have an account? Sign up free" link

**Create Account tab**:
- Logo + "Create your account" h1 + "Get 5 free credits" copy
- "Continue with Google" button
- First name + Last name (2-column grid)
- Email field (`signup-email`)
- Password field with **live strength meter**: 4 segments (bg-error / bg-warning / bg-success) checking: length ≥8, uppercase, number, special char
- Password strength label (Weak/Medium/Strong)
- "I agree to Terms and Privacy Policy" checkbox
- "Create Account →" gradient submit → navigates to `/onboarding`

**Right panel floating badges**: "1M+ Videos" and "50+ Countries" (sign in) / "10,000+ Videos" and "4 Platforms" (sign up) — `animate-float` CSS

**Backend needs**:
- `POST /auth/register` — email, password, firstName, lastName → creates user with 5 free credits
- `POST /auth/login` — email, password → JWT token
- `POST /auth/google` — OAuth callback
- `POST /auth/forgot-password` → sends reset email
- `POST /auth/reset-password` — token + new password
- `GET /auth/me` — returns current user profile + credits

---

#### `/onboarding` — OnboardingPage

**Visual**: Centered card (max-w-640px) with 3-step stepper at top. Step circles: done=blue filled, active=gradient+ring, future=elevated bg.

**Step 1 — "Where do you publish?"**:
- List of 4 platforms: TikTok, YouTube, Instagram, Facebook (each with colored icon circle, name, description, "Connect" button → toggles to "✓ Connected")
- Skip / Continue buttons

**Step 2 — "Tell us about your brand"**:
- Circular logo upload (dashed border, h-36 w-36)
- Brand name text input
- Industry select: E-commerce, Digital Agency, Content Creator, Education, SaaS, Real Estate, Food, Other
- Brand color: 6 preset swatches (#2563eb, #7c3aed, #10b981, #f59e0b, #ef4444, #ec4899) + custom color picker
- Back / Skip / Continue buttons

**Step 3 — "Let's make something amazing"**:
- Prompt textarea (5 rows, placeholder: "15s product showcase for our new sneaker drop...")
- Template pills: Product Ad (blue), Social Story (violet), Tutorial (green), Testimonial (yellow)
- "✦ Generate My First Video" gradient button → navigates to `/dashboard`
- "Uses 2 credits · You have 5 free credits remaining"
- Back button

**Backend needs**:
- `POST /onboarding/complete` — saves: connected platforms, brand name, industry, brand color hex, initial prompt/template
- `GET /users/:id/brand-kit` — returns onboarding data for brand kit page
- Social OAuth connect: TikTok, YouTube, Instagram, Facebook accounts linked via OAuth

---

#### `/dashboard` — DashboardPage

**Visual**: Dark panel sidebar (collapsible) + main content area. Has light/dark theme toggle (CSS class swap).

**Sidebar (inline duplicate of VidifySidebar)**:
- Collapse toggle → sidebar narrows from 260px to 72px (icons only), content `ml` animates
- Credits widget adapts: expanded = horizontal bar + "42/200", collapsed = vertical bar + "42" monospace

**Topbar**:
- Breadcrumb: "Dashboard / Home"
- Search bar (center, hidden on mobile) → opens modal on click or ⌘K
- Search modal: full-screen blur overlay + centered input box "Search videos, templates..."
- Notifications bell (red dot badge)
- Dark/light toggle 🌙/☀️
- Avatar "E"

**Hero welcome banner** (gradient-bg with floating ✦ icon):
- "Good morning, Ehtisham 👋" (personalised with user name)
- "42 credits remaining"
- 3 action buttons: "✦ New Video" → /create · "⊕ New Image" → /create · "↑ Upload" → /create

**Stats cards** (4-up grid, 2-col sm → 4-col xl):
| Label | Value | Trend | Icon | Sparkline |
|---|---|---|---|---|
| Credits Remaining | 42 | ↓ 158 used | ✦ | blue bars |
| Videos This Month | 18 | ↑ +3 | ▶ | green bars |
| Total Views | 124K | ↑ +12% | ◎ | violet bars |
| Scheduled Posts | 7 | ↑ +2 | ⌚ | yellow bars |

**Recent Videos section**:
- Filter pills: All · Published · Ready · Scheduled · Generating
- 3-col grid of video cards (aspect-video gradient thumbnail, status badge, duration, platform dots, date)
- Status badges: Published (blue) · Generating (violet+pulse) · Ready (green) · Scheduled (yellow) · Failed (red)
- Platform dots: T=TikTok cyan · Y=YouTube red · I=Instagram orange · F=Facebook blue
- Click → navigates to `/result`

**Quick Actions** (3 cards):
- 🔥 Trending Templates → /templates
- ⚡ Connect Instagram → /social
- 📈 View Analytics → /analytics

**Backend needs**:
- `GET /dashboard/stats` — credits_remaining, videos_this_month, total_views, scheduled_posts, sparkline arrays
- `GET /videos?status=&page=&limit=` — paginated video list with status filter
- `GET /videos/recent?limit=6` — last 6 videos

---

#### `/create` — WizardPage (4-step video creation wizard)

**Visual**: Full-page flow without sidebar. Fixed header (Back ← · "Create New Video") + step progress bar + main content + right sidebar panel + footer navigation.

**Step progress bar**: 4 steps (Input · Configure · Enhance · Generate), current=ring+violet, done=✓+blue, future=gray

**Right sidebar (always visible)**: Shows current settings (Mode/Ratio/Duration/Style/Model/Music/Captions) + large cost estimate display (gradient number) + progress bar (totalCredits/creditsRemaining) + "X credits remaining after" + Tips box

**Footer**: "💎 X credits · Save as Draft" left | Back + Continue / Generate Video right

---

**Step 1 — Input**:

Three tab modes:

1. **Text to Video** tab:
   - "Describe your video" h2
   - Textarea (min-h-180, 1000 char limit, counter bottom-left)
   - "✦ Enhance with AI" button (violet, top-right of textarea area)
   - Quick suggestion chips: cinematic transitions, slow motion close-ups, text overlays, product showcase, upbeat music, CTA ending, voiceover

2. **Image to Video** tab:
   - Drag-and-drop upload zone (dashed border, PNG/JPG up to 20MB)
   - "Animation direction" textarea (pan left, subtle zoom, parallax depth…)

3. **From Template** tab:
   - 2×3 grid of template buttons: Product Ad, Social Story, Tutorial, Testimonial, Promo, Announcement

---

**Step 2 — Configure**:

- **Aspect ratio** (4 options): 9:16 📱 TikTok · 16:9 🖥 YouTube · 1:1 ⬛ Feed · 4:5 🖼 Instagram
- **Duration** (slider 5–60s, ticks at 5/15/30/45/60)
- **Visual style** (6 options): Cinematic, Minimal, Dynamic, Corporate, Artistic, Custom
- **AI model** (3 options with speed dots):
  - Mochi Fast — 1 credit — 3/3 speed dots
  - CogVideoX Quality — 2 credits — 2/3 speed dots
  - Wan 2.1 Premium — 4 credits — 1/3 speed dots
- **Toggle switches** (Voiceover / Background Music / Auto Captions)

---

**Step 3 — Enhance (SEO/Metadata)**:

- Video title input + "↻ Regenerate" button (randomizes title)
- Per-platform description tabs (TikTok / YouTube / Instagram / Facebook), each with textarea (500 char limit)
- Tags: editable chips with × remove + "+" add input (Enter to add)
- Thumbnail picker: 2 AI-generated thumbnails + custom upload slot

---

**Step 4 — Generate (Review)**:

- Summary table: Mode, Aspect ratio, Duration, Style, Model, Voiceover, Background music, Auto captions, Title
- Cost breakdown:
  - Video: `modelCredits` credits
  - Captions: 0.5 credits (if on)
  - Thumbnail: 0.5 credits
  - **Total**: sum
- "~45 seconds" estimate badge + "You have X credits" green text
- Footer: "✦ Generate Video" violet button → navigates to `/progress`

**Backend needs**:
- `POST /videos/generate` — body: `{prompt, mode, aspectRatio, duration, style, model, voiceover, bgMusic, autoCaptions, title, platformDescriptions, tags, thumbnailIndex, templateId}`
  - Deducts credits
  - Creates video job
  - Returns `{jobId, estimatedSeconds}`
- `POST /prompts/enhance` — body: `{prompt}` → returns enhanced prompt string
- `POST /thumbnails/generate` — generates 2 thumbnail options via AI
- `POST /videos/draft` — saves draft without generating

---

#### `/progress` — ProgressPage

**Visual**: Centered card (max-w-600px). Ambient blobs + floating particle dots background.

**Circular progress ring** (160×160 SVG, gradient stroke blue→violet):
- Center: "XX%" large + "Generating" label below
- Animates from 0→100 via `setInterval` (~400ms ticks)

**Stage pill**: Live stage label with pulsing blue dot

**Stage pipeline** (6 stages in horizontal row):
1. Analyzing Prompt (active at <10%)
2. Generating Frames (active at 10–40%)
3. Rendering Video (active at 40–65%)
4. Adding Music (active at 65–78%)
5. Burning Captions (active at 78–90%)
6. Encoding Output (active at 90–100%)

Done stages = green ✓, active = blue, future = gray.

**Stats row** (3 cards): Time left countdown · Queue position (#1) · Duration (15s)

**Frame preview strip** (5 aspect-video boxes): shimmer placeholders → loads gradient fill progressively at 30/45/60/75/88% thresholds

**Buttons**: "Cancel Generation" (red outline) · "🔔 Notify when ready" (toggleable)

**Success modal** (shown at 100%+0.8s delay): 🎉 "Your video is ready!" + preview thumbnail → "View & Publish Video →" → /result

**Backend needs**:
- `GET /jobs/:jobId/status` — returns `{percentage, stage, framesReady, queuePosition, estimatedSecondsLeft}`
  - Frontend polls this or subscribes via WebSocket/SSE
- `POST /jobs/:jobId/cancel` — cancels job, refunds credits
- WebSocket or SSE endpoint: `GET /jobs/:jobId/stream` — real-time progress events

---

#### `/result` — ResultPage

**Visual**: Full-height layout (no sidebar). Header + two-panel (main video left, metadata right) + action footer.

**Header** (h-60px):
- Back ← → /dashboard
- "Video Result" h1
- "✓ Ready" green badge
- Version selector dropdown (Version 1/2/3)

**Main panel (left)**:
- Large video player (aspect-video, max-w-800px) with:
  - Gradient thumbnail overlay
  - Caption overlay: "Summer Product Launch 2024"
  - Play/Pause toggle button (center, frosted glass)
  - Progress bar (draggable, gradient fill, white dot scrubber)
  - Controls bar: Play · Rewind · "0:05 / 0:15" · Volume slider · Speed "1x" · Fullscreen
- Video metadata chips below: "Format MP4 · Quality 1080p · Size 8.4MB · Duration 0:15 · Ratio 16:9"
- Action buttons: "Download MP4" · "Download Thumbnail"

**Right sidebar (380px)**:
- **Title** field (editable) + "Regenerate" button
- **Description**: Platform tab switcher (TikTok/YouTube/Instagram/Facebook, each with platform-colored bg when active) + textarea (2200 char limit)
- **Tags**: removable chips + "+ Add" button
- **Platform preview** (mini phone mockup, max-w-220px):
  - Platform tabs: TikTok/YouTube/Instagram/Facebook
  - Phone frame with avatar "@vidify_brand", "Follow" button
  - 9:14 aspect video area with gradient + caption overlay
  - Engagement stats: ❤️ 2.4K · 💬 142 · ↗ 890

**Footer**:
- 🚀 Publish Now → /publish
- 📅 Schedule → /publish
- ↓ Download
- ↻ Regenerate
- 🗑 Delete (red, right side)

**Backend needs**:
- `GET /videos/:id` — full video details: url, thumbnail, duration, format, quality, size, ratio, title, descriptions, tags, status
- `PUT /videos/:id` — update title, descriptions, tags
- `GET /videos/:id/download` — signed download URL
- `DELETE /videos/:id` — soft delete, refund if applicable
- `POST /videos/:id/regenerate` — creates new version, deducts credits
- `POST /videos/:id/metadata/regenerate` — regenerates title/description/tags via AI (LLM call)

---

#### `/publish` — PublishingPage

**Visual**: Full-height, no sidebar. Header + two-panel (left preview/platform list, right schedule settings).

**Header**: Back ← → /result · "Publish Video"

**Left panel (360px)**:
- Video preview card (aspect-video gradient + play button + title + metadata chips)
- "Publishing to" section: 4 platform rows (each: icon, name, handle, toggle switch)
  - TikTok ✓ connected
  - YouTube ✓ connected
  - Instagram ✓ connected
  - Facebook ✗ "Not connected" → toggle disabled
- "Platform previews" row: thumbnail strips per connected platform

**Main panel**:
- **Schedule section**: Radio buttons:
  - 🚀 Publish Now
  - 📅 Schedule for Later → reveals Date + Time + Timezone (UTC/NY/London/Tokyo) grid
- **Per-platform settings** (accordion expandable):
  - **TikTok**: Caption textarea (120/2200) · Privacy (Public/Friends/Private) · Comments (Everyone/Friends/Off)
  - **YouTube**: Title input · Description textarea · Visibility (Public/Unlisted/Private) · Category dropdown
  - **Instagram**: Caption textarea · Post type (Reel/Feed/Story)
  - **Facebook**: "Not connected" banner → link to Settings

**Footer**:
- Active platforms colored dots + "Publishing to X platforms"
- "Save as Draft" ghost button
- "🚀 Publish Now" gradient button → opens confirmation modal

**Confirmation modal**:
- Lists selected platforms with handles
- Cancel / "🚀 Publish Now" gradient
- On confirm → "✅ Published to 3 platforms successfully!" toast (bottom center) → auto-redirect to /dashboard after 1.8s

**Backend needs**:
- `POST /videos/:id/publish` — body: `{platforms: [{id, caption, privacy, visibility, category, postType}], scheduleAt: ISO8601 | null}`
- `GET /publishing/jobs/:jobId` — status of publish job per platform
- `POST /social/connect/:platform` — OAuth flow to connect TikTok/YouTube/Instagram/Facebook
- `DELETE /social/disconnect/:platform`
- `GET /social/accounts` — list of connected accounts with status

---

#### `/library` — LibraryPage

**Visual**: Uses VidifySidebar. Full video library with search, filter, sort, grid/list view toggle.

**Backend needs**:
- `GET /videos?q=&status=&platform=&page=&limit=&sort=` — full filterable library
- `DELETE /videos/:id` — delete video
- `POST /videos/:id/duplicate`

---

#### `/templates` — TemplatesPage

**Visual**: Uses VidifySidebar. Browse template library by category.

**Backend needs**:
- `GET /templates?category=&sort=` — list templates
- `GET /templates/:id` — template detail
- `POST /templates/:id/use` — creates wizard pre-filled with template

---

#### `/social` — SocialAccountsPage

**Visual**: Uses VidifySidebar. Shows all connected/disconnected social accounts.

**Backend needs**:
- `GET /social/accounts`
- `POST /social/connect/:platform` — OAuth initiate
- `GET /social/callback/:platform` — OAuth callback
- `DELETE /social/accounts/:id`

---

#### `/calendar` — CalendarPage

**Visual**: Uses VidifySidebar. Monthly calendar view with scheduled posts.

**Backend needs**:
- `GET /schedule?month=&year=` — returns scheduled posts per day
- `POST /schedule` — create/update scheduled post time
- `DELETE /schedule/:id`

---

#### `/analytics` — AnalyticsPage

**Visual**: Uses VidifySidebar. Comprehensive analytics dashboard.

**Header controls**:
- Date range pills: 7d · 30d · 90d · All time
- Platform filter dropdown
- "↓ Export CSV" button

**Stats cards** (4-up): Total Views (124K +18.2%) · Total Engagement (8.4K +12.5%) · Videos Published (18 +3) · Avg Engagement Rate (4.8% -0.3%) — each with 15-bar sparkline

**Charts**:
- **Line chart** (SVG, custom-drawn): Views over time, 4 platform series (TikTok cyan, YouTube red, Instagram orange, Facebook blue), y-axis 0K–24K, x-axis Apr 1–28
- **Donut chart** (SVG): Platform distribution — TikTok 44%, YouTube 31%, Instagram 18%, Facebook 8% — center total "124K total views"

**Engagement Breakdown**: 12-month stacked bar chart (likes=blue, comments=violet, shares=green)

**Top Performing Videos table** (8 columns): Video thumbnail+title · Platform · Views · Likes · Comments · Shares · Engagement Rate bar · Published date

**Backend needs**:
- `GET /analytics/overview?dateRange=&platform=` — all KPIs + sparklines
- `GET /analytics/views-over-time?dateRange=&platform=` — time series per platform
- `GET /analytics/platform-distribution?dateRange=` — donut segments
- `GET /analytics/engagement-breakdown?year=` — monthly stacked data
- `GET /analytics/top-videos?dateRange=&platform=&limit=` — top performers table
- `GET /analytics/export.csv?dateRange=&platform=` — CSV download

---

#### `/image-gen` — ImageGenPage ⭐ PRIMARY AI FEATURE

**Visual**: Uses VidifySidebar. Two-panel layout (left=controls 400px, right=results flex-1).

**Topbar**: "AI Image Generator" h1 + "✦ AI Powered" violet badge + user avatar

**Left panel (controls)**:

1. **Prompt** section:
   - Textarea (min-h-120, 500 char limit, counter bottom-right)
   - "▸ Add negative prompt" toggle → reveals exclusion textarea

2. **Model** selection (2-column grid):
   - **SDXL** — "Fast · Great quality" — 0.5 cr/image
   - **Flux Pro** — "Best quality · Photorealistic" — 1 cr/image
   - Active: blue border + blue/10 bg; inactive: default border

3. **Size / Ratio** (5-column grid):
   - 1:1 Feed · 16:9 YouTube · 9:16 TikTok · 4:5 Instagram · ⊡ Custom
   - Active: blue border + blue/10 bg

4. **Style Preset** (wrap chips, rounded-full):
   - Photorealistic · Cinematic · 3D Render · Illustration · Flat Design · Minimalist · Vintage · Neon Glow
   - Active: violet border + violet/15 bg + violet text

5. **Number of Images**: 1 · 2 · 3 · 4 (square toggle buttons, active=blue)

**Bottom sticky bar** (left panel):
- "✦ Generate Images" gradient button (disabled when no prompt or generating)
- "X images × Y credits = Z credits" summary line in mono font

**Right panel (results)**:

- **Empty state**: 🖼️ icon (64px, 20% opacity) + "No images yet" + "Describe what you want to create..."
- **Generating state**: 2-col grid of shimmer placeholders (spinning violet ring + "Generating..." text)
- **Results grid**: 2-col grid of generated images:
  - Hover overlay: frosted glass buttons "↓ Download" · "→ Use in Video" (→/create) · "🖼 Set Thumbnail"
  - Below each image: truncated prompt text
- **Recent Generations strip**: 8 small thumbnails (h-14 w-14) horizontally scrollable

**Current frontend behavior** (mock): Uses `setTimeout(2200ms)` to simulate generation, then renders gradient placeholder cards. The backend replaces this with real Flux API calls.

**Backend needs** (detailed in Section 5):
- `POST /images/generate` — real Flux Pro API call
- `GET /images/jobs/:jobId/status` — poll status
- `GET /images` — history
- `DELETE /images/:id`

---

#### `/billing` — BillingPage

**Visual**: Uses VidifySidebar. Subscription management.

**Backend needs**:
- `GET /billing/subscription` — current plan, credits, renewal date
- `POST /billing/upgrade` — change plan (Stripe integration)
- `GET /billing/invoices` — invoice history
- `POST /billing/credits/purchase` — buy additional credits

---

#### `/settings` — SettingsPage

**Visual**: Uses VidifySidebar. Multi-section settings with sidebar sub-navigation.

**Backend needs**:
- `GET /users/me` — profile data
- `PUT /users/me` — update name, email, password, avatar
- `PUT /users/me/notifications` — notification preferences
- `DELETE /users/me` — account deletion

---

#### `/brand-kit` — BrandKitPage

**Visual**: Uses VidifySidebar. Brand identity management.

**Backend needs**:
- `GET /brand-kit` — logo URL, colors, fonts, templates
- `PUT /brand-kit` — update brand kit
- `POST /brand-kit/logo` — upload logo (multipart)

---

#### `/notifications` — NotificationsPage

**Visual**: Uses VidifySidebar. 6 unread notifications (red badge on sidebar).

**Backend needs**:
- `GET /notifications?unread=` — notification list
- `PUT /notifications/:id/read`
- `PUT /notifications/read-all`
- `DELETE /notifications/:id`

---

#### `/progress`, `/result`, `/publish` — The Video Pipeline

These three pages form the end-to-end video generation and publishing flow:
```
/create (wizard) → /progress (job status) → /result (review) → /publish (publish)
```

---

## 3. Data Models

### 3.1 User
```json
{
  "id": "uuid",
  "email": "string",
  "firstName": "string",
  "lastName": "string",
  "avatarUrl": "string | null",
  "googleId": "string | null",
  "passwordHash": "string | null",
  "createdAt": "ISO8601",
  "updatedAt": "ISO8601",
  "plan": "free | starter | pro | agency",
  "creditsTotal": 200,
  "creditsUsed": 158,
  "creditsRemaining": 42,
  "creditsResetAt": "ISO8601",
  "onboardingCompleted": true,
  "brandKit": {
    "brandName": "Acme Co.",
    "industry": "E-commerce",
    "brandColorHex": "#2563eb",
    "logoUrl": "string | null"
  }
}
```

### 3.2 Video
```json
{
  "id": "uuid",
  "userId": "uuid",
  "title": "Summer Drop — Teaser",
  "prompt": "string",
  "mode": "text | image | template",
  "status": "draft | generating | processing | ready | published | scheduled | failed",
  "aspectRatio": "9:16 | 16:9 | 1:1 | 4:5",
  "duration": 15,
  "style": "Cinematic | Minimal | Dynamic | Corporate | Artistic | Custom",
  "model": "mochi | cog | wan",
  "voiceover": false,
  "bgMusic": true,
  "autoCaptions": true,
  "videoUrl": "string | null",
  "thumbnailUrl": "string | null",
  "fileSizeMb": 8.4,
  "quality": "720p | 1080p | 4K",
  "format": "mp4",
  "creditsCost": 3,
  "templateId": "string | null",
  "jobId": "uuid",
  "platformDescriptions": {
    "tiktok": "string",
    "youtube": "string",
    "instagram": "string",
    "facebook": "string"
  },
  "tags": ["skincare", "launch", "2026"],
  "publishedAt": "ISO8601 | null",
  "scheduledAt": "ISO8601 | null",
  "platforms": ["tiktok", "youtube"],
  "createdAt": "ISO8601",
  "updatedAt": "ISO8601",
  "versions": [{"versionNumber": 1, "videoUrl": "...", "createdAt": "..."}]
}
```

### 3.3 GeneratedImage
```json
{
  "id": "uuid",
  "userId": "uuid",
  "jobId": "uuid",
  "prompt": "string",
  "negativePrompt": "string | null",
  "model": "sdxl | flux",
  "aspectRatio": "1:1 | 16:9 | 9:16 | 4:5",
  "style": "Photorealistic | Cinematic | 3D Render | Illustration | Flat Design | Minimalist | Vintage | Neon Glow",
  "imageUrl": "string",
  "thumbnailUrl": "string",
  "creditsCost": 1,
  "usedInVideoId": "uuid | null",
  "createdAt": "ISO8601"
}
```

### 3.4 Job
```json
{
  "id": "uuid",
  "userId": "uuid",
  "type": "video_generation | image_generation | publish",
  "status": "queued | processing | completed | failed | cancelled",
  "percentage": 67,
  "currentStage": "Generating Frames",
  "entityId": "uuid",
  "externalJobId": "string",
  "errorMessage": "string | null",
  "estimatedSecondsLeft": 30,
  "queuePosition": 1,
  "createdAt": "ISO8601",
  "updatedAt": "ISO8601"
}
```

### 3.5 SocialAccount
```json
{
  "id": "uuid",
  "userId": "uuid",
  "platform": "tiktok | youtube | instagram | facebook",
  "handle": "@vidify_brand",
  "displayName": "Vidify Brand",
  "accessToken": "encrypted",
  "refreshToken": "encrypted",
  "tokenExpiresAt": "ISO8601",
  "connected": true,
  "avatarUrl": "string | null",
  "createdAt": "ISO8601"
}
```

### 3.6 AnalyticsRecord
```json
{
  "id": "uuid",
  "videoId": "uuid",
  "userId": "uuid",
  "platform": "tiktok | youtube | instagram | facebook",
  "date": "YYYY-MM-DD",
  "views": 42100,
  "likes": 2100,
  "comments": 412,
  "shares": 890,
  "engagementRate": 6.2,
  "impressions": 80000
}
```

### 3.7 Plan/Credit Tiers
```json
{
  "free":    { "creditsPerMonth": 5,   "price": 0,  "videoQuality": "720p",  "connectedAccounts": 1 },
  "starter": { "creditsPerMonth": 50,  "price": 19, "videoQuality": "1080p", "connectedAccounts": 3 },
  "pro":     { "creditsPerMonth": 200, "price": 49, "videoQuality": "4K",    "connectedAccounts": -1 },
  "agency":  { "creditsPerMonth": 500, "price": 99, "videoQuality": "4K",    "connectedAccounts": -1 }
}
```

---

## 4. Authentication & Authorization

### 4.1 Strategy
- JWT Bearer tokens (access token 15min + refresh token 7d)
- Google OAuth 2.0
- All routes except `/auth/*` and `/` require `Authorization: Bearer <token>` header

### 4.2 Endpoints
```
POST   /auth/register          — email + password signup, creates user with 5 free credits
POST   /auth/login             — email + password → {accessToken, refreshToken, user}
POST   /auth/google            — {code} → same response
POST   /auth/refresh           — {refreshToken} → new accessToken
POST   /auth/logout            — invalidates refresh token
POST   /auth/forgot-password   — {email} → sends reset link
POST   /auth/reset-password    — {token, newPassword}
GET    /auth/me                — returns user object with credits
```

---

## 5. ⭐ Flux AI Image Generation — Critical Feature

### 5.1 Overview

The **ImageGenPage** (`/image-gen`) is the primary AI feature. The frontend currently mocks generation with a 2.2-second timeout. The backend must replace this with **real Flux Pro** image generation.

**Flux Pro** is available via:
- **Replicate API** (recommended): `https://api.replicate.com/v1/predictions` using model `black-forest-labs/flux-pro` or `black-forest-labs/flux-1.1-pro`
- **fal.ai**: `https://fal.run/fal-ai/flux-pro` (faster, simpler)
- **Together AI**: `black-forest-labs/FLUX.1-pro`

### 5.2 API Flow

**Frontend calls**: `POST /images/generate`

**Request body**:
```json
{
  "prompt": "A minimalist product shot of a skincare bottle on white marble...",
  "negativePrompt": "blurry, low quality, ...",
  "model": "flux",
  "aspectRatio": "1:1",
  "style": "Photorealistic",
  "count": 2
}
```

**Backend flow**:
1. Validate user has enough credits (`count × model_cost`)
2. Deduct credits optimistically
3. Build Flux prompt: prepend style modifier to user prompt
   - "Photorealistic" → `"photorealistic, ultra-detailed, 8K quality, {prompt}"`
   - "Cinematic" → `"cinematic film still, dramatic lighting, anamorphic lens, {prompt}"`
   - "3D Render" → `"3D render, octane render, ray tracing, photorealistic materials, {prompt}"`
   - "Illustration" → `"digital illustration, concept art, {prompt}"`
   - "Flat Design" → `"flat design, vector art, clean shapes, {prompt}"`
   - "Minimalist" → `"minimalist, clean composition, lots of whitespace, {prompt}"`
   - "Vintage" → `"vintage photography, film grain, retro color grading, {prompt}"`
   - "Neon Glow" → `"neon glow, cyberpunk aesthetic, neon lights, {prompt}"`
4. Map aspect ratio to pixel dimensions:
   - `1:1` → `1024×1024`
   - `16:9` → `1344×768`
   - `9:16` → `768×1344`
   - `4:5` → `896×1120`
5. Call Flux API (create `count` separate requests in parallel)
6. Save job record to DB
7. Return `{jobId}` immediately

**Response**: `{jobId: "uuid"}`

### 5.3 Flux API Call (via Replicate)

```http
POST https://api.replicate.com/v1/predictions
Authorization: Token REPLICATE_API_TOKEN
Content-Type: application/json

{
  "version": "black-forest-labs/flux-1.1-pro",
  "input": {
    "prompt": "photorealistic, ultra-detailed, ...",
    "negative_prompt": "...",
    "width": 1024,
    "height": 1024,
    "num_outputs": 1,
    "guidance_scale": 3.5,
    "num_inference_steps": 28,
    "output_format": "webp",
    "output_quality": 90
  }
}
```

### 5.4 Status Polling

**Frontend polls**: `GET /images/jobs/:jobId/status`

**Backend response**:
```json
{
  "status": "starting | processing | succeeded | failed",
  "percentage": 65,
  "images": [
    {
      "id": "uuid",
      "url": "https://your-storage/...",
      "thumbnailUrl": "https://your-storage/...",
      "prompt": "...",
      "style": "Photorealistic"
    }
  ],
  "error": null
}
```

Backend polls Replicate's prediction status:
```http
GET https://api.replicate.com/v1/predictions/{prediction_id}
Authorization: Token REPLICATE_API_TOKEN
```

When `status === "succeeded"`, download output images, upload to your storage (S3/Cloudflare R2/Supabase Storage), save `GeneratedImage` records, return final URLs.

### 5.5 All Image Generation Endpoints

```
POST   /images/generate           — start generation job
GET    /images/jobs/:jobId/status — poll progress + get image URLs when done
GET    /images                    — user's image history (paginated)
GET    /images/:id                — single image details
DELETE /images/:id                — delete image
POST   /images/:id/use-in-video   — mark image as used in video, get reference URL
POST   /images/:id/download       — generate signed download URL
```

### 5.6 SDXL Fallback

If model = "sdxl", use Replicate's `stability-ai/sdxl` model:
- Cost: 0.5 credits/image
- Faster, slightly lower quality
- Input schema similar to Flux

### 5.7 Credit Deduction Rules

| Model | Cost per image |
|---|---|
| SDXL | 0.5 credits |
| Flux Pro | 1.0 credit |

If generation fails, refund credits immediately.

---

## 6. Video Generation Pipeline

> Note: Full video AI is complex. The frontend is built for it, but you may start with a placeholder pipeline and progressively integrate real video AI models.

### 6.1 Models & Credit Costs

| Model ID | Name | Credits | Suggested API |
|---|---|---|---|
| `mochi` | Mochi Fast | 1 cr | Replicate `genmo/mochi-1-preview` |
| `cog` | CogVideoX Quality | 2 cr | Replicate `cogvideox-5b` |
| `wan` | Wan 2.1 Premium | 4 cr | WanVideo API |

Additional costs:
- Auto Captions: +0.5 cr (Whisper API)
- Thumbnail: +0.5 cr (Flux generation)
- Background Music: included

### 6.2 Video Generation Flow

```
POST /videos/generate
  → validate credits
  → create Video record (status=generating)
  → create Job record
  → if mode=text: POST to video AI API
  → if mode=image: POST source image + animation direction to img2vid API
  → if mode=template: load template + apply prompt
  → poll AI status via background job runner
  → on completion: download video, upload to storage, update Video record
  → if autoCaptions: run Whisper transcription, burn in captions
  → if thumbnail: generate thumbnail via Flux
  → mark Video as ready
  → send WebSocket/SSE event to frontend
```

### 6.3 Job Status Stages

Map AI progress to these stage names (shown on `/progress`):
1. `Analyzing Prompt` — validating input, calling AI
2. `Generating Frames` — AI model generating frames
3. `Rendering Video` — assembling video
4. `Adding Music` — mixing background audio
5. `Burning Captions` — Whisper + ffmpeg
6. `Encoding Output` — final MP4 encoding, uploading to storage

---

## 7. Publishing Pipeline

### 7.1 Platform APIs

```
TikTok:    TikTok for Developers - Content Posting API v2
YouTube:   YouTube Data API v3 - videos.insert
Instagram: Instagram Graph API - Media + Publish
Facebook:  Facebook Graph API - Video Upload
```

### 7.2 Publish Endpoint

```
POST /videos/:id/publish
Body: {
  "platforms": [
    {
      "platform": "tiktok",
      "caption": "POV: your summer launch...",
      "privacy": "PUBLIC",
      "allowComments": "EVERYONE"
    },
    {
      "platform": "youtube",
      "title": "Summer Product Launch 2024",
      "description": "...",
      "visibility": "public",
      "categoryId": "26"
    },
    {
      "platform": "instagram",
      "caption": "Summer glow, unlocked...",
      "postType": "REELS"
    }
  ],
  "scheduleAt": null
}
```

### 7.3 OAuth Flows

Each platform requires user OAuth authorization to get access tokens:

```
GET  /social/connect/tiktok      → redirect to TikTok OAuth
GET  /social/callback/tiktok     → exchange code for tokens, save to DB
GET  /social/connect/youtube     → redirect to Google OAuth (YouTube scope)
GET  /social/callback/youtube    → exchange code for tokens
GET  /social/connect/instagram   → redirect to Meta OAuth (Instagram scope)
GET  /social/callback/instagram  → exchange code for tokens
GET  /social/connect/facebook    → redirect to Meta OAuth (Pages scope)
GET  /social/callback/facebook   → exchange code for tokens
DELETE /social/accounts/:id      → revoke tokens + delete account
```

---

## 8. Complete API Endpoint Reference

### 8.1 Auth
```
POST   /auth/register
POST   /auth/login
POST   /auth/google
POST   /auth/refresh
POST   /auth/logout
POST   /auth/forgot-password
POST   /auth/reset-password
GET    /auth/me
```

### 8.2 Users
```
GET    /users/me
PUT    /users/me
PUT    /users/me/password
PUT    /users/me/avatar         (multipart)
DELETE /users/me
GET    /users/me/credits
```

### 8.3 Onboarding
```
POST   /onboarding/complete
GET    /onboarding/status
```

### 8.4 Dashboard
```
GET    /dashboard/stats
```

### 8.5 Videos
```
GET    /videos                  ?q=&status=&platform=&page=&limit=&sort=
POST   /videos/generate
POST   /videos/draft
GET    /videos/recent           ?limit=
GET    /videos/:id
PUT    /videos/:id
DELETE /videos/:id
POST   /videos/:id/regenerate
POST   /videos/:id/duplicate
POST   /videos/:id/publish
GET    /videos/:id/download
POST   /videos/:id/metadata/regenerate
GET    /videos/:id/versions
```

### 8.6 Jobs
```
GET    /jobs/:jobId/status
POST   /jobs/:jobId/cancel
GET    /jobs/:jobId/stream      (SSE)
```

### 8.7 Images (⭐ Flux Feature)
```
POST   /images/generate
GET    /images/jobs/:jobId/status
GET    /images                  ?page=&limit=
GET    /images/:id
DELETE /images/:id
POST   /images/:id/use-in-video
GET    /images/:id/download
```

### 8.8 Prompts / AI Assist
```
POST   /prompts/enhance         — {prompt} → enhanced prompt (LLM)
POST   /titles/generate         — {videoId | prompt} → title suggestions
POST   /descriptions/generate   — {videoId, platform} → platform description
POST   /tags/generate           — {videoId | prompt, platform} → hashtag suggestions
```

### 8.9 Templates
```
GET    /templates               ?category=&sort=&limit=
GET    /templates/:id
POST   /templates               (admin only)
POST   /templates/:id/use
```

### 8.10 Social Accounts
```
GET    /social/accounts
GET    /social/connect/:platform
GET    /social/callback/:platform
DELETE /social/accounts/:id
POST   /social/accounts/:id/refresh  — refresh access token
```

### 8.11 Publishing Schedule
```
GET    /schedule                ?month=&year=&platform=
POST   /schedule
PUT    /schedule/:id
DELETE /schedule/:id
```

### 8.12 Analytics
```
GET    /analytics/overview          ?dateRange=7d|30d|90d|all&platform=
GET    /analytics/views-over-time   ?dateRange=&platform=&granularity=day|week
GET    /analytics/platform-dist     ?dateRange=
GET    /analytics/engagement-monthly ?year=
GET    /analytics/top-videos        ?dateRange=&platform=&limit=&sort=
GET    /analytics/export.csv        ?dateRange=&platform=
POST   /analytics/sync              — pull latest stats from platform APIs
```

### 8.13 Brand Kit
```
GET    /brand-kit
PUT    /brand-kit
POST   /brand-kit/logo              (multipart)
DELETE /brand-kit/logo
```

### 8.14 Billing
```
GET    /billing/subscription
GET    /billing/plans
POST   /billing/subscribe           — {planId, paymentMethodId}
POST   /billing/cancel
GET    /billing/invoices
POST   /billing/credits/purchase    — {pack: 50|100|500, paymentMethodId}
GET    /billing/portal              — Stripe customer portal URL
```

### 8.15 Notifications
```
GET    /notifications               ?unread=true&limit=
PUT    /notifications/:id/read
PUT    /notifications/read-all
DELETE /notifications/:id
DELETE /notifications               — clear all
```

---

## 9. Credits System

### 9.1 Credit Costs Summary

| Action | Credits |
|---|---|
| SDXL image | 0.5 |
| Flux Pro image | 1.0 |
| Mochi video (fast) | 1.0 |
| CogVideoX video | 2.0 |
| Wan 2.1 video | 4.0 |
| Auto captions | 0.5 |
| AI thumbnail | 0.5 |
| Prompt enhance | 0.0 (free) |
| Metadata regen | 0.0 (free) |

### 9.2 Credit Operations

```
POST /credits/deduct      — internal, called by generation services
POST /credits/refund      — internal, called on failure/cancel
GET  /credits/history     — transaction log for user
GET  /credits/balance     — {remaining, total, used, resetAt}
```

### 9.3 Credit Reset

Credits reset monthly on subscription renewal date. New users get 5 free credits on signup.

---

## 10. Real-time Communication

The progress page polls job status. Implement one of:

### Option A: Server-Sent Events (SSE) — Recommended
```
GET /jobs/:jobId/stream
Content-Type: text/event-stream

data: {"percentage": 25, "stage": "Generating Frames", "framesReady": 1}
data: {"percentage": 65, "stage": "Rendering Video", "framesReady": 3}
data: {"percentage": 100, "stage": "Encoding Output", "framesReady": 5, "videoId": "uuid"}
```

### Option B: WebSocket
```
ws://api/ws
Client sends: {"type": "subscribe_job", "jobId": "uuid", "token": "..."}
Server sends: {"type": "job_progress", "jobId": "uuid", "percentage": 65, "stage": "..."}
```

---

## 11. File Storage

All media (videos, images, thumbnails, logos) must be stored on cloud storage:

**Recommended**: AWS S3, Cloudflare R2, or Supabase Storage

**URL pattern**:
```
https://storage.vidify.app/users/{userId}/videos/{videoId}.mp4
https://storage.vidify.app/users/{userId}/images/{imageId}.webp
https://storage.vidify.app/users/{userId}/thumbnails/{videoId}.jpg
https://storage.vidify.app/brand-kits/{userId}/logo.png
```

**Signed URLs**: Download endpoints return time-limited signed URLs (expire in 1 hour).

---

## 12. Environment Variables

```env
# Server
PORT=3000
NODE_ENV=development

# Database
DATABASE_URL=postgresql://user:pass@host:5432/vidify

# JWT
JWT_SECRET=your-secret-key
JWT_EXPIRES_IN=15m
REFRESH_TOKEN_SECRET=your-refresh-secret
REFRESH_TOKEN_EXPIRES_IN=7d

# Google OAuth
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_CALLBACK_URL=http://localhost:3000/auth/callback/google

# ⭐ Flux / Image AI
REPLICATE_API_TOKEN=r8_xxxxxxxxxxxx
# OR
FAL_API_KEY=your-fal-key

# Video AI
REPLICATE_API_TOKEN=r8_xxxxxxxxxxxx   # (same token, different models)

# Storage
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=us-east-1
S3_BUCKET=vidify-media

# Social OAuth
TIKTOK_CLIENT_ID=
TIKTOK_CLIENT_SECRET=
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
INSTAGRAM_APP_ID=
INSTAGRAM_APP_SECRET=
FACEBOOK_APP_ID=
FACEBOOK_APP_SECRET=

# Stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Email
SMTP_HOST=smtp.resend.com
SMTP_API_KEY=re_...
FROM_EMAIL=noreply@vidify.app

# Frontend URL (for CORS + OAuth callbacks)
FRONTEND_URL=http://localhost:5173
```

---

## 13. CORS Configuration

```js
// Allow these origins:
const allowedOrigins = [
  'http://localhost:5173',   // Vite dev server (frontend)
  'https://vidify.app',       // production frontend
]

// Expose headers for SSE:
// Access-Control-Allow-Origin: *
// Access-Control-Allow-Credentials: true
```

---

## 14. Error Response Format

All API errors must return:
```json
{
  "error": {
    "code": "INSUFFICIENT_CREDITS",
    "message": "You need 2 credits but only have 1 remaining.",
    "status": 402
  }
}
```

**Standard error codes**:
- `INVALID_CREDENTIALS` (401)
- `TOKEN_EXPIRED` (401)
- `FORBIDDEN` (403)
- `NOT_FOUND` (404)
- `INSUFFICIENT_CREDITS` (402)
- `GENERATION_FAILED` (500)
- `VALIDATION_ERROR` (422)
- `RATE_LIMITED` (429)
- `PLATFORM_NOT_CONNECTED` (400)

---

## 15. Database Schema (PostgreSQL)

```sql
-- Users
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  first_name TEXT NOT NULL,
  last_name TEXT NOT NULL,
  avatar_url TEXT,
  google_id TEXT UNIQUE,
  password_hash TEXT,
  plan TEXT DEFAULT 'free',
  credits_total INTEGER DEFAULT 5,
  credits_used INTEGER DEFAULT 0,
  credits_reset_at TIMESTAMPTZ,
  onboarding_completed BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Brand Kits
CREATE TABLE brand_kits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  brand_name TEXT,
  industry TEXT,
  brand_color_hex TEXT DEFAULT '#2563eb',
  logo_url TEXT,
  connected_platforms TEXT[] DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Jobs
CREATE TABLE jobs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  type TEXT NOT NULL, -- 'video_generation' | 'image_generation' | 'publish'
  status TEXT DEFAULT 'queued',
  percentage INTEGER DEFAULT 0,
  current_stage TEXT,
  entity_id UUID,
  external_job_id TEXT,
  error_message TEXT,
  estimated_seconds_left INTEGER,
  queue_position INTEGER DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Videos
CREATE TABLE videos (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  job_id UUID REFERENCES jobs(id),
  title TEXT NOT NULL,
  prompt TEXT,
  mode TEXT DEFAULT 'text',
  status TEXT DEFAULT 'generating',
  aspect_ratio TEXT DEFAULT '16:9',
  duration INTEGER DEFAULT 15,
  style TEXT,
  model TEXT,
  voiceover BOOLEAN DEFAULT FALSE,
  bg_music BOOLEAN DEFAULT TRUE,
  auto_captions BOOLEAN DEFAULT TRUE,
  video_url TEXT,
  thumbnail_url TEXT,
  file_size_mb DECIMAL,
  quality TEXT DEFAULT '1080p',
  format TEXT DEFAULT 'mp4',
  credits_cost DECIMAL DEFAULT 2.5,
  template_id UUID,
  platform_descriptions JSONB DEFAULT '{}',
  tags TEXT[] DEFAULT '{}',
  published_at TIMESTAMPTZ,
  scheduled_at TIMESTAMPTZ,
  platforms TEXT[] DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Generated Images
CREATE TABLE generated_images (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  job_id UUID REFERENCES jobs(id),
  prompt TEXT NOT NULL,
  negative_prompt TEXT,
  model TEXT DEFAULT 'flux',
  aspect_ratio TEXT DEFAULT '1:1',
  style TEXT DEFAULT 'Photorealistic',
  image_url TEXT,
  thumbnail_url TEXT,
  credits_cost DECIMAL DEFAULT 1,
  used_in_video_id UUID REFERENCES videos(id),
  replicate_prediction_id TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Social Accounts
CREATE TABLE social_accounts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  platform TEXT NOT NULL,
  handle TEXT,
  display_name TEXT,
  access_token TEXT,
  refresh_token TEXT,
  token_expires_at TIMESTAMPTZ,
  connected BOOLEAN DEFAULT TRUE,
  avatar_url TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Analytics
CREATE TABLE analytics_records (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  video_id UUID REFERENCES videos(id) ON DELETE CASCADE,
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  platform TEXT NOT NULL,
  date DATE NOT NULL,
  views INTEGER DEFAULT 0,
  likes INTEGER DEFAULT 0,
  comments INTEGER DEFAULT 0,
  shares INTEGER DEFAULT 0,
  engagement_rate DECIMAL,
  impressions INTEGER DEFAULT 0,
  PRIMARY KEY (video_id, platform, date)
);

-- Notifications
CREATE TABLE notifications (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  type TEXT NOT NULL, -- 'video_ready' | 'publish_success' | 'publish_failed' | 'credits_low' | 'plan_renewal'
  title TEXT NOT NULL,
  message TEXT,
  read BOOLEAN DEFAULT FALSE,
  entity_type TEXT,
  entity_id UUID,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Credit Transactions
CREATE TABLE credit_transactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  amount DECIMAL NOT NULL, -- negative=deduct, positive=add
  balance_after DECIMAL NOT NULL,
  reason TEXT NOT NULL, -- 'video_generation' | 'image_generation' | 'refund' | 'purchase' | 'monthly_reset'
  entity_type TEXT,
  entity_id UUID,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Scheduled Posts
CREATE TABLE scheduled_posts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  video_id UUID REFERENCES videos(id),
  platform TEXT NOT NULL,
  scheduled_at TIMESTAMPTZ NOT NULL,
  status TEXT DEFAULT 'pending', -- 'pending' | 'published' | 'failed' | 'cancelled'
  caption TEXT,
  error_message TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

---

## 16. Recommended Tech Stack

### Option A — Node.js (Express/Fastify)
- **Framework**: Fastify or Express
- **ORM**: Prisma or Drizzle
- **DB**: PostgreSQL
- **Queue**: BullMQ (Redis)
- **Auth**: jsonwebtoken + bcrypt
- **Storage**: @aws-sdk/client-s3
- **Realtime**: SSE via `res.write()` or `socket.io`

### Option B — Python (FastAPI)
- **Framework**: FastAPI
- **ORM**: SQLAlchemy or SQLModel
- **DB**: PostgreSQL
- **Queue**: Celery + Redis
- **Auth**: python-jose + passlib
- **Storage**: boto3

---

## 17. Key Implementation Notes

1. **Flux First**: The `/image-gen` page is the primary AI feature. Implement this endpoint first and make it real.

2. **Credits are sacred**: Always deduct before generation, always refund on failure. Use DB transactions.

3. **Frontend expects specific field names**: Match the exact field names shown in the frontend code (e.g., `status` values must exactly match: `"generating"`, `"ready"`, `"published"`, `"scheduled"`, `"failed"`).

4. **Platform colors expected**: The frontend uses Tailwind classes `bg-tiktok`, `bg-youtube`, `bg-instagram`, `bg-facebook`. These are custom CSS vars; your backend data just needs the platform string identifiers: `"tiktok"`, `"youtube"`, `"instagram"`, `"facebook"`.

5. **Sidebar badge counts**: The sidebar shows "18" badge on My Videos and "6" badge on Notifications. These come from API responses — return counts in the user stats object.

6. **Video generation can be mocked initially**: Start with Flux image generation as real, and mock video generation as a queued job that auto-completes after 45 seconds.

7. **Dashboard "Good morning, Ehtisham"**: The greeting uses the user's `firstName`. Make sure `GET /auth/me` returns `firstName`.

8. **Progress page auto-redirects**: When job completes, the success modal navigates to `/result`. The backend must have the video ready at `GET /videos/:id` by that time.

9. **Publishing confirmation toast**: Shows for 1.8s then redirects to `/dashboard`. No backend call needed for the toast itself.

10. **Analytics data**: Start by returning mock analytics data that matches the shape shown in the frontend (line chart with 15 points, donut with 4 segments, monthly bar chart with 12 months).

---

## 18. Development Order (Suggested)

1. **Auth system** — register, login, JWT, `/auth/me`
2. **User model + credits** — credit balance, deduction, refund
3. **⭐ Flux image generation** — `/images/generate` + `/images/jobs/:id/status`
4. **Video CRUD** — create, list, get, delete (mock generation)
5. **Dashboard stats** — `/dashboard/stats` returning real DB counts
6. **Job system** — status polling + SSE for progress page
7. **Social OAuth** — connect TikTok/YouTube/Instagram
8. **Publishing** — `/videos/:id/publish` calls platform APIs
9. **Analytics** — sync platform stats, return to frontend
10. **Billing** — Stripe integration
11. **Notifications** — trigger on key events

---

*This document covers every pixel of the Admart/Vidify frontend and every API call the backend needs to support. Build in the order above, starting with Flux image generation as the first real AI feature.*
