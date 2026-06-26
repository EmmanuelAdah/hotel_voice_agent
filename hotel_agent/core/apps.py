"""Core application configuration."""
from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "hotel_agent.core"
    label = "core"
    verbose_name = "Hotel Agent Core"

    def ready(self):
        """Wire up signal handlers and startup routines."""
        import hotel_agent.core.signals  # noqa: F401
