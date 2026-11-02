# Admart Agents — guide

Agents do work for a user inside a project. Users pick an agent from **Agents** in the sidebar,
deploy it, and run it. Every run is processed in the background by the **agents worker**.

| Agent | Kind | What it does |
|---|---|---|
| **YouTube Shorts Creator** | Full automation | Topic → finished vertical Short, with your approval before anything is posted |
| **Script Writer** | Single task | Topic → Short script (scenes, title, description, tags) |
| **Voiceover** | Single task | Text → MP3 voice recording |
| **Video Editor** | Full automation | Your own video (up to 3 min) → cut, cleaned, captioned and reframed, with your approval |
| **Growth Report** | Full automation | Every 7, 15 or 30 days: what happened (YouTube Analytics, followers, posts), why, and a plan for the next period, emailed and in the app; approve the plan into Autopilot |
| **Trend Finder** | Single task | Your niche → 5–8 topics rising this week, each with why, a scored hook and a source; make a Short or add it to Autopilot in one click |
| **Cross-poster** | Full automation | A Library video → a post for YouTube, Instagram and Facebook; you check them, it posts now or later |
| **Clip Maker** | Full automation | A YouTube link or a long upload (30 min Free, 2 h paid) → the best moments, scored, as vertical clips with captions |

---

## How the Shorts Creator works

```
Topic → Research → 3 concepts (you pick) → Script (you edit)
      → Voice → Caption timing → Visuals (stock video or AI images)
      → Storyboard (you check, redo any scene) → Edit → Quality checks
      → You approve → Publish page opens pre-filled
```

- **Research** uses web search for current facts and keeps the sources.
- **Edit** (FFmpeg, CPU only): camera moves on images, crossfades, word-highlight captions in the
  Brand Kit colour, background music ducked under the voice, loudness levelled for YouTube,
  title thumbnail.
- **Quality checks**: length, vertical 1080×1920, no black frames, clear audio, no long silences.
- **Check-ins** (set when deploying): *Every step* (concept, script, storyboard) or
  *Final video only*. Nothing is ever posted without approval.
- **Credits** are reserved when a run starts, refunded if it fails, and refunded if discarded at
  the concept or script check-in. An agent can have a monthly credit limit.
- A run that stops half-way (restart, crash) resumes from its last finished step and never pays
  twice for the same step.

---

## How the Video Editor works

```
Upload / pick a Library video → Check (length, sound) → Transcript (fal Whisper)
      → Clean audio (Basic free / Standard / Studio) → Edit plan: pauses, um/uh, restarts,
        black or frozen frames + caption spelling fixes → You review the cuts (keep, cut, fix spelling)
      → Render in your format (9:16, 1:1, 4:5 or original), captions, -14 LUFS → Title & thumbnail
      → You approve → Publish page opens pre-filled
```

- Choices per agent (start screen or **Settings**): format, cut style (Gentle / Normal / Tight),
  audio cleanup level with its price per minute, captions, music, review of the cuts.
- Credits depend on the video's length and the audio level (Basic ≈ 0.013, Standard ≈ 0.04,
  Studio ≈ 0.22 credits per minute at today's fal prices, before any change to the markup).
- If a paid audio service fails, the free filter is used and the workflow says so.
- Code: `agents/video_edit.py`; plan: `docs/plans/2026-10-13-video-editor-agent.md`.

## How the Growth Report works

- Steps `collect → analyze → deliver` (`agents/growth.py`, plan `docs/plans/2026-10-15-growth-report-agent.md`).
- **collect:** the period (7/15/30 days up to yesterday) and the one before. YouTube Analytics totals,
  revenue (monetized channels), top 10 videos and the subscriber count; Instagram/Facebook followers (live);
  posts published through Admart with live stats; best weekdays from the user's own posts.
  YouTube connections made before 2026-10-15 lack the analytics permissions: the report asks the user to reconnect.
- **analyze:** numbers are computed in code; one OpenRouter call (web search when a niche is set) writes the
  verdict, wins and losses, a plan (posts per week × period) and 3 actions. Citations and website names are stripped.
- **deliver:** HTML email to the owner plus up to 5 addresses, plus the in-app report. An email failure doesn't fail the run.
- **Schedule:** the agent's Autopilot. `config.period` 15 or 30 means the next report is that many days after the
  last slot. WhatsApp, Telegram and Slack show as "Coming soon".
- **Policy:** YouTube numbers are removed from saved reports when YouTube is disconnected.

## How the Trend Finder works

- One OpenRouter call with web search (always searches) for news, launches and viral topics from the
  last 14 days in the niche. The brand name is not sent (it would find news about that company).
- Skips topics the project's agents already covered (last 30 runs). Each trend gets a hook score.
- A source link is shown only if it came from the search results, never one the model made up.
- **Make a Short** starts the project's YouTube Shorts Creator with that topic; **Add to Autopilot**
  appends it to that agent's topic queue. About 0.01 credits per run.
- Code: `step_trends` in `agents/steps.py`, UI `AgentTrendList.jsx`.

## How the Clip Maker works

```
YouTube link (user ticks "I have the rights") or Library video → Download (yt-dlp, ≤1080p) / copy
      → Transcript in 10-min pieces cut at pauses (Groq free → local faster-whisper → fal), one language
      → AI reads ~20-min windows of numbered sentences, returns moments (from/to sentence, 0-100 score,
        title, hook, reason) → edges snapped to whole sentences, fitted to the length, duplicates dropped
      → You pick, trim and edit hooks (check-in) → Render: 1080×1920 crop or blurred fit, word captions,
        hook box for 3.5 s, -14 LUFS, quality checks → Every clip saved to the Library
```

- Settings per agent: clip length (15–30 / 30–60 / 60–90 s), up to 3–10 clips, framing, check-in on/off.
- Framing **Follow the speaker** (default, `agents/reframe.py`): each clip is sampled 10×/s at 640 px; OpenCV
  YuNet finds faces, a colour-histogram change finds camera cuts. Per shot: one face (or two close together)
  → a still camera that only moves when the face leaves a dead zone, then eases over, snapping on cuts;
  two people far apart → split screen (one per half, captions on the seam); no clear face, a crowd or a
  screen → the whole picture over a blurred copy. About 6 s of analysis per minute of clip on CPU.
  Already-vertical sources are just cropped.
- Downloads retry 10× with a 60 s timeout; "Try again" resumes a half-finished download.
- Long jobs: run a separate worker with `run_agents_worker --only clip-maker` (and `--exclude clip-maker`
  on the main one) so Shorts and posts never wait behind a 2-hour video.
- Local transcription speed on a 12-core CPU: about 6× real time with the `base` model (`small` is slower,
  more accurate). Groq is much faster.
- Caption styles (Classic, Bold, Boxed, Minimal), captions editable per clip at the check-in, and
  **Tighten** (cuts pauses and um/uh inside clips). Uploads over 100 MB go in resumable 8 MB chunks (up to 4 GB).
- Server setup (Deno, PO-token provider, own worker, daily source cleanup): [clip-maker-server.md](clip-maker-server.md).
- Code: `agents/clips.py`; plan: `docs/plans/2026-10-14-clip-maker-agent.md`.

## How the Cross-poster works

```
Pick a Library video → Check (length, shape, sound) → Transcript of the first 3 min (fal Whisper)
      → One AI call writes a post per connected platform (YouTube title/description/tags + thumbnail,
        Instagram caption, Facebook caption) → You edit them, untick platforms, pick now or a time
      → (waits until that time) → Posts to each platform with the existing publishers
```

- Posts only to platforms connected on **Social Accounts** (YouTube, Instagram, Facebook). Instagram
  and Facebook still need `INSTAGRAM_PUBLISH_ENABLED` / `FACEBOOK_PUBLISH_ENABLED` (App Review).
- Instagram downloads the video from its URL, so `MEDIA_BASE_URL` must be public https.
- Scheduling: the run waits in the queue until the time (the worker must be running then).
  **Cancel** on the run stops it and refunds. Needs a plan with scheduled publishing.
- Every post is a **Publish job**, so it shows in Calendar and Analytics.
- A retry re-posts only platforms that failed; an upload cut off mid-way is never repeated
  automatically (check the platform first).
- About 0.04 credits per post at most (mostly transcription; the post writing is one cheap text call).
- Code: `agents/cross_post.py`; plan: `docs/plans/2026-10-14-cross-poster-agent.md`.

---

## What you need

### On the server (once)

- [ ] FFmpeg and fonts: `sudo apt install -y ffmpeg fonts-dejavu-core`
- [ ] The agents worker service — see [agents-worker.md](agents-worker.md)
- [ ] `MEDIA_BASE_URL` set to the public API address (so YouTube can fetch the video)

### Keys in the backend `.env`

| Key | Needed? | Used for |
|---|---|---|
| `OPENROUTER_API_KEY` | Yes | Research, ideas, script (and web search with credit) |
| `FAL_KEY` | Yes | Voice, caption timing, images (also used by the image/video pages) |
| `PEXELS_API_KEY` | Optional, free | Real stock video for scenes that suit it |
| `AGENTS_DRY_RUN` | — | `True` = free test mode (placeholders, 0 credits); `False` for real |

### Files (optional)

- [ ] 10–20 royalty-free music tracks (`.mp3`/`.m4a`/`.wav`, e.g. from the YouTube Audio Library)
      in `agent_music/` (or `AGENTS_MUSIC_DIR`). No tracks = no music.

### Google / YouTube (start early — takes days to weeks)

- [ ] Ask for a higher **YouTube Data API upload quota** in Google Cloud. The default allows only
      a handful of uploads per day for *all* users combined.
- [ ] Pass Google's app **audit**, otherwise uploads through the API may be forced to private.

---

## Services, models and costs

Agents use two services: **OpenRouter** (text) and **fal.ai** (voice, caption timing, images).
Models are set in `.env`; a failed step fails the run and refunds it (caption timing alone falls
back to an estimate).

| Purpose | Model now (setting) | Cost | Alternatives (same service) |
|---|---|---|---|
| Ideas, script, auto-topics, posts | OpenRouter `google/gemini-2.5-flash-lite` → `qwen/qwen3.7-flash` → `deepseek/deepseek-v4-flash` (`AGENTS_OPENROUTER_MODELS`, tried in order) | ~$0.001 per call, ~$0.003 per Short (`AGENTS_LLM_USD_PER_RUN`). Tested 2026-10-14: Gemini fastest (8 s) with the best hooks; Qwen good but slow (~70 s); DeepSeek cheapest but sometimes returns nothing; GLM 4.7 Flash failed | Free (daily limits): `google/gemma-4-31b-it:free`, `nvidia/nemotron-3-super-120b-a12b:free` |
| Research facts | Same models + OpenRouter web search, engine `exa` (`AGENTS_SEARCH_ENGINE`) | ~$0.007 per Short (one search). **Skipped without credit**: research then uses the model's own knowledge | Engines `parallel` (~$0.001), `perplexity` (~$0.005) |
| Voice | fal `fal-ai/kokoro/american-english` / `british-english` (6 voices picked per agent) | $0.02 per 1,000 characters ≈ **$0.01–0.02** per Short | fal Chatterbox (~$0.025/1K chars), Gemini 3.1 Flash TTS on fal (~$0.15/1K chars) |
| Caption timing | fal `fal-ai/whisper`, word level (`AGENTS_WHISPER_MODEL`) | Billed per compute second; estimate **~$0.01** per Short | None needed: without it captions use an even estimate |
| Pictures | fal `fal-ai/flux/schnell` (`AGENTS_IMAGE_MODEL`) | $0.003 per megapixel ≈ $0.003 per picture ≈ **$0.02** per Short (6 scenes) | `fal-ai/flux/dev` (~$0.026/picture, better detail), `fal-ai/flux-pro/v1.1` (~$0.04/picture, best) |
| Stock video (optional) | Pexels | Free | — |
| Music (optional) | Your own files in `agent_music/` | Free | — |

**Per Short:** about **$0.04–0.05** with free text models (voice + captions + 6 pictures + one
search), or about $0.05–0.07 with a cheap paid text model. Credits charged to users = this
estimate × Admart markup; picture prices come live from fal's pricing API.
Set `AGENTS_LLM_USD_PER_RUN` (USD per text call) when you switch to paid text models.

**Voice & style per agent.** Users pick a voice (6 Kokoro narrators), pace, tone, video length
(30/45/60s) and picture style when they start an agent, and can change them later under
**Settings** (`VOICES` in `agents/registry.py`). The preview clips live in the frontend at
`public/agent-voices/<id>.mp3`; re-record them if you change a voice.

Prices change: check openrouter.ai/models and fal.ai/pricing.

---

## Autopilot (scheduled runs)

On an agent's page (agents that take a topic), switch **Autopilot** on and choose:

- **Days and time** — in the user's own time zone (taken from the browser).
- **Upcoming topics** — used in order, one per run.
- **Channel niche** — when the topic list is empty, the agent picks a fresh topic from the niche,
  avoiding its recent topics.

The worker checks every 30 seconds and starts due runs with the usual credit and monthly-limit
checks. If a slot can't run (for example not enough credits) it is skipped, a note shows on the
agent, and it tries again at the next slot. Results never post by themselves: they wait for the
user. (The Cross-poster posts only after the user approves the posts.)

**Inbox:** runs that need the user (concept, script, storyboard, finished Short) and failures from
the last 7 days show on **Notifications**, as a count on the bell, and under **Waiting for you**
on the Agents page.

---

## Managing agents (admin dashboard)

`/admin/dashboard/` → **Agents**:

- **Summary**: runs and failure rate (30 days), credits charged, stuck runs, providers in use.
- **Agent recipes**: each agent is a list of step blocks plus optional custom prompts
  (research, concepts, script). Owners can edit a recipe or create a new agent with
  **+ New agent** — it appears in the users' catalog immediately, no deploy needed. Invalid
  orders are rejected with a reason (e.g. captions need a voice step first). Hiding an agent
  removes it from the catalog; existing deployments keep working.
- **Recent runs** across all users, filterable (failed, stuck, …). Owners can **Cancel & refund**
  a queued/running/paused run or **Retry** a failed one.

Users also get a **Try again** button on their own failed runs; it charges the run's credits
again and resumes after the last finished step.

Available step blocks: `research`, `concepts`, `pick_concept` (check-in), `script`,
`review_script` (check-in), `voice`, `captions`, `visuals`, `review_storyboard` (check-in),
`render`, `finish`.

---

## Try it

1. Set `AGENTS_DRY_RUN=True`, restart the backend, start the worker:
   `python manage.py run_agents_worker`
2. **Agents → YouTube Shorts Creator → Deploy → Run now.** A dry run uses placeholder images and
   silent audio and costs nothing, but goes through every step including the real edit.
3. For real Shorts set `AGENTS_DRY_RUN=False` with the keys above, restart backend + worker.

Render time on CPU: roughly 3–4 minutes for a 45-second Short (more with local voice/timings).

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Run stays **Queued** | The worker isn't running. Start it (`run_agents_worker`) or check the service. |
| "No … service is set up" | `OPENROUTER_API_KEY` or `FAL_KEY` is missing. |
| "The … service (…) failed" | The service errored: free OpenRouter models busy, or fal out of balance. Try later, top up, or switch to a paid text model. |
| Captions slightly off | fal Whisper was unavailable, so timings were estimated. |
| No music | `agent_music/` is empty or music is off in the agent's settings. |
| Upload fails / private on YouTube | API quota or app audit — see *Google / YouTube* above. |

Credits are refunded automatically whenever a run fails.

---

## For developers

- Code: `agents/` (models, registry, steps, providers, render, engine, views).
- Hooks and packaging: `agents/hooks.py` has 21 hook formulas, a hook scorer and a title +
  thumbnail-text linter (no AI calls), ported from the MIT-licensed
  [youtube-agent-skill](https://github.com/Jakeschincariol/youtube-agent-skill). Ideas write 3 hooks
  each and keep the best-scoring one; the best idea is listed first.
- New agent: create a recipe in the admin dashboard (no code). A new *step block* needs code in
  `agents/steps.py` plus an entry in `STEP_BLOCKS` in `agents/registry.py`.
- New provider: add it to the job's `*_READY` and call maps in `agents/providers.py`.
- Tests: `python manage.py test agents` — no paid calls; providers are mocked and a full Short is
  rendered in dry-run mode.
