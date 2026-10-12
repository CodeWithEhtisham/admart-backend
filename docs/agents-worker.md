# Agents worker — server setup

Agent runs (YouTube Shorts Creator, Script Writer, Voiceover) are processed by a separate
process, `manage.py run_agents_worker`. Without it, runs stay "Queued".

Nothing in `deploy/` or the CI workflow changes. These are one-time steps on the VPS.

## 1. FFmpeg (CPU only, no GPU needed)

```bash
sudo apt install -y ffmpeg fonts-dejavu-core
ffmpeg -version | head -1
```

## 2. Free local models (voice + caption timing)

```bash
cd /srv/admart/backend
.venv/bin/pip install -r requirements.txt          # deploys do this already
.venv/bin/python manage.py download_agent_models   # ~250 MB, once
```

This downloads the Kokoro voice and the faster-whisper caption-timing model into
`agent_models/` (git-ignored). Both run on the CPU.

## 3. Backend `.env`

Each job tries its providers in order and skips any that aren't set up. Free first:

| Job | Free | Paid fallback |
|---|---|---|
| Script, concepts, research | Gemini free tier (`GEMINI_API_KEY`), then Groq free tier (`GROQ_API_KEY`) | — |
| Voice | Kokoro (local), then Gemini TTS free tier | OpenAI (`OPENAI_API_KEY`) |
| Images | Cloudflare Workers AI free allowance (`CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`) | fal (`FAL_KEY`) |
| Caption timing | faster-whisper (local) | OpenAI; otherwise an even estimate |
| Stock video | Pexels (`PEXELS_API_KEY`) | — |

Cloudflare token: create one with the "Workers AI" permission in the Cloudflare dashboard.


Minimal free setup:

```bash
GEMINI_API_KEY=...              # free tier (already used for AI suggestions)
GROQ_API_KEY=...                # optional free fallback for text
CLOUDFLARE_ACCOUNT_ID=...       # free images
CLOUDFLARE_API_TOKEN=...
AGENTS_DRY_RUN=False            # True = free test mode: placeholder images, silent audio, 0 credits
PEXELS_API_KEY=                 # optional, free: real stock video for suitable scenes
# Optional paid fallbacks: OPENAI_API_KEY (voice/timings), FAL_KEY (images)
AGENTS_MUSIC_DIR=/srv/admart/agent_music   # optional: royalty-free tracks for background music
```

### Background music

Put 10–20 royalty-free tracks you are allowed to use on YouTube (for example from the
YouTube Audio Library) as `.mp3`, `.m4a` or `.wav` in `AGENTS_MUSIC_DIR`. Each Short picks one,
loops or trims it to length, and ducks it under the narration. No tracks = no music.

`MEDIA_BASE_URL` must be the public API origin (e.g. `https://api.example.com`) so YouTube
uploads and the library can fetch the rendered video.

## 4. systemd service

Create `/etc/systemd/system/admart-agents-worker.service`:

```ini
[Unit]
Description=Admart agents worker
After=network.target postgresql.service
# Restarted together with the backend, so every deploy (which restarts
# admart-backend) also reloads the worker's code.
PartOf=admart-backend.service

[Service]
User=deploy
Group=www-data
WorkingDirectory=/srv/admart/backend
UMask=0027
ExecStart=/srv/admart/backend/.venv/bin/python manage.py run_agents_worker
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target admart-backend.service
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now admart-agents-worker
sudo systemctl status admart-agents-worker --no-pager
journalctl -u admart-agents-worker -f     # live log
```

## Notes

- One worker handles one run at a time; a Short takes roughly 1–3 minutes of CPU. For more
  throughput, add a second service with the same content under another name — runs are
  claimed atomically, so two workers never take the same run.
- If the worker dies mid-run, the run is picked up again after 15 minutes and resumes from
  its last finished step; after 3 attempts it fails and the credits are refunded.
- YouTube API upload quota is per Google Cloud project; check it before enabling Shorts for
  many users.
