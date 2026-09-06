"""Reads for the HR app.

The soft-delete filter is written out here rather than hidden in a manager, and
it matches ``idx_employees_active`` — the partial index is
``WHERE deleted_at IS NULL AND employment_status = 'active'``, so
``active_employees()`` is the query that index exists for.
"""

from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.hr.models import Employee, EmployeeDocument, EmploymentStatus
from apps.identity import constants
from apps.identity.services import has_permission


def live_employees() -> QuerySet[Employee]:
    """Not soft-deleted. Includes exited staff, who remain part of the record."""
    return Employee.objects.filter(deleted_at__isnull=True)


def active_employees() -> QuerySet[Employee]:
    """Currently employed. Matches idx_employees_active exactly."""
    return Employee.objects.filter(
        deleted_at__isnull=True, employment_status=EmploymentStatus.ACTIVE
    )


def employees_visible_to(actor) -> QuerySet[Employee]:
    """What this user may list.

    A holder of the unrestricted grant sees everyone; an operational role sees
    exactly their own record. Filtering the queryset rather than the page means
    an unauthorised row is never serialised, not merely never rendered.
    """
    if has_permission(
        actor, constants.RES_EMPLOYEE, "view", level=constants.LEVEL_PROTECTED
    ):
        return live_employees().select_related("department", "designation")

    if actor is not None and getattr(actor, "employee_id", None):
        own = live_employees().filter(pk=actor.employee_id)
        if has_permission(actor, constants.RES_EMPLOYEE, "view", obj=actor.employee):
            return own.select_related("department", "designation")

    return Employee.objects.none()


def search_employees(actor, term: str = "") -> QuerySet[Employee]:
    queryset = employees_visible_to(actor)
    if term:
        queryset = queryset.filter(
            Q(full_name__icontains=term)
            | Q(employee_code__icontains=term)
            | Q(personal_email__icontains=term)
        )
    return queryset.order_by("employee_code")


def documents_for(actor, employee: Employee) -> QuerySet[EmployeeDocument]:
    """Sensitive rows are withheld unless the actor holds level 2.

    Filtering rather than redacting matters: a level-0 holder should not learn
    that an Aadhaar scan exists, only to be told they cannot open it.
    """
    queryset = EmployeeDocument.objects.filter(
        employee=employee, deleted_at__isnull=True
    ).select_related("document")

    if has_permission(
        actor,
        constants.RES_EMPLOYEE_DOCUMENT,
        "view",
        obj=employee,
        level=constants.LEVEL_SENSITIVE,
    ):
        return queryset

    if has_permission(actor, constants.RES_EMPLOYEE_DOCUMENT, "view", obj=employee):
        return queryset.filter(is_sensitive=False)

    return EmployeeDocument.objects.none()
