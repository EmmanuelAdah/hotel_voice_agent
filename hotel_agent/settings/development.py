"""Development settings."""
from .base import *  # noqa: F401, F403

DEBUG = True
SECRET_KEY = "dev-secret-key-not-for-production"  # noqa: S105

ALLOWED_HOSTS = ["*"]

# Disable SSL requirements in dev
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Django Debug Toolbar
INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405
MIDDLEWARE = ["debug_toolbar.middleware.DebugToolbarMiddleware"] + MIDDLEWARE  # noqa: F405
INTERNAL_IPS = ["127.0.0.1", "localhost"]

# Relaxed rate limits for dev
REST_FRAMEWORK = {  # noqa: F405
    **REST_FRAMEWORK,  # noqa: F405
    "DEFAULT_THROTTLE_CLASSES": [],
}

# Console email backend
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Eager Celery tasks for dev
CELERY_TASK_ALWAYS_EAGER = True

LOGGING["root"]["level"] = "DEBUG"  # noqa: F405
