# Agents — Phase 1 plan

Branch: `feature/agents` in both repos (staging is live; merge via PR only, no pipeline changes).

## Goal

An **Agents** page where a user picks an agent, deploys it to the active project and runs it.
Phase 1 ships three agents on one engine:

| Agent | Kind | Steps | Output |
|---|---|---|---|
| YouTube Shorts Creator | large | script → images → voice → render → finish | 9:16 MP4 in the library, ready to publish after approval |
| Script Writer | small | script | title, description, tags, scenes (narration + image prompt) |
| Voiceover | small | voice (one scene) | MP3 in the library |

Runs are on demand ("Run now"). Schedules (Autopilot) are Phase 2 and only add a trigger to the same engine.

Decisions (user, 2026-10-12): Shorts first, approval always on, OpenAI TTS, still images (no AI clips), no GPU.

## Backend (`admart-backend`, new app `agents`)

### Models

- `AgentDeployment` — project, user, `agent_type` (registry slug), `config` (JSON: niche, voice, …),
  `status` (`active`/`paused`), `monthly_credit_limit` (nullable), timestamps.
- `AgentRun` — deployment, project, user, `input` (JSON), `status`
  (`queued`, `running`, `needs_review`, `succeeded`, `failed`, `discarded`, `approved`), `step`,
  `output` (JSON: script, scenes with image/audio URLs, video URL…), `library_asset` (nullable),
  `credits_reserved`, `topup_reserved`, `error`, `attempts`, `locked_until`, timestamps, `finished_at`.

### Registry (`agents/registry.py`)

`AGENTS = {slug: AgentSpec(name, kind, description, needs, steps, input_fields, estimate_usd)}`.
The catalog API is generated from it; adding an agent = a spec + its steps.

### Steps (`agents/steps.py`) — each idempotent: if its output exists, it is skipped

- `script` — Gemini (existing key/helpers), JSON out: title, description, tags, 4–7 scenes of
  narration (≤ ~130 words total for ~45 s) + image prompt. Uses Brand Kit name, industry, tone.
- `images` — fal `fal-ai/flux/schnell` (setting `AGENTS_IMAGE_MODEL`), portrait 9:16, one per
  scene, polled synchronously in the worker, persisted with `persist_remote_image`.
- `voice` — OpenAI `/v1/audio/speech` (`AGENTS_TTS_MODEL`, default `gpt-4o-mini-tts`,
  `AGENTS_TTS_VOICE`), one MP3 per scene; duration via ffprobe.
- `render` — FFmpeg, CPU only: per scene zoom/pan on the image for the scene's audio length,
  captions burned in as 3–4 word chunks timed proportionally inside the scene, scenes joined,
  1080×1920 H.264/AAC, thumbnail from the first scene. Self-check: duration > 0, has audio
  stream, audio not silent (volumedetect).
- `finish` — creates the `LibraryAsset` (video, ready) and sets status `needs_review`
  (large agents) or `succeeded` (small agents).

**Dry run** (`AGENTS_DRY_RUN=True`): template script, solid-colour placeholder images and silent
audio made by FFmpeg, zero credits — exercises the whole pipeline including the real render at $0.

### Worker

`python manage.py run_agents_worker [--once]` — claims one queued run with a conditional UPDATE
(`status=queued → running`, sets `locked_until`), runs its remaining steps, saves after each step.
Stale `running` runs (lease expired) are re-queued; after 3 attempts they fail. Failure refunds
the reserved credits and stores a plain error message (via `projects.publish.user_error`).

### Credits

Price = estimated provider USD (images × image price from `content.pricing`, TTS per 1k chars,
LLM flat) × `admart_markup_multiplier`. Reserved when the run is created, refunded on failure.
Deployment's monthly limit checked against this month's non-refunded runs.

### API

- `GET  /api/agents/catalog`
- `GET|POST /api/projects/:pid/agents` — deployments
- `GET|PATCH|DELETE /api/projects/:pid/agents/:id` — pause/resume, config, limit
- `GET|POST /api/projects/:pid/agents/:id/runs` — list / start (quote + reserve)
- `GET  /api/projects/:pid/agents/:id/runs/:rid`
- `POST /api/projects/:pid/agents/:id/runs/:rid/approve` and `/discard`

Approve does not publish by itself: the frontend opens the existing Publish page with the
library asset pre-filled (title, description, tags), reusing the YouTube form, schedule and
cross-posting.

### Tests (no paid calls: Gemini, fal and OpenAI are mocked)

Each step; a real FFmpeg render of a tiny 2-scene dry run; worker claim + stale recovery;
credit reserve/refund; monthly limit; ownership (other users get 404); paused deployment
cannot run.

## Frontend (`Admart-frontend`)

- Sidebar: **Agents**.
- `/agents` — catalog: tabs All · Single tasks · Full automations; cards (what it does, needs,
  est. credits, Deploy); "My agents" list.
- Deploy wizard (modal): large agent = Connect check → Brief → Rules; small agent = one confirm.
- `/agents/:id` — deployment page: status + Pause/Resume, Run now form, runs list with live step
  progress (polling), review panel (vertical video / audio / script), Approve → Publish page,
  Discard.

## Deploy (owner action — not edited by us)

1. `sudo apt install ffmpeg` on the VPS.
2. Add `OPENAI_API_KEY` (and optionally `AGENTS_*` settings) to the backend `.env`.
3. A systemd service running `manage.py run_agents_worker`, modelled on
   `deploy/admart-backend.service`; restart it on deploy. The unit text is provided in the PR.

## Out of scope (Phase 2+)

Schedules/Autopilot, music, AI video clips, analytics feedback, long-form, Trend Finder,
Cross-poster, Lead/Business Finder.
