"""API permissions, throttles, and pagination."""
from rest_framework import permissions, throttling, pagination
from rest_framework.response import Response
from hotel_agent.core.models import User


# ── Permissions ───────────────────────────────────────────────────────────────

class IsGuestOrStaff(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in (
            User.Role.GUEST, User.Role.STAFF, User.Role.MANAGER, User.Role.ADMIN
        )


class IsStaffOrAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in (
            User.Role.STAFF, User.Role.MANAGER, User.Role.ADMIN
        )


class IsManagerOrAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in (
            User.Role.MANAGER, User.Role.ADMIN
        )


class IsOwnerOrStaff(permissions.BasePermission):
    """Owner of a resource or staff can access."""
    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False
        if request.user.role in (User.Role.STAFF, User.Role.MANAGER, User.Role.ADMIN):
            return True
        # Check ownership
        owner = getattr(obj, "guest", None) or getattr(obj, "user", None)
        return owner == request.user


# ── Throttling ────────────────────────────────────────────────────────────────

class BurstRateThrottle(throttling.UserRateThrottle):
    scope = "burst"


class SustainedRateThrottle(throttling.UserRateThrottle):
    scope = "sustained"


class VoiceSessionThrottle(throttling.UserRateThrottle):
    scope = "voice_agent"


class AnonThrottle(throttling.AnonRateThrottle):
    scope = "anon"


# ── Pagination ────────────────────────────────────────────────────────────────

class StandardResultsPagination(pagination.PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response({
            "pagination": {
                "count": self.page.paginator.count,
                "num_pages": self.page.paginator.num_pages,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "current_page": self.page.number,
            },
            "results": data,
        })
