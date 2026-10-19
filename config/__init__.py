# Load Celery with Django so @shared_task uses this app.
from .celery import app as celery_app

__all__ = ("celery_app",)
