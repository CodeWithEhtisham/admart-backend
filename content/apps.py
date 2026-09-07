from django.apps import AppConfig
from django.db.models.signals import post_migrate


class ContentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "content"
    verbose_name = "Content / Image Generation"

    def ready(self):
        post_migrate.connect(_seed_templates_on_migrate, sender=self)


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
