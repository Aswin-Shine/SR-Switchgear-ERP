"""Plain Django views for the sales domain — not apps.sales.api_urls, which
is JSON-only (D1). Mounted at /print/ in config/urls.py."""

from django.urls import path

from apps.sales import views

urlpatterns = [
    path("job-card/<str:job_no>", views.print_job_card, name="print-job-card"),
]
