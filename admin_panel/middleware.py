from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone


class UpdateLastActiveMiddleware:
    """Touch ``User.last_active_at`` for authenticated users.

    Writes at most once per 15 minutes per user (LocMemCache-backed guard) so
    polling-heavy pages don't hammer the database. Supports the admin "active
    customers" metric and per-customer last-activity display.
    """

    GUARD_KEY = "admin:last_active:{user_id}"
    GUARD_SECONDS = int(15 * 60)

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            key = self.GUARD_KEY.format(user_id=user.pk)
            if cache.add(key, "1", timeout=self.GUARD_SECONDS):
                from users.models import User

                User.objects.filter(pk=user.pk).update(last_active_at=timezone.now())
        return response
