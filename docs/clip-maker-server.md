# Clip Maker — server setup (VPS, CPU only)

The Clip Maker turns a YouTube link or a long upload into vertical clips. It needs a few things on
the VPS beyond [agents-worker.md](agents-worker.md). Nothing in `deploy/` or the CI workflow changes:
these are one-time steps.

## 1. Packages

```bash
sudo apt install -y ffmpeg fonts-dejavu-core
curl -fsSL https://deno.land/install.sh | sh -s -- -y   # yt-dlp solves YouTube's JavaScript with Deno
sudo ln -sf ~/.deno/bin/deno /usr/local/bin/deno
/srv/admart/backend/.venv/bin/pip install -r /srv/admart/backend/requirements.txt   # yt-dlp, faster-whisper, OpenCV
```

`requirements.txt` pins yt-dlp. YouTube changes often: when downloads start failing, update it first
(`pip install -U yt-dlp`), run the tests, then pin the new version.

## 2. Backend `.env`

```bash
# Transcription, tried in order: Groq (free tier) → local faster-whisper on the CPU (free, ~6x real time
# on 12 cores with "base") → fal Whisper (paid). Drop "fal" to never pay for transcription.
GROQ_API_KEY=...
CLIPS_TRANSCRIBE_PROVIDERS=groq,local,fal
CLIPS_LOCAL_WHISPER_MODEL=base

# Picking moments: OpenRouter (AGENTS_OPENROUTER_MODELS), or Gemini when there is no OpenRouter key.
# Tested 2026-10-15: qwen/qwen3.7-flash picked the best moments for ~$0.0003 per video.
AGENTS_OPENROUTER_MODELS=qwen/qwen3.7-flash,nvidia/nemotron-3-super-120b-a12b:free,google/gemini-2.5-flash-lite

CLIPS_YTDLP_JS_RUNTIMES=deno,node
CLIPS_YTDLP_POT_URL=http://127.0.0.1:4416     # step 3
CLIPS_YTDLP_PROXY=                             # step 4, only if still blocked
CLIPS_KEEP_SOURCE_DAYS=7
```

## 3. YouTube on a server IP: PO-token provider

YouTube often answers a datacenter IP with "Sign in to confirm you're not a bot". The bgutil PO-token
provider fixes many of these cases (not all):

```bash
sudo docker run -d --name bgutil-pot --restart unless-stopped -p 127.0.0.1:4416:4416 brainicism/bgutil-ytdlp-pot-provider
/srv/admart/backend/.venv/bin/pip install bgutil-ytdlp-pot-provider   # the yt-dlp plugin that talks to it
```

Set `CLIPS_YTDLP_POT_URL=http://127.0.0.1:4416` and restart the Clip Maker worker. Check from the server:

```bash
cd /srv/admart/backend && .venv/bin/python -c "from agents.clips import youtube_info; print(youtube_info('https://www.youtube.com/watch?v=jNQXAC9IVRw'))"
```

## 4. Still blocked: residential proxy

If the check above still says "not a bot", only a residential proxy fixes it reliably (paid, per GB).
Set `CLIPS_YTDLP_PROXY=http://user:pass@host:port`. Uploads always work without any of this, and the
user sees a clear message suggesting an upload when YouTube blocks the server.

## 5. Its own worker

A 2-hour video takes several minutes, so the Clip Maker gets its own worker and never blocks Shorts or
scheduled posts. Copy the service from [agents-worker.md](agents-worker.md) twice:

- `admart-agents-worker.service`: `ExecStart=... manage.py run_agents_worker --exclude clip-maker`
- `admart-clips-worker.service`: `ExecStart=... manage.py run_agents_worker --only clip-maker`

Then `sudo systemctl daemon-reload && sudo systemctl enable --now admart-clips-worker`.

## 6. Disk: delete old source videos daily

Long sources are large (a 2-hour 1080p video is 2–4 GB). The clips themselves stay in the Library.

```bash
# crontab -e (as the deploy user)
30 3 * * * cd /srv/admart/backend && .venv/bin/python manage.py cleanup_clip_sources >> /var/log/admart-clip-cleanup.log 2>&1
```

Unfinished large uploads (`PRIVATE_MEDIA_ROOT/uploads`) are removed after a day automatically.

## 7. Limits

| | |
|---|---|
| Source length | Free plan 30 min, paid plans 2 h (`agents/clips.py`) |
| Upload size | 4 GB (`LIBRARY_LARGE_VIDEO_BYTES`), sent in 8 MB chunks; nginx's 210 MB body limit is enough |
| Clips per run | 3–10, 15–90 s each |
| CPU per clip | ~6 s face analysis per minute of clip + ~15 s render (1080×1920, x264 veryfast) |
