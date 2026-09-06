from django.urls import path
from django.views.generic.base import RedirectView

from apps.identity import views

urlpatterns = [
    # "/" has no view of its own — bounce to "/app/", whose own @login_required
    # already sends an anonymous visitor on to "/login/?next=/app/" and an
    # authenticated one straight into the SPA. Not permanent: a 301 here would
    # let browsers cache past a user's own session state.
    path("", RedirectView.as_view(pattern_name="app", permanent=False)),
    path("login/", views.ERPLoginView.as_view(), name="login"),
    path("logout/", views.ERPLogoutView.as_view(), name="logout"),
    path("password/change/", views.password_change, name="password-change"),
    path("app/", views.app_shell, name="app"),
    # The SPA owns everything under this prefix client-side (see
    # frontend/src/app/router.tsx) — a direct navigation or refresh on any
    # sub-route (e.g. /app/board, /app/job-cards/<id>) needs the same shell,
    # not a 404, so React Router can take over and resolve it itself.
    path("app/<path:subpath>", views.app_shell, name="app-subpath"),
]
