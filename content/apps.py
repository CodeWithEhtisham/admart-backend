import logging
import os
import threading

from django.apps import AppConfig
from django.db.models.signals import post_migrate

logger = logging.getLogger(__name__)


class ContentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "content"
    verbose_name = "Content / Image Generation"

    def ready(self):
        post_migrate.connect(_seed_templates_on_migrate, sender=self)
        _start_template_auto_refresher()


def _seed_templates_on_migrate(app_config, **kwargs):
    """Auto-seed owned templates after every `python manage.py migrate`.

    Only runs for the 'content' app in non-test environments.
    """
    if app_config.name != "content":
        return
    from django.conf import settings

    if getattr(settings, "TESTING", False):
        return
    from django.core.management import call_command

    call_command("seed_templates", verbosity=0)


def _start_template_auto_refresher():
    """Start a background thread that refreshes the template gallery.

    Totally free (no Celery/cron/external service): a daemon thread inside
    the Django process re-fetches templates from meigen.ai and recalculates
    trending counters every TEMPLATE_AUTO_REFRESH_MINUTES (default 30;
    set to 0 to disable). The first refresh runs ~2 minutes after startup.
    """
    from django.conf import settings

    if getattr(settings, "TESTING", False):
        return

    try:
        interval_minutes = int(os.getenv("TEMPLATE_AUTO_REFRESH_MINUTES", "30"))
    except ValueError:
        interval_minutes = 30
    if interval_minutes <= 0:
        return

    # runserver with autoreload calls ready() twice (parent + child).
    # Only the child (RUN_MAIN=true) serves requests, so only it should refresh.
    if settings.DEBUG and os.environ.get("RUN_MAIN") != "true":
        return

    if getattr(settings, "_template_refresher_started", False):
        return
    settings._template_refresher_started = True

    def _refresh_loop():
        import time

        from django.core.management import call_command

        # Give startup (migrations, etc.) time to settle before the first fetch.
        time.sleep(120)
        while True:
            try:
                call_command("fetch_meigen_templates", "--keep-owned", verbosity=0)
                call_command("recalculate_template_trends", verbosity=0)
                logger.info("Template gallery auto-refresh completed.")
            except Exception:  # noqa: BLE001 — never let the scheduler die
                logger.exception("Template gallery auto-refresh failed; will retry next cycle.")
            time.sleep(interval_minutes * 60)

    threading.Thread(
        target=_refresh_loop,
        name="template-auto-refresh",
        daemon=True,
    ).start()
