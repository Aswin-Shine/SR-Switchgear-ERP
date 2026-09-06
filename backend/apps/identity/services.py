"""The RBAC engine.

Everything that answers "may this person do this?" lives here. No caller
compares a role code against a literal; callers ask for a (resource, action)
pair and this module consults ``auth_role_permissions``.

That indirection is the point of the whole design. "Only HR and the CEO may
create accounts" (D3) is implemented as the permission ``user_account:create``,
so moving that authority to a different role is an UPDATE against seed data,
not a code change and not a deployment.
"""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass
from typing import Any

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from apps.core.db import audit_actor
from apps.core.exceptions import PermissionDenied, RuleViolation
from apps.identity import constants
from apps.identity.models import Role, RolePermission, UserAccount, UserRole

PASSWORD_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*-_"


@dataclass(frozen=True, slots=True)
class Grant:
    """One resolved capability."""

    resource: str
    action: str
    perm_level: int
    if_owner: bool

    def covers(self, level: int) -> bool:
        return self.perm_level >= level


# --- Ownership ---------------------------------------------------------------
#
# `if_owner` is meaningless without a definition of "own". Rather than guess
# from field names at runtime, each model states its rule explicitly. A model
# absent from this table has no notion of ownership, and an owner-scoped grant
# over it can never be satisfied — which is the safe direction to fail.

def _owns_user_account(user: UserAccount, obj) -> bool:
    return obj.pk == user.pk


def _owns_employee(user: UserAccount, obj) -> bool:
    return obj.pk == user.employee_id


def _owns_employee_document(user: UserAccount, obj) -> bool:
    return obj.employee_id == user.employee_id


def _owns_by_field(field: str):
    def check(user: UserAccount, obj) -> bool:
        return getattr(obj, field, None) == user.pk

    return check


OWNERSHIP_RULES: dict[str, Any] = {
    "identity.UserAccount": _owns_user_account,
    "hr.Employee": _owns_employee,
    "hr.EmployeeDocument": _owns_employee_document,
    "core.Document": _owns_by_field("uploaded_by_id"),
    "sales.Client": _owns_by_field("created_by_id"),
    "sales.JobCard": _owns_by_field("owner_user_id"),
    "sales.Quotation": _owns_by_field("prepared_by_id"),
    "sales.JobNote": _owns_by_field("author_user_id"),
}


def is_owner(user: UserAccount, obj: Any) -> bool:
    """Whether ``obj`` belongs to ``user``, by that model's explicit rule."""
    if obj is None:
        return False
    label = f"{obj._meta.app_label}.{obj._meta.object_name}"
    rule = OWNERSHIP_RULES.get(label)
    if rule is None:
        # sales.JobLine has no owner of its own; it inherits its card's.
        if label == "sales.JobLine":
            return obj.job_card.owner_user_id == user.pk
        return False
    return rule(user, obj)


# --- Resolution --------------------------------------------------------------

_CACHE_ATTR = "_resolved_grants"


def resolve_permissions(user: UserAccount | None) -> frozenset[Grant]:
    """Every capability ``user`` holds, unioned across their active roles.

    Rules, in order:

    * no user, an inactive user, or a soft-deleted user holds nothing;
    * grants from inactive roles are ignored;
    * for a given (resource, action), the highest ``perm_level`` wins;
    * an owner-scoped grant is dropped when an unrestricted grant for the same
      pair covers it.

    That last rule is deliberately narrower than "if_owner is dropped whenever
    any non-owner grant exists". Consider a role granting
    ``employee_document:view`` at level 2 but only over one's own records,
    alongside another role granting it at level 0 unrestricted. Collapsing
    those to a single unrestricted level-2 grant would hand out every
    employee's Aadhaar scan on the strength of a level-0 grant. So an
    owner-scoped grant survives when it reaches *higher* than any unrestricted
    grant for the same pair, and the two coexist in the result. On the
    Appendix B grid as written the two readings agree — no owner-scoped cell
    outranks an unrestricted one — so this costs nothing today and closes an
    escalation path if the grid is ever edited.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return frozenset()
    if not user.is_active or user.deleted_at is not None:
        return frozenset()

    cached = getattr(user, _CACHE_ATTR, None)
    if cached is not None:
        return cached

    rows = (
        RolePermission.objects.filter(
            role__user_roles__user=user,
            role__is_active=True,
        )
        .values_list(
            "permission__resource", "permission__action", "perm_level", "if_owner"
        )
        .distinct()
    )

    # (resource, action) -> highest level seen, per scope
    best: dict[tuple[str, str], dict[bool, int]] = {}
    for resource, action, perm_level, if_owner in rows:
        scopes = best.setdefault((resource, action), {})
        if perm_level > scopes.get(if_owner, -1):
            scopes[if_owner] = perm_level

    grants: set[Grant] = set()
    for (resource, action), scopes in best.items():
        unrestricted = scopes.get(False)
        owner_only = scopes.get(True)
        if unrestricted is not None:
            grants.add(Grant(resource, action, unrestricted, if_owner=False))
        # Keep the owner-scoped grant only where it reaches higher.
        if owner_only is not None and (unrestricted is None or owner_only > unrestricted):
            grants.add(Grant(resource, action, owner_only, if_owner=True))

    resolved = frozenset(grants)
    _cache_grants(user, resolved)
    return resolved


def _cache_grants(user: UserAccount, grants: frozenset[Grant]) -> None:
    """Memoise on the instance. Lives as long as the request does."""
    try:
        object.__setattr__(user, _CACHE_ATTR, grants)
    except AttributeError:  # pragma: no cover — defensive
        pass


def invalidate_permission_cache(user: UserAccount) -> None:
    """Call after changing a user's roles within the same request."""
    if hasattr(user, _CACHE_ATTR):
        delattr(user, _CACHE_ATTR)


def has_permission(
    user: UserAccount | None,
    resource: str,
    action: str,
    obj: Any = None,
    level: int = 0,
) -> bool:
    """Whether ``user`` may perform ``action`` on ``resource`` at ``level``.

    When the only grants covering the request are owner-scoped, ``obj`` must be
    supplied and must belong to the user. Passing no object in that situation
    answers False: the question "may you edit *a* record" cannot be answered
    yes when the honest answer is "only your own".
    """
    for grant in resolve_permissions(user):
        if grant.resource != resource or grant.action != action:
            continue
        if not grant.covers(level):
            continue
        if not grant.if_owner:
            return True
        if obj is not None and is_owner(user, obj):
            return True
    return False


def require_permission(
    user: UserAccount | None,
    resource: str,
    action: str,
    obj: Any = None,
    level: int = 0,
) -> None:
    """``has_permission`` or raise. The form services should normally use."""
    if not has_permission(user, resource, action, obj=obj, level=level):
        raise PermissionDenied(
            f"You do not have permission to {action} {resource}.",
            resource=resource,
            action=action,
            level=level,
        )


def has_any_permission(user: UserAccount | None, resource: str, action: str) -> bool:
    """Whether the pair is granted at all, ignoring scope.

    For menus and index pages — "should this section be visible" — not for
    authorising an operation.
    """
    return any(
        g.resource == resource and g.action == action for g in resolve_permissions(user)
    )


def owner_scope_for(
    user: UserAccount | None, resource: str, action: str
) -> UserAccount | None:
    """Authorise a *list* endpoint and say how far the result set may reach.

    ``require_permission`` answers a yes/no question about one object; a list
    view needs a different answer — "how much of the table may this response
    include" — since passing ``obj=None`` to an owner-scoped-only grant always
    reads as "no" (the honest answer to "may you view *a* record" when the
    real answer is "only your own").

    Returns ``None`` when the user holds an unrestricted grant for the pair
    (list everything, same as before), or ``user`` itself when every grant
    they hold for it is owner-scoped (list only rows ``is_owner`` would
    approve). Raises ``PermissionDenied`` when they hold no grant at all.
    """
    grants = [
        g for g in resolve_permissions(user) if g.resource == resource and g.action == action
    ]
    if not grants:
        raise PermissionDenied(
            f"You do not have permission to {action} {resource}.",
            resource=resource,
            action=action,
            level=0,
        )
    if any(not g.if_owner for g in grants):
        return None
    return user


# --- Django admin bridge (deviation 3.11) ------------------------------------

#: Django admin asks in terms of "app_label.codename"; we answer in terms of
#: (resource, action). Codenames look like "view_employee" / "add_jobcard".
_DJANGO_ACTION_MAP = {
    "view": "view",
    "add": "create",
    "change": "edit",
    "delete": "delete",
}

#: Which of our resources each admin app_label covers, for has_module_perms.
_APP_RESOURCES: dict[str, tuple[str, ...]] = {
    "hr": (constants.RES_EMPLOYEE, constants.RES_EMPLOYEE_DOCUMENT),
    "identity": (
        constants.RES_USER_ACCOUNT,
        constants.RES_ROLE_ASSIGNMENT,
        constants.RES_PASSWORD,
    ),
    "core": (constants.RES_AUDIT_LOG, constants.RES_DOCUMENT),
    "pipeline": (constants.RES_TRANSITION_RULE,),
    "sales": (
        constants.RES_CLIENT,
        constants.RES_JOB_CARD,
        constants.RES_JOB_LINE,
        constants.RES_QUOTATION,
        constants.RES_JOB_NOTE,
    ),
}


def has_permission_for_django_codename(
    user: UserAccount, perm: str, obj: Any = None
) -> bool:
    """Translate ``"hr.view_employee"`` into a question this module can answer.

    ``RBACModelAdmin`` calls ``has_permission`` directly and does not depend on
    this; it exists for the admin internals we do not own.
    """
    if "." not in perm:
        return False
    _, codename = perm.split(".", 1)
    if "_" not in codename:
        return False
    django_action, model_name = codename.split("_", 1)
    action = _DJANGO_ACTION_MAP.get(django_action)
    if action is None:
        return False
    # Model names in codenames are lower-cased and unspaced; our resources are
    # snake_case. `jobcard` -> `job_card` is not derivable, so match loosely.
    squashed = model_name.replace("_", "")
    for grant in resolve_permissions(user):
        if grant.action == action and grant.resource.replace("_", "") == squashed:
            if not grant.if_owner:
                return True
            if obj is not None and is_owner(user, obj):
                return True
    return False


def has_any_permission_in_app(user: UserAccount, app_label: str) -> bool:
    """Whether the admin should show this app on the index page."""
    resources = _APP_RESOURCES.get(app_label)
    if not resources:
        return False
    return any(g.resource in resources for g in resolve_permissions(user))


# --- Account lifecycle -------------------------------------------------------


def generate_password(length: int = 20) -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def create_user_account(
    actor: UserAccount,
    employee,
    username: str,
    password: str | None = None,
) -> tuple[UserAccount, str]:
    """Create a login for ``employee``. Returns ``(account, password)``.

    Authority is the ``user_account:create`` permission, never a role-name
    check (D3). The generated password is returned rather than stored or
    mailed, and ``must_change_password`` is set so it survives exactly one
    login.
    """
    require_permission(actor, constants.RES_USER_ACCOUNT, "create")

    username = (username or "").strip()
    if not 3 <= len(username) <= 64:
        raise RuleViolation("A username must be between 3 and 64 characters.")

    issued = password or generate_password()

    with audit_actor(actor):
        if UserAccount.objects.filter(username=username).exists():
            raise RuleViolation(f"The username {username!r} is already taken.")
        if UserAccount.objects.filter(employee=employee).exists():
            raise RuleViolation(
                f"{employee.employee_code} already has a login account."
            )
        try:
            account = UserAccount.objects.create_user(
                username=username,
                employee=employee,
                password=issued,
                must_change_password=True,
                created_by=actor,
            )
        except IntegrityError as exc:
            raise RuleViolation(f"Could not create the account: {exc}") from exc

    return account, issued


def change_own_password(user: UserAccount, old_password: str, new_password: str) -> None:
    """Rotate one's own password.

    Django's hashers and validators do the work; this project never invents its
    own. Note the permission is checked with ``obj=user`` because
    ``password:edit`` is granted with ``if_owner`` for every role — passing no
    object would correctly be refused.
    """
    require_permission(user, constants.RES_PASSWORD, "edit", obj=user)

    if not user.check_password(old_password):
        raise PermissionDenied("The current password is not correct.")

    if old_password == new_password:
        raise RuleViolation("The new password must differ from the current one.")

    try:
        validate_password(new_password, user=user)
    except ValidationError as exc:
        raise RuleViolation(" ".join(exc.messages)) from exc

    with audit_actor(user):
        user.set_password(new_password)
        user.must_change_password = False
        user.password_changed_at = timezone.now()
        user.failed_login_count = 0
        user.locked_until = None
        user.save(
            update_fields=[
                "password",
                "must_change_password",
                "password_changed_at",
                "failed_login_count",
                "locked_until",
            ]
        )


def set_password_for(actor: UserAccount, user: UserAccount, new_password: str) -> None:
    """An administrator resetting somebody else's password."""
    require_permission(actor, constants.RES_USER_ACCOUNT, "edit", obj=user)

    try:
        validate_password(new_password, user=user)
    except ValidationError as exc:
        raise RuleViolation(" ".join(exc.messages)) from exc

    with audit_actor(actor):
        user.set_password(new_password)
        user.must_change_password = True
        user.password_changed_at = timezone.now()
        user.failed_login_count = 0
        user.locked_until = None
        user.save(
            update_fields=[
                "password",
                "must_change_password",
                "password_changed_at",
                "failed_login_count",
                "locked_until",
            ]
        )


def deactivate_user_account(actor: UserAccount, user: UserAccount) -> None:
    require_permission(actor, constants.RES_USER_ACCOUNT, "edit", obj=user)
    with audit_actor(actor):
        user.is_active = False
        user.save(update_fields=["is_active"])


# --- Role assignment ---------------------------------------------------------


def assign_role(actor: UserAccount, user: UserAccount, role: Role) -> UserRole:
    require_permission(actor, constants.RES_ROLE_ASSIGNMENT, "create")

    if not role.is_active:
        raise RuleViolation(f"Role {role.code} is not active.")

    with audit_actor(actor):
        assignment, created = UserRole.objects.get_or_create(
            user=user, role=role, defaults={"assigned_by": actor}
        )
    if not created:
        raise RuleViolation(f"{user.username} already holds the role {role.code}.")

    invalidate_permission_cache(user)
    return assignment


def revoke_role(actor: UserAccount, user: UserAccount, role: Role) -> None:
    require_permission(actor, constants.RES_ROLE_ASSIGNMENT, "delete")

    with audit_actor(actor):
        deleted, _ = UserRole.objects.filter(user=user, role=role).delete()

    if not deleted:
        raise RuleViolation(f"{user.username} does not hold the role {role.code}.")

    invalidate_permission_cache(user)


def roles_for(user: UserAccount) -> list[Role]:
    """The user's active roles, for display."""
    return list(Role.objects.filter(user_roles__user=user, is_active=True).order_by("code"))
