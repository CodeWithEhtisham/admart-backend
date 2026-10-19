# Video Editor agent — Phase 1 plan

Branch: `feature/agents` in both repos (staging is live; merge via PR only, no pipeline changes).

## Goal

A user uploads their own video (talking head, tutorial, product clip). The agent cleans it up and
hands back a ready-to-post vertical video for approval, then the existing Publish page posts it.

What it fixes automatically:

| Problem | How | Service |
|---|---|---|
| Long pauses, dead air | Silence detection, cut with short padding | FFmpeg (server) |
| "Um/uh", false starts, repeated takes | Word-level transcript; filler list + AI marks retakes | fal Whisper + OpenRouter |
| Background noise, quiet/uneven voice | Noise removal (quality level the user picks), then loudness to -14 LUFS | FFmpeg / fal `veed/clean-audio` / fal ElevenLabs |
| Caption spelling (names, brands, terms) | AI corrects the transcript using the Brand Kit; captions burned in | OpenRouter + our caption renderer |
| Black / frozen frames | `blackdetect` / `freezedetect`, cut them | FFmpeg |
| Wrong shape for the platform | Crop to the format the user picks (9:16, 1:1, 4:5 or original) | FFmpeg |
| Title, description, tags, thumbnail text | Hook/title rules from `agents/hooks.py` | OpenRouter |

Nothing is published without approval (same rule as every agent).

### Phase 1 limits

- Videos **up to 3 minutes** and **200 MB** (the Library's existing upload limit); MP4, MOV or WebM.
- Must have an audio track; English captions.
- One render at a time per worker (CPU only; a 3-minute 1080p render takes ~1–3 minutes on a small VPS).

### Not in Phase 1

Face-tracking reframe, videos longer than 3 minutes, "long video → several Shorts", B-roll and zooms,
re-speaking wrong words (would need voice cloning: consent/misuse risk, left out), stabilisation and
colour correction, other languages.

## User flow

1. **Agents → Video Editor → Start.** The user picks (and can change later in Settings):
   - **Format:** 9:16 vertical (Reels/Shorts/TikTok, default), 1:1 square, 4:5 portrait
     (Instagram/Facebook feed) or keep original.
   - **Cut style:** Gentle, Normal (default) or Tight.
   - **Audio cleanup**, with the price shown:

     | Level | Service | Price | 3-minute video |
     |---|---|---|---|
     | Basic (free) | FFmpeg noise filter on our server | $0 | $0 |
     | Standard (default) | fal `veed/clean-audio` | $0.0125/min | ~$0.04 |
     | Studio | fal ElevenLabs audio isolation | $0.10/min | ~$0.30 |

   - Captions on/off, background music on/off, check-ins.
2. **Make a video:** pick a video from the Library or upload one (reuses `library/uploads`).
3. The workflow view shows each step live (same UI as the Shorts agent).
4. **Check-in: review the edit** (on by default). The transcript is shown with the parts the agent
   wants to cut struck through and labelled (pause, filler, retake, black frames). Click a cut to keep
   it, click a word to cut it. Caption text is editable here (spelling fixes are highlighted).
   A before/after audio sample plays for the noise cleanup.
5. **Final review:** the edited video, title, description, tags, thumbnail text and title check →
   **Approve & publish…** opens the Publish page, as today.

## Backend

### Recipe

New built-in recipe `video-editor` (kind `large`, `input_kind="video"`, `review=True`):

```
prepare → transcribe → clean_audio → plan_edit → review_edit → render_edit → package → finish
```

`input_kind="video"`: the run input is `{"assetId": <LibraryAsset id>}`. The run view validates the
asset belongs to the project, is a video and is ready. Recipes can't mix video steps with topic
steps (`validate_recipe`).

### Steps (each idempotent: skipped when its output exists)

| Step | Does | Output (`run.output`) |
|---|---|---|
| `prepare` | Copy the asset into the run folder; `ffprobe` duration/size/streams; reject > 3 min, no audio, unreadable | `source`, `source_info` |
| `transcribe` | Extract 16 kHz mono audio; fal Whisper, `chunk_level=word` | `words: [{word, start, end}]`, `text` |
| `clean_audio` | By the chosen level: Basic = FFmpeg `afftdn`; Standard = fal `veed/clean-audio`; Studio = fal ElevenLabs isolation. If a fal service fails, falls back to Basic and notes it | `audio_clean`, `audio_level_used` |
| `plan_edit` | Build the cut list (rules below); one OpenRouter call returns retake ranges + caption spelling fixes | `cuts: [{start, end, reason, keep}]`, `caption_fixes: [{index, from, to}]` |
| `review_edit` | Check-in gate `edit` (skipped when check-ins are "final only") | — |
| `render_edit` | Keep segments → trim + concat (cleaned audio), 30 ms audio crossfades, reframe, ASS captions from corrected words (re-timed to the cut timeline), optional music ducked, `loudnorm` -14 LUFS, quality checks (existing `check_video`) | `video`, `thumbnail`, `duration`, `checks` |
| `package` | Title, description, tags, thumbnail text from the transcript, using `TITLE_RULES` + `lint_title` | `title`, `description`, `tags`, `thumbnail_text`, `title_check` |
| `finish` | Save to the Library (existing step) | `library_asset` |

### Cut rules

- **Pauses:** FFmpeg `silencedetect` (noise −35 dB). Gaps longer than Gentle 1.0 s / Normal 0.6 s /
  Tight 0.35 s are cut down to 0.2 s of padding each side.
- **Fillers:** whole words "um, uh, erm, ah, hmm" (and "like / you know" only in Tight), using the
  Whisper word times ± 40 ms. Never cut inside another word.
- **Retakes / false starts:** the AI gets the transcript with word numbers and returns ranges where the
  speaker restarts a sentence; keep the last complete attempt. Limited to 15% of the video unless Tight.
- **Black / frozen frames:** `blackdetect` (≥ 0.3 s) and `freezedetect` (≥ 1.5 s) at the start/end
  and anywhere in between.
- Merge overlapping cuts; never leave a kept segment shorter than 0.3 s.

### Reframe (Phase 1)

Centre crop to the chosen format, then scale: 9:16 → 1080×1920, 1:1 → 1080×1080,
4:5 → 1080×1350. A video already in that shape is only scaled; "Keep original" keeps the shape
(longest side up to 1920). (Phase 2: face tracking to move the crop window.)

### Credits

Reserved at start like other agents, from the video length:

| Item | fal price (pricing API, 2026-10-13) | 3-minute video |
|---|---|---|
| Whisper | $0.0008 per compute second | ~$0.01–0.02 |
| Audio cleanup | Basic $0 / Standard $0.0125 per min / Studio $0.10 per min | $0 / ~$0.04 / ~$0.30 |
| OpenRouter text (free models) | $0 (set `AGENTS_LLM_USD_PER_RUN` for paid) | $0 |
| **Total** | | **~$0.02 / ~$0.06 / ~$0.32** before markup |

The quote on the start screen and the run button changes with the chosen level and the video length.

### API changes

- `POST /api/projects/:pid/agents/:id/runs` accepts `{"assetId": …}` for video agents.
- `continue` at the `edit` gate accepts `{"cuts": [{start, end, keep}], "captions": [{index, text}]}`.
- `run_data` adds `words`, `cuts`, `captionFixes`, `sourceUrl`, `audioCleanUrl`.

## Frontend

- Catalog: Video Editor card (`large`).
- Start dialog and Settings: format, cut style and audio level as picker cards (audio cards show the
  price per minute), captions, music, check-ins (reuses `AgentStylePicker`'s pattern).
- Agent page "Make a video": Library picker (videos only) + Upload button instead of the topic box.
- Workflow view: new steps Prepare, Transcript, Clean audio, Edit plan, Review edit, Video, Package.
- **Edit review screen:** transcript with struck-through cuts (colour by reason), click to toggle,
  "Keep all pauses / fillers" shortcuts, editable caption lines, total time saved, before/after audio.

## Tests

- Cut planning: silences, fillers, retakes merged; padding; minimum segment; cut-style thresholds.
- Caption re-timing after cuts; spelling fixes applied.
- `prepare` rejects long / silent / non-video files and other users' assets.
- Render on a generated test clip (tone + colour bars + a black second): output length = kept time ± 0.1 s, 1080×1920, passes checks.
- fal and OpenRouter faked as in the existing provider tests; credits reserve/refund.

## Estimate

About 2–3 days: backend steps + tests ~1.5 days, edit-review screen + picker ~1 day, real test ~0.5 day.

## Decisions (user, 2026-10-13)

- Videos up to 3 minutes in Phase 1.
- Format, cut style and audio cleanup level are user choices (defaults: 9:16, Normal, Standard).
