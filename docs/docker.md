# Docker (local development)

One backend image and one frontend image run the whole app:

| Container | Image | What it does |
|---|---|---|
| `db` | postgres:17 | Database (same engine as production) |
| `redis` | redis:7.4 | Celery broker **and** Django's shared cache (rate limits and locks work across processes) |
| `web` | admart-backend (dev) | Django API on http://localhost:8000; runs migrations on start |
| `worker` | admart-backend (dev) | Celery worker: agent runs (renders, uploads, reports) |
| `beat` | admart-backend (dev) | Celery Beat: every 15 s starts due Autopilot/report slots, resumes scheduled posts, recovers stuck runs; template gallery refresh every 30 min |
| `frontend` | admart-frontend (dev) | Vite on http://localhost:5173 |

The frontend repo must sit next to this one (`../Admart-frontend`).

## Start and stop

```bash
./dev.sh                 # build if needed, start everything, follow the logs (Ctrl+C stops following only)
./dev.sh down            # stop
./dev.sh ps              # status
./dev.sh logs -f worker  # one container's logs
./dev.sh exec web python manage.py createsuperuser
```

`dev.sh` runs the containers as your user, so files they write (media, renders) stay yours.
Ports in use already? `BACKEND_PORT=8100 FRONTEND_PORT=5180 ./dev.sh`.

## Code changes apply automatically

- **Backend:** the folder is mounted into the containers. Django reloads on save; the Celery worker and beat
  restart on any `.py` change (watchmedo).
- **Frontend:** Vite hot-reloads in the browser.
- **New Python or npm packages:** `./dev.sh up --build -d` (the images rebuild only what changed).

## Settings

Containers read the backend `.env`, then compose sets `POSTGRES_*` (Docker database), `REDIS_URL`,
`USE_CELERY=True` and `CORS_ORIGINS`. Everything else (API keys, `DEBUG`, `AGENTS_DRY_RUN`...) comes from `.env`.

## Your existing data

The Docker database starts empty. To copy your local SQLite data in (one time):

```bash
./dev.sh                                   # stack running
scripts/sqlite_to_docker_postgres.sh       # empties the Docker DB, then loads db.sqlite3
```

`db.sqlite3` is not changed. Docker data lives in the `admart_pgdata` volume (`docker compose down -v` deletes it).

## How background tasks work

- A new run, a run resumed after a check-in, or a retried run is sent to the worker at once
  (`agents.tasks.dispatch`). Beat's `agents.tasks.sweep` is the safety net. Each run is claimed atomically,
  so a run never goes to two workers.
- Scheduled posts (Cross-poster) wait in the database until their time; the sweep starts them.
- Without Celery (`USE_CELERY` off: the current server), `manage.py run_agents_worker` does the same job, and
  the template refresh runs in a thread as before. Nothing in `deploy/` or CI changed.

## Production images

`docker build --target prod` gives gunicorn (backend) and an nginx static site (frontend; pass the `VITE_*`
values as `--build-arg`). Tested 2026-10-15: both start. The backend refuses to start without the production
settings it always needs: `SECRET_KEY`, `SOCIAL_TOKEN_ENCRYPTION_KEY`, `ALLOWED_HOSTS`, the `POSTGRES_*` values
and `REDIS_URL` + `USE_CELERY=True` (then run the same image as `celery -A config worker` and `celery -A config beat`). The backend image doesn't serve `/static` or `/media`: put nginx or a CDN in front
(see `deploy/nginx-admart.conf`). Moving the server to Docker is a separate step with its own deploy changes.
