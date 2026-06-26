"""Main URL configuration."""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django_prometheus import exports as prometheus_exports

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("hotel_agent.api.v1.urls")),
    path("metrics/", prometheus_exports.ExportToDjangoView, name="prometheus-metrics"),
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns += [path("__debug__/", include(debug_toolbar.urls))]
