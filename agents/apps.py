import logging
import os
import sys
import threading
import time

from django.apps import AppConfig

logger = logging.getLogger("agents.worker")


def starts_runner(argv, environ, *, AGENTS_RUNNER_WITH_RUNSERVER, USE_CELERY) -> bool:  # noqa: N803 — setting names
    """Whether this process is `manage.py runserver` serving requests and should run agents too.

    With the autoreloader, runserver is two processes: the parent only watches files and restarts the child
    (RUN_MAIN=true), which serves. Running agents in the child means a code change restarts them as well.
    """
    if not AGENTS_RUNNER_WITH_RUNSERVER or USE_CELERY or "runserver" not in argv[1:2]:
        return False
    return environ.get("RUN_MAIN") == "true" or "--noreload" in argv


def _run_forever() -> None:
    from django.core.management import call_command

    while True:
        try:
            call_command("run_agents_worker")
        except Exception:  # noqa: BLE001 — keep local agents running whatever one loop hit
            logger.exception("The agent runner stopped; starting it again in 5 seconds")
            time.sleep(5)


class AgentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "agents"

    def ready(self):
        from django.conf import settings

        if starts_runner(sys.argv, os.environ, AGENTS_RUNNER_WITH_RUNSERVER=settings.AGENTS_RUNNER_WITH_RUNSERVER,
                         USE_CELERY=settings.USE_CELERY):
            threading.Thread(target=_run_forever, name="agents-runner", daemon=True).start()
