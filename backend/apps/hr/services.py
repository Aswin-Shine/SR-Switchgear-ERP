"""Employee lifecycle.

The access rule this module exists to enforce, from Appendix B: HR edits
everything, everyone else sees their own record and can change nothing on it
but their password. That is not implemented as "if user is HR" — it falls out
of the grid, because the operational roles hold ``employee:view`` with
``if_owner`` at level 0 and hold no ``employee:edit`` grant at all.

The field tiers are the second half of it. ``full_name``, ``department``,
``designation``, the joining and exit dates, the employment status and the
photo are ``perm_level`` 1; everything else on the record is level 0. So a
hypothetical future role could be allowed to correct a phone number without
being allowed to change somebody's job title.

``employee_code`` is not writable at all, by anyone, ever: it is issued by
``apps.core.numbering.next_employee_code`` (``SRS-001``, ``SRS-002``, ...) at
creation and never appears in a payload again — not through this service,
not through the admin (``EmployeeAdmin.save_model``/``readonly_fields``),
not through ``bootstrap_admin``. One source, one sequence, no user-chosen
codes.
"""

from __future__ import annotations

from typing import Any

from django.core.files.uploadedfile import UploadedFile
from django.db import IntegrityError
from django.utils import timezone

from apps.core.db import audit_actor
from apps.core.exceptions import RuleViolation
from apps.core.numbering import next_employee_code
from apps.core.services import upload_document
from apps.hr.models import Employee, EmployeeDocument, EmploymentStatus
from apps.identity import constants
from apps.identity.services import has_permission, require_permission

#: Fields callers may set. Anything else in a payload is ignored rather than
#: blindly applied — a mass-assignment guard. ``employee_code`` is
#: deliberately absent — it is never caller-supplied, see the module
#: docstring.
WRITABLE_FIELDS = frozenset(
    {
        "full_name",
        "department",
        "designation",
        "reports_to",
        "photo_document",
        "date_of_joining",
        "date_of_exit",
        "employment_status",
        "personal_phone",
        "personal_email",
    }
)


def _required_level(fields: set[str]) -> int:
    """Level 1 if any protected field is being written, else level 0."""
    return (
        constants.LEVEL_PROTECTED
        if fields & constants.PROTECTED_EMPLOYEE_FIELDS
        else constants.LEVEL_ORDINARY
    )


def create_employee(actor, **fields: Any) -> Employee:
    require_permission(
        actor, constants.RES_EMPLOYEE, "create", level=constants.LEVEL_PROTECTED
    )

    unknown = set(fields) - WRITABLE_FIELDS
    if unknown:
        raise RuleViolation(f"Unknown employee field(s): {', '.join(sorted(unknown))}.")

    _validate(fields)

    with audit_actor(actor):
        try:
            return Employee.objects.create(employee_code=next_employee_code(), **fields)
        except IntegrityError as exc:
            raise RuleViolation(_explain(exc)) from exc


def update_employee(actor, employee: Employee, **fields: Any) -> Employee:
    """Apply a partial update, charging the right permission level for it."""
    unknown = set(fields) - WRITABLE_FIELDS
    if unknown:
        raise RuleViolation(f"Unknown employee field(s): {', '.join(sorted(unknown))}.")
    if not fields:
        return employee

    require_permission(
        actor,
        constants.RES_EMPLOYEE,
        "edit",
        obj=employee,
        level=_required_level(set(fields)),
    )

    _validate(fields, existing=employee)

    for name, value in fields.items():
        setattr(employee, name, value)

    with audit_actor(actor):
        try:
            employee.save(update_fields=sorted(fields))
        except IntegrityError as exc:
            raise RuleViolation(_explain(exc)) from exc

    return employee


def soft_delete_employee(actor, employee: Employee) -> None:
    """Mark an employee deleted. Their account, if any, is deactivated with them.

    Deliberately not a hard delete: ``fk_user_accounts_employee`` and
    ``fk_job_cards_owner`` are ON DELETE RESTRICT, and the quotation history
    that proves what was promised to a client names the person who prepared it.
    """
    require_permission(
        actor,
        constants.RES_EMPLOYEE,
        "delete",
        obj=employee,
        level=constants.LEVEL_PROTECTED,
    )

    with audit_actor(actor):
        employee.deleted_at = timezone.now()
        employee.save(update_fields=["deleted_at"])

        account = employee.account
        if account is not None and account.is_active:
            account.is_active = False
            account.save(update_fields=["is_active"])


def _validate(fields: dict[str, Any], existing: Employee | None = None) -> None:
    """The handful of rules worth catching before the database does.

    Everything here is *also* enforced by a CHECK constraint. The duplication
    is deliberate and bounded: it turns an opaque IntegrityError into a
    sentence a user can act on. No rule lives here that does not also live in
    the schema.
    """
    joining = fields.get(
        "date_of_joining", existing.date_of_joining if existing else None
    )
    exit_date = fields.get("date_of_exit", existing.date_of_exit if existing else None)
    status = fields.get(
        "employment_status", existing.employment_status if existing else None
    )

    if exit_date and joining and exit_date < joining:
        raise RuleViolation(
            "The exit date cannot be before the joining date.",
            date_of_joining=str(joining),
            date_of_exit=str(exit_date),
        )

    if status == EmploymentStatus.EXITED and not exit_date:
        raise RuleViolation("An exited employee needs an exit date.")

    reports_to = fields.get("reports_to")
    if reports_to is not None and existing is not None and reports_to.pk == existing.pk:
        raise RuleViolation("An employee cannot report to themselves.")


def _explain(exc: IntegrityError) -> str:
    """Turn a named constraint into something a user can act on.

    Reading the constraint name is exactly what defect #8 in the schema review
    made possible — with auto-generated names this would be unreadable.
    """
    text = str(exc)
    if "uk_employees_code" in text:
        return "That employee code is already in use."
    if "ck_employees_email" in text:
        return "That email address is not a valid address."
    if "ck_employees_exit_date" in text:
        return "The exit date cannot be before the joining date."
    if "ck_employees_not_self" in text:
        return "An employee cannot report to themselves."
    if "ck_employees_status" in text:
        return "That employment status is not one of the permitted values."
    return "That change conflicts with an existing record."


# --- employee documents -------------------------------------------------------


def attach_employee_document(
    actor,
    employee: Employee,
    doc_type: str,
    upload: UploadedFile,
    *,
    is_sensitive: bool = True,
) -> EmployeeDocument:
    """Upload a file and file it against an employee.

    ``is_sensitive`` defaults to True. This table is designed to hold Aadhaar
    and PAN scans, so the default has to be the careful one — a document
    wrongly marked non-sensitive is readable by anyone with level 0, and
    nothing later would flag it.
    """
    require_permission(
        actor,
        constants.RES_EMPLOYEE_DOCUMENT,
        "view",
        obj=employee,
        level=constants.LEVEL_SENSITIVE if is_sensitive else constants.LEVEL_ORDINARY,
    )

    document = upload_document(actor, upload)

    with audit_actor(actor):
        try:
            return EmployeeDocument.objects.create(
                employee=employee,
                document=document,
                doc_type=doc_type,
                is_sensitive=is_sensitive,
            )
        except IntegrityError as exc:
            if "ck_employee_documents_type" in str(exc):
                raise RuleViolation(f"{doc_type!r} is not a valid document type.") from exc
            # uk_employee_documents is (employee, doc_type, document). It
            # cannot collide here — every call uploads a fresh document with a
            # new UUID storage key — so there is no branch for it. The
            # constraint still guards direct writes from the admin or psql.
            raise RuleViolation("That document could not be filed.") from exc


def may_read_employee_document(actor, record: EmployeeDocument) -> bool:
    """Sensitive rows need level 2; ordinary rows need level 0."""
    return has_permission(
        actor,
        constants.RES_EMPLOYEE_DOCUMENT,
        "view",
        obj=record.employee,
        level=constants.LEVEL_SENSITIVE if record.is_sensitive else constants.LEVEL_ORDINARY,
    )
