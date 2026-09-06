"""The JSON API the React SPA consumes.

Hand-written Django views, not DRF (D1). Populated by phases 2.5, 4.5 and 5.5.
"""

from django.urls import include, path

urlpatterns = [
    path("", include("apps.identity.api_urls")),
    path("", include("apps.pipeline.api_urls")),
    path("", include("apps.sales.api_urls")),
    path("", include("apps.hr.api_urls")),
]
