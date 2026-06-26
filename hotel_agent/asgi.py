"""ASGI application - HTTP + WebSocket routing."""
import os
from django_asgi_app.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django_asgi_app.urls import re_path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hotel_agent.settings.production")

# Initialize Django before importing consumers
django_asgi_app = get_asgi_application()

from hotel_agent.api.consumers import VoiceSessionConsumer  # noqa: E402

websocket_urlpatterns = [
    re_path(
        r"ws/voice/(?P<session_id>[0-9a-f-]+)/$",
        VoiceSessionConsumer.as_asgi(),
    ),
]

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        URLRouter(websocket_urlpatterns)
    ),
})
