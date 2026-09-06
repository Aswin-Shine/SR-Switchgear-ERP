"""Server-rendered pages: login, password change, and the SPA shell.

D1 keeps these off the JSON API deliberately. Login is the one place a browser
redirect is the right answer rather than a 401, and a forced password change
must be un-skippable — which is easier to guarantee in a view than in a client
the user could simply not run.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.core.exceptions import DomainError
from apps.identity.services import change_own_password


class ERPLoginView(LoginView):
    template_name = "identity/login.html"
    redirect_authenticated_user = True

    def get_success_url(self) -> str:
        # A user carrying must_change_password goes nowhere else until it is
        # cleared. The SPA never sees a session that still has it set.
        if self.request.user.must_change_password:
            return reverse("password-change")
        return super().get_success_url()


class ERPLogoutView(LogoutView):
    next_page = "/login/"


@login_required
def password_change(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        old_password = request.POST.get("old_password", "")
        new_password = request.POST.get("new_password", "")
        confirm = request.POST.get("confirm_password", "")

        if new_password != confirm:
            messages.error(request, "The two new passwords do not match.")
        else:
            try:
                change_own_password(request.user, old_password, new_password)
            except DomainError as exc:
                messages.error(request, exc.message)
            else:
                # Rotating the password rotates the session hash; without this
                # the user is logged out by their own successful change.
                update_session_auth_hash(request, request.user)
                messages.success(request, "Your password has been changed.")
                return redirect("/app/")

    return render(
        request,
        "identity/password_change.html",
        {"forced": request.user.must_change_password},
    )


@login_required
def app_shell(request: HttpRequest, subpath: str | None = None) -> HttpResponse:
    """Serve the built SPA.

    Rendered as a Django template rather than served as a static file so the
    CSRF token can be embedded in a meta tag. That is what lets
    CSRF_COOKIE_HTTPONLY stay True: the client reads the token from the
    document instead of from a readable cookie.

    ``subpath`` is unused: it exists only so the same view answers every
    /app/<anything> URL (see identity/urls.py) — the SPA owns everything
    under that prefix client-side, this just has to serve the same shell
    regardless of which sub-route a direct navigation or refresh names.
    """
    if request.user.must_change_password:
        return redirect("password-change")
    return render(request, "index.html")
