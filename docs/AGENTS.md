# Admart Agents — guide

Agents do work for a user inside a project. Users pick an agent from **Agents** in the sidebar,
deploy it, and run it. Every run is processed in the background by the **agents worker**.

| Agent | Kind | What it does |
|---|---|---|
| **YouTube Shorts Creator** | Full automation | Topic → finished vertical Short, with your approval before anything is posted |
| **Script Writer** | Single task | Topic → Short script (scenes, title, description, tags) |
| **Voiceover** | Single task | Text → MP3 voice recording |

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

## What you need

### On the server (once)

- [ ] FFmpeg and fonts: `sudo apt install -y ffmpeg fonts-dejavu-core`
- [ ] Python packages: `pip install -r requirements.txt` (includes `kokoro-onnx` and `faster-whisper`
      for the free local voice and captions; the first install is ~150 MB)
- [ ] Free local models: `python manage.py download_agent_models` (~250 MB: Kokoro voice + Whisper)
- [ ] The agents worker service — see [agents-worker.md](agents-worker.md)
- [ ] `MEDIA_BASE_URL` set to the public API address (so YouTube can fetch the video)

### Keys in the backend `.env`

| Key | Needed? | Cost | Used for |
|---|---|---|---|
| `GEMINI_API_KEY` | Yes (or Groq) | Free tier | Research, concepts, script; fallback voice |
| `GROQ_API_KEY` | Optional | Free tier | Text fallback when Gemini's free limit is used up |
| `CLOUDFLARE_ACCOUNT_ID` + `CLOUDFLARE_API_TOKEN` | Yes (or fal) | Free daily allowance | AI images |
| `PEXELS_API_KEY` | Optional | Free | Real stock video for scenes that suit it |
| `OPENAI_API_KEY` | Optional | Paid | Premium voice and exact caption timing fallback |
| `FAL_KEY` | Optional | Paid (cheap) | Image fallback |
| `AGENTS_DRY_RUN` | — | — | `True` = free test mode (placeholders, 0 credits); `False` for real |

### Files (optional)

- [ ] 10–20 royalty-free music tracks (`.mp3`/`.m4a`/`.wav`, e.g. from the YouTube Audio Library)
      in `agent_music/` (or `AGENTS_MUSIC_DIR`). No tracks = no music.

### Google / YouTube (start early — takes days to weeks)

- [ ] Ask for a higher **YouTube Data API upload quota** in Google Cloud. The default allows only
      a handful of uploads per day for *all* users combined.
- [ ] Pass Google's app **audit**, otherwise uploads through the API may be forced to private.

---

## Free vs paid providers

Each job tries its providers **in order**, skips any that aren't set up, and falls through to the
next if one fails (for example when a free limit is reached). Order is set in `.env`:

| Job | Setting | Default order (free first) |
|---|---|---|
| Text (research, concepts, script) | `AGENTS_LLM_PROVIDERS` | `gemini,groq` |
| Voice | `AGENTS_TTS_PROVIDERS` | `kokoro,gemini,openai` |
| Images | `AGENTS_IMAGE_PROVIDERS` | `cloudflare,fal` |
| Caption timing | `AGENTS_CAPTION_PROVIDERS` | `local,openai` (else an even estimate) |

| Provider | Type | Notes |
|---|---|---|
| Gemini Flash | Free tier | Daily limits apply; on the free tier Google may use prompts to improve its models |
| Groq (Llama) | Free tier | No web search, so research uses the model's own knowledge |
| Kokoro | Free, local (CPU) | Good English voice, ~real-time on CPU, Apache-2.0 |
| Gemini TTS | Free tier | Preview model, daily limits |
| OpenAI TTS / transcription | Paid | Best voice; exact word timings |
| Cloudflare Workers AI FLUX schnell | Free daily allowance | Square images, cropped to 9:16 |
| fal FLUX schnell | Paid (~$0.003/image) | Native 9:16 |
| faster-whisper | Free, local (CPU) | Exact word timings for captions |
| Pexels | Free | Stock video; credit added to the description |

Free-tier limits change often — check each provider's dashboard.

### Cost per Short (estimates)

| Setup | Approx. cost |
|---|---|
| Free providers only (within free limits) | **$0** + CPU time |
| Paid (OpenAI voice + fal images + Gemini paid) | about $0.08–0.25 |

Credits charged to users = provider cost × Admart markup. Free providers add 0; set
`AGENTS_LLM_USD_PER_RUN=0` to make text free too.

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
| "No … service is set up" | No provider for that job has a key/model. Add a key or run `download_agent_models`. |
| "Every … service failed" | All providers for that job errored (often free limits). Try later or add a paid fallback. |
| Captions slightly off | No timing provider available, so timings are estimated. Install faster-whisper models. |
| No music | `agent_music/` is empty or music is off in the agent's settings. |
| Upload fails / private on YouTube | API quota or app audit — see *Google / YouTube* above. |

Credits are refunded automatically whenever a run fails.

---

## For developers

- Code: `agents/` (models, registry, steps, providers, render, engine, views).
- New agent: create a recipe in the admin dashboard (no code). A new *step block* needs code in
  `agents/steps.py` plus an entry in `STEP_BLOCKS` in `agents/registry.py`.
- New provider: add it to the job's `*_READY` and call maps in `agents/providers.py`.
- Tests: `python manage.py test agents` — no paid calls; providers are mocked and a full Short is
  rendered in dry-run mode.
