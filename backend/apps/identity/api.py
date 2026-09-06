"""Session and identity endpoints."""

from __future__ import annotations

from django.contrib.auth import logout as django_logout
from django.http import HttpRequest, JsonResponse

from apps.core.api import api, iso, json_body, ok, require
from apps.identity.services import change_own_password, resolve_permissions, roles_for


def serialize_me(user) -> dict:
    """The session payload the SPA boots from.

    Grants, not role names. A client that branches on ``role == "SALES"``
    re-implements the permission grid in JavaScript and then drifts from it;
    a client that branches on ``client:create`` being present cannot.
    Role codes are included for display only — a "Signed in as Sales" label —
    and the SPA must not use them for access decisions.
    """
    return {
        "id": str(user.id),
        "username": user.username,
        "full_name": user.employee.full_name,
        "employee_id": str(user.employee_id),
        "employee_code": user.employee.employee_code,
        "department": user.employee.department.name,
        "must_change_password": user.must_change_password,
        "last_login": iso(user.last_login),
        "roles": [{"code": role.code, "name": role.name} for role in roles_for(user)],
        "grants": sorted(
            (
                {
                    "resource": grant.resource,
                    "action": grant.action,
                    "level": grant.perm_level,
                    "if_owner": grant.if_owner,
                }
                for grant in resolve_permissions(user)
            ),
            key=lambda g: (g["resource"], g["action"], g["level"]),
        ),
    }


@api(["GET"])
def me(request: HttpRequest) -> JsonResponse:
    return ok(serialize_me(request.user))


@api(["POST"])
def change_password(request: HttpRequest) -> JsonResponse:
    payload = json_body(request)
    old_password, new_password = require(payload, "old_password", "new_password")
    change_own_password(request.user, old_password, new_password)
    return ok({"changed": True, "must_change_password": False})


@api(["POST"])
def logout(request: HttpRequest) -> JsonResponse:
    django_logout(request)
    return ok({"signed_out": True})
