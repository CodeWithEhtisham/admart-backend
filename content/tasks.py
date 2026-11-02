"""Celery tasks for the template gallery (replaces the in-process refresh thread when USE_CELERY is on),
the fal price snapshot and the daily storage cleanup."""

from celery import shared_task
from django.core.management import call_command


@shared_task(ignore_result=True)
def refresh_templates() -> None:
    call_command("fetch_meigen_templates", "--keep-owned", verbosity=0)
    call_command("recalculate_template_trends", verbosity=0)


@shared_task(ignore_result=True)
def refresh_fal_prices() -> None:
    call_command("refresh_fal_prices", verbosity=0)


@shared_task(ignore_result=True)
def discover_fal_models() -> None:
    call_command("discover_fal_models", verbosity=0)


@shared_task(ignore_result=True)
def clean_storage() -> None:
    call_command("clean_storage", verbosity=0)
