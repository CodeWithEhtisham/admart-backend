"""Per-account storage: how much room a customer's files take and how much their plan allows.

Usage is every file in the account's project folders (library uploads, AI images and videos, agent
work files) plus their edit/upscale source images. Unfinished downloads (*.part) don't count. A full
account can't add files or start new jobs; nothing it already has is deleted for being over.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db.models import Sum
from django.utils import timezone

from users.entitlements import limits

GB = 1024**3
USAGE_CACHE_SECONDS = 60  # explicit storage_changed() calls refresh it sooner

# Bought like a top-up pack (Payment.payment_type "storage"); each purchase adds 30 days.
STORAGE_ADDON = {
    "id": "storage_50",
    "name": "Extra storage",
    "gb": 50,
    "price_usd": Decimal("3"),
    "price_pkr": 849,
    "days": 30,
}


def _folder_bytes(folder: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(folder):
        for name in files:
            if name.endswith(".part"):
                continue
            try:
                total += os.stat(os.path.join(root, name)).st_size
            except OSError:  # removed while we walked
                continue
    return total


def measure_used_bytes(user) -> int:
    """Walk the account's files now (uncached)."""
    from content.models import ImageUpload

    projects = Path(settings.MEDIA_ROOT) / "projects"
    total = sum(_folder_bytes(projects / str(pid)) for pid in user.projects.values_list("id", flat=True))
    return total + (ImageUpload.objects.filter(user=user).aggregate(total=Sum("byte_size"))["total"] or 0)


def _cache_key(user_id) -> str:
    return f"storage-used:{user_id}"


def used_bytes(user) -> int:
    used = cache.get(_cache_key(user.pk))
    if used is None:
        used = measure_used_bytes(user)
        cache.set(_cache_key(user.pk), used, USAGE_CACHE_SECONDS)
    return used


def storage_changed(user_id) -> None:
    """Call after adding or removing an account's files so the next check measures again."""
    cache.delete(_cache_key(user_id))


def addon_active(user) -> bool:
    return bool(user.extra_storage_until and user.extra_storage_until > timezone.now())


def plan_bytes(user) -> int:
    return int(Decimal(str(limits(user.plan).get("storage_gb", 0))) * GB)


def limit_bytes(user) -> int:
    return plan_bytes(user) + (STORAGE_ADDON["gb"] * GB if addon_active(user) else 0)


def extend_addon(user) -> None:
    """One more add-on period: from its current end while it's still on, else from now. Caller saves."""
    now = timezone.now()
    start = user.extra_storage_until if addon_active(user) else now
    user.extra_storage_until = start + timedelta(days=STORAGE_ADDON["days"])


def format_bytes(size: int) -> str:
    if size >= GB:
        return f"{size / GB:.1f} GB".replace(".0 GB", " GB")
    return f"{max(size, 0) / 1024**2:.0f} MB"


@dataclass(frozen=True)
class StorageFull:
    used: int
    limit: int
    incoming: int = 0

    @property
    def message(self) -> str:
        if self.incoming and self.used < self.limit:
            return (f"This file is {format_bytes(self.incoming)} but you only have "
                    f"{format_bytes(self.limit - self.used)} of storage left. "
                    "Delete files from your Library or get more storage.")
        return (f"Your storage is full ({format_bytes(self.used)} of {format_bytes(self.limit)}). "
                "Delete files from your Library or get more storage to keep creating.")

    def response_data(self) -> dict:
        return {"message": self.message, "code": "STORAGE_FULL", "storageUsed": self.used,
                "storageLimit": self.limit}


def storage_problem(user, incoming: int = 0) -> StorageFull | None:
    """None when the account has room for `incoming` more bytes (or, with 0, isn't already full)."""
    used, limit = used_bytes(user), limit_bytes(user)
    if (used + incoming > limit) if incoming else (used >= limit):
        return StorageFull(used, limit, incoming)
    return None


def storage_payload(user) -> dict:
    used, limit = used_bytes(user), limit_bytes(user)
    return {
        "usedBytes": used,
        "limitBytes": limit,
        "planBytes": plan_bytes(user),
        "extraBytes": limit - plan_bytes(user),
        "extraUntil": user.extra_storage_until if addon_active(user) else None,
        "full": used >= limit,
        "addon": {
            "id": STORAGE_ADDON["id"],
            "name": STORAGE_ADDON["name"],
            "gb": STORAGE_ADDON["gb"],
            "priceUsd": f"{STORAGE_ADDON['price_usd']:f}",
            "pricePkr": STORAGE_ADDON["price_pkr"],
            "days": STORAGE_ADDON["days"],
        },
    }
