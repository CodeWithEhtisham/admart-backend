"""Celery app: `celery -A config worker` and `celery -A config beat` (schedule in settings.CELERY_BEAT_SCHEDULE)."""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("admart")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
