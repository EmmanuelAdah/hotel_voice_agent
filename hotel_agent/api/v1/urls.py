"""API v1 URL patterns."""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView, TokenBlacklistView

from hotel_agent.api.views.main import (
    CustomTokenObtainPairView, RegisterView, VoiceSessionViewSet,
    ServiceRequestViewSet, RoomViewSet, BookingViewSet, HealthCheckView,
)

router = DefaultRouter()
router.register("voice/sessions", VoiceSessionViewSet, basename="voice-session")
router.register("service-requests", ServiceRequestViewSet, basename="service-request")
router.register("rooms", RoomViewSet, basename="room")
router.register("bookings", BookingViewSet, basename="booking")

urlpatterns = [
    # Auth
    path("auth/register/", RegisterView.as_view(), name="register"),
    path("auth/token/", CustomTokenObtainPairView.as_view(), name="token-obtain"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/token/blacklist/", TokenBlacklistView.as_view(), name="token-blacklist"),

    # Health
    path("health/", HealthCheckView.as_view(), name="health-check"),

    # Resource routers
    path("", include(router.urls)),
]
