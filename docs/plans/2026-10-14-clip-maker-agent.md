# Clip Maker agent — plan (draft, not started)

Branch: `feature/agents` in both repos. Nothing is pushed without the owner's OK.

## Goal

A user gives a **YouTube link** or **uploads a long video** (podcast, interview, talk, tutorial,
vlog). The agent finds the best moments and returns **several ready-to-post vertical clips** (9:16,
1080×1920) for TikTok, Instagram Reels and YouTube Shorts. Each clip comes with face-tracked framing,
animated captions, a hook title, a virality score and per-platform captions. Same rules as every
agent: credits reserved up front, refunded on failure, nothing posted without approval.

## How the best open-source tools do it (research, 2026-10-14)

| Project | Stars | Licence | What we take from it |
|---|---|---|---|
| [mutonby/openshorts](https://github.com/mutonby/openshorts) | ~6.5k | MIT core (`cloud/` is not) | Whole pipeline shape; scene-aware reframing (TRACK / GENERAL / SPLIT); camera smoothing; per-scene FFmpeg `sendcmd` crop; two-pass LLM scoring |
| [SamurAIGPT / Anil-matcha AI-Youtube-Shorts-Generator](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator) | ~5.3k | MIT | Content-type detection first; 20-min chunks with 60 s overlap for long videos; 0–100 score + hook + reason; dedupe >50 % overlap |
| [ClipsAI/clipsai](https://github.com/ClipsAI/clipsai) | — | MIT | Topic segmentation of the transcript (fallback when no LLM); WhisperX word timing; Pyannote speaker-aware resize |
| [fralapo/clippyme](https://github.com/fralapo/clippyme) | small | MIT | Cuts land on sentence ends and silences, never mid-word; caption style presets; in-browser trim |
| [mehbul/chopify](https://github.com/mehbul/chopify) | small | MIT | "Complete-thought" rule (clip must end on terminal punctuation); 8-criteria score; OpenCV **YuNet** face detector; ASS caption presets (default/hormozi/mrbeast/podcast); -14 LUFS |
| `~/clip-maker` (ours, prototype) | — | — | Groq Whisper + Gemini picker + centre crop. Good start; no face tracking, word-level captions or sentence snapping |

The common pipeline in all of them:

```
link / upload → download (yt-dlp) → transcript with word timing → scene cuts (PySceneDetect)
  → LLM finds & scores moments → snap edges to sentences/silences → dedupe → top N
  → per clip: face-tracked 9:16 reframe → word-by-word captions + hook text → loudness → MP4
```

What makes the good ones look professional (and the weak ones look cheap):

1. **Edges.** Start 0.2–0.4 s before the hook, end 0.2–0.4 s after the payoff, on a full sentence.
2. **Framing.** It isn't a centre crop. The face is tracked with a *still* camera that only moves when
   the speaker leaves a safe zone (OpenShorts: safe zone = 25 % of crop width, slow pan 3 px/f,
   fast re-frame 15 px/f, move confirmed over 3 frames, snap instantly on a scene cut). Two people
   go into a stacked split screen. No face / crowds / screen recordings become a blurred-background "fit".
3. **Speaker stickiness.** Face IDs are matched across frames (within 15 % of width), scores decay
   ×0.85, the current speaker gets a ×3 "sticky" bonus, and switches are blocked for 30 frames.
4. **Captions.** Word-by-word, highlighted, 2–4 words per line, safe-area aware (above the platform UI).
5. **Ranking.** A 0–100 virality score with reasons, so users trust the order.

## Free / cheap services (keys you'll provide)

| Purpose | Recommended | Free allowance | Fallback |
|---|---|---|---|
| Transcription with word timing | **Groq** `whisper-large-v3-turbo` (console.groq.com) | Free tier: ~20 req/min, ~2,000 req/day, 25 MB per file → we send 10-min mono chunks | fal Whisper (already configured, paid) → local `faster-whisper` on CPU (free, slow) |
| Finding moments (LLM) | **Google Gemini** Flash / Flash-Lite (aistudio.google.com) | Free tier, limits per project (~1,500/day often quoted; Dec-2025 cuts, check AI Studio). Free-tier prompts may be used by Google | OpenRouter models already used by the agents (key not set locally yet), Groq-hosted LLMs |
| Extra free transcription credit | Deepgram ($200 one-time), AssemblyAI ($50 one-time) | Credit, not monthly | — |
| YouTube video info / ownership check | **YouTube Data API key** (Google Cloud) | 10,000 units/day | — |
| Face detection, scene cuts, render | Local: OpenCV YuNet, PySceneDetect, FFmpeg | Free | — |
| B-roll (later phase) | Pexels (already supported) | Free | — |

Not free and not needed for Phase 1: residential proxies (for YouTube downloads at scale), fal
`ltx-2.3/reframe` (generative reframe, $0.10–0.20 per second, far too expensive per clip).

## The hard part: YouTube links

- From a **home connection** `yt-dlp` works fine. From a **datacenter/VPS IP**, YouTube often
  answers "Sign in to confirm you're not a bot". Fixes in order of cost: latest yt-dlp + Deno JS
  runtime → PO-token provider (`bgutil-ytdlp-pot-provider`, Docker sidecar; partial fix, the
  maintainers say it no longer works in most cases) → cookies of a throwaway Google account (account
  ban risk) → **residential proxy** (paid, the only reliable fix at scale).
- **Legal:** YouTube's Terms don't allow downloading except through YouTube's own features, and
  OpusClip-style tools put the rights responsibility on the user. We should at least require a
  "I own this video or have the rights to it" tick box, and ideally (decision below) only accept links
  to videos on the user's **connected YouTube channel** (we already have YouTube OAuth): we check
  the video's `channelId` with the Data API before downloading.
- Upload always works and has none of these problems, so **upload ships first**, link import is behind
  a setting (`CLIPS_YOUTUBE_IMPORT`).

## User flow

1. **Agents → Clip Maker → Start.** Settings (changeable later): clip length (15–30 s / 30–60 s /
   60–90 s), how many clips (3–10), caption style (4 presets, Brand Kit colour), hook title on/off,
   layout (Auto / always track face / always fit), check-ins.
2. **New run:** paste a YouTube link *or* upload / pick a Library video. We show the title, length
   and a credit quote before starting.
3. Workflow view shows live steps: Getting video → Transcribing → Finding moments → Framing → Rendering.
4. **Check-in: pick the clips** (default on). A ranked list: score, hook, reason, transcript excerpt,
   a preview player that plays the original section. User ticks clips, drags start/end (snaps to
   words), edits the hook. Only ticked clips are rendered → users only pay for what they keep.
5. **Results:** a grid of vertical clips. Each: download, edit captions, **Publish** (existing Publish
   page) or **Cross-post** (existing Cross-poster agent) to YouTube / Instagram / Facebook / TikTok.

## Backend (new module `agents/clips.py`, same pattern as `video_edit.py`)

New built-in recipe `clip-maker` (kind `large`, `input_kind` `video_or_link`), steps:

| Step | What happens | Notes |
|---|---|---|
| `source` | Library asset → copy; YouTube link → `yt-dlp` (≤1080p, mp4, `--max-filesize`), optional proxy/cookies from env. `ffprobe` checks length/audio | Limit per plan (e.g. 60 / 120 min). Keep source 7 days |
| `transcribe_long` | Extract 16 kHz mono audio, split into 10-min chunks on silences with overlap, transcribe (provider chain), merge word timings | Reuses `providers.word_times` style; new `providers.transcribe_long()` |
| `scenes` | PySceneDetect `ContentDetector` on a 320–640 px proxy | Cheap on CPU |
| `find_moments` | Pass 1: classify video type. Pass 2: per 20-min window (60 s overlap) the LLM returns candidates with 0–100 score (hook, emotion, insight, payoff, standalone), hook text, reason. Then: snap to sentence ends + silences, enforce length, dedupe >50 %, top N. Pass 3: titles + per-platform captions for the winners | Prompts editable in the admin recipe like other agents |
| `review_clips` | Check-in gate (new `GATES` entry) | Credits for render charged after this point |
| `reframe` | Per clip: YuNet face detection every 4th frame at 640 px, speaker tracker + smoothed camera (constants above), per-scene layout TRACK / SPLIT / FIT. Output: crop track JSON | No MediaPipe: no Python 3.14 wheel. OpenCV ships abi3 wheels |
| `render_clips` | Per clip one FFmpeg pass: `-ss/-t`, `sendcmd` crop (or split/blur graph), scale 1080×1920, ASS word captions (`render.build_captions` + presets), hook title first 3 s, -14 LUFS, optional pause/um cuts reusing `video_edit` cut logic. `render.check_video` per clip | Resumable per clip: a crash re-renders only unfinished clips |
| `package` | Each clip → `LibraryAsset` (+ thumbnail), results in `run.output["clips"]` | A run has many outputs: `library_asset` stays the first, the list lives in `output` |

Other backend work:

- **Uploads:** Library video limit is 200 MB today. Long videos need **chunked/resumable upload**
  (up to ~2 GB) straight to disk, not via `DATA_UPLOAD_MAX_MEMORY_SIZE`.
- **Worker:** runs can take 10–30 min. Lease is 15 min today. Renew the lease between clips/chunks,
  and add `run_agents_worker --only clip-maker` / `--exclude clip-maker` so long clip jobs don't block
  Shorts and posts. Also fix today's crash: the worker loop must survive `database is locked`
  (seen locally on SQLite) instead of exiting.
- **Credits:** quote = transcription minutes + LLM calls + render minutes (CPU cost) × markup.
- **Security:** validate links (YouTube hosts only, no playlists/live), never pass user text to a
  shell, cap download size/length, per-user rate limit, temp files cleaned up.
- **Dependencies:** `yt-dlp`, `opencv-python-headless`, `numpy`, `scenedetect`, Deno (yt-dlp JS
  challenges). YuNet model file (~230 KB) shipped in the repo.

## Frontend

- Agent start screen: link field *or* upload/pick, settings above, credit quote.
- `AgentClipPicker.jsx`: ranked moments, preview player seeking the source, start/end handles, hook edit.
- `AgentClipResults.jsx`: vertical clip grid, download, Publish / Cross-post per clip.
- Resumable upload component for big files with a progress bar.

## Phases

| Phase | Scope | Rough effort |
|---|---|---|
| **0** | Worker survives DB lock; lease renewal; worker `--only/--exclude` | small |
| **1** | Upload **and YouTube link** → transcript → moments → **pick check-in** → centre/blur-fit render with word captions + hook → Library. Proves the whole loop end to end | medium |
| **2** | Face-tracked reframe (YuNet + tracker + smooth camera + scene snap), split screen for two people | medium-large |
| **3** | YouTube link hardening for the VPS (Deno, POT provider sidecar, optional proxy setting) | small-medium (mostly ops) |
| **4** | Resumable big uploads, caption presets, per-clip caption editing, trim silences/fillers in clips | medium |
| **5** (later) | Active-speaker detection from lip movement, B-roll from Pexels, auto-zoom punch-ins, other languages | — |

Each phase: tests first (unit tests for snapping, dedupe, tracker smoothing, chunk merging; one end
to end run in `AGENTS_DRY_RUN`), then real-video checks on a podcast, a solo talking head and a
screen recording.

## Decisions (owner, 2026-10-14)

1. **YouTube links:** any public video. The user must tick "I own this video or have the rights to
   use it"; no channel-ownership check. Playlists, live streams and private videos are rejected.
2. **Where it runs:** CPU on the VPS. No GPU.
3. **Max source length:** Free plan 30 min, paid plans 2 h.
4. **Providers:** fal and OpenRouter keys exist (paid models allowed in production). **For testing
   use free options**, chosen by settings, tried in order:
   - Transcription `CLIPS_TRANSCRIBE_PROVIDERS` (e.g. `groq,local,fal`): Groq free tier
     (`GROQ_API_KEY`) → local `faster-whisper` on CPU (free, no key; has a Python 3.14 build)
     → fal Whisper (paid).
   - Moments/titles: the existing OpenRouter text provider with free models in
     `AGENTS_OPENROUTER_MODELS` (e.g. `google/gemma-4-31b-it:free`); direct Gemini (`GEMINI_API_KEY`,
     already a setting) as an option. Production switches to the cheap paid models by `.env` only.
5. Phase 0 + 1 next, once the owner says go.
