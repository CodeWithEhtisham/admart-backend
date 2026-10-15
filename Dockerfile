# syntax=docker/dockerfile:1
# One backend image for every backend container: web (Django), worker (Celery) and beat (Celery Beat).
#   dev  (default for docker compose): code is bind-mounted, servers reload on change
#   prod: code baked in, gunicorn; serve /static and /media from a reverse proxy (see docs/docker.md)

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/tmp
# FFmpeg renders agent videos; DejaVu is the caption font (AGENTS_CAPTION_FONT).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core curl \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

FROM base AS dev
# watchdog restarts Celery when Python files change (Django's runserver reloads by itself).
RUN pip install watchdog==6.0.0
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

FROM base AS prod
COPY . .
RUN useradd --create-home --uid 10001 app \
    && DEBUG=True python manage.py collectstatic --noinput --verbosity 0 \
    && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", \
     "--worker-class", "gthread", "--threads", "4", "--timeout", "120"]
