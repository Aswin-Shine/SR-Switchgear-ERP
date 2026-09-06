"""Reads for the identity app.

Every query that is not a plain ``Model.objects.get(pk=...)`` lives here,
including the soft-delete filter. Managers are deliberately not overridden to
hide soft-deleted rows: an invisible default filter breaks the admin and hides
referential reality, so ``deleted_at IS NULL`` is written out, matching the
partial indexes.
"""

from __future__ import annotations

from django.db.models import QuerySet

from apps.identity.models import Role, UserAccount, UserRole


def active_user_accounts() -> QuerySet[UserAccount]:
    return UserAccount.objects.filter(deleted_at__isnull=True, is_active=True)


def user_accounts_for_admin() -> QuerySet[UserAccount]:
    """Including inactive, excluding soft-deleted."""
    return UserAccount.objects.filter(deleted_at__isnull=True).select_related("employee")


def find_by_username(username: str) -> UserAccount | None:
    return UserAccount.objects.filter(username=username, deleted_at__isnull=True).first()


def active_roles() -> QuerySet[Role]:
    return Role.objects.filter(is_active=True).order_by("code")


def role_assignments_for(user: UserAccount) -> QuerySet[UserRole]:
    return (
        UserRole.objects.filter(user=user)
        .select_related("role", "assigned_by")
        .order_by("role__code")
    )


def active_role_ids_for(user: UserAccount) -> list:
    """The role ids the pipeline engine matches transition rules against."""
    return list(
        UserRole.objects.filter(user=user, role__is_active=True).values_list(
            "role_id", flat=True
        )
    )
