"""Celery task for the template gallery (replaces the in-process refresh thread when USE_CELERY is on)."""

from celery import shared_task
from django.core.management import call_command


@shared_task(ignore_result=True)
def refresh_templates() -> None:
    call_command("fetch_meigen_templates", "--keep-owned", verbosity=0)
    call_command("recalculate_template_trends", verbosity=0)
