from rest_framework import permissions


class IsAdmin(permissions.BasePermission):
    """Allow access to staff members (view + support actions)."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_staff
        )


class IsOwnerAdmin(permissions.BasePermission):
    """Allow access to superusers only (plan/credit/payment mutations)."""

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_superuser
        )
