"""hr — the employee master.

Tables: hr_employees, hr_employee_documents.

Three identities are deliberately separate, and conflating them is the mistake
this design exists to prevent:

* ``id``            — surrogate key, what every foreign key points at;
* ``employee_code`` — the human/paper-facing code (HR-EMP-00001);
* ``user_account``  — an optional login, in auth_user_accounts.
"""

from __future__ import annotations

from django.db import models

from apps.core.fields import CITextField, uuid_pk_kwargs
from apps.core.models import SoftDelete, TimeStamped, fk


class EmploymentStatus(models.TextChoices):
    """Pinned by ``ck_employees_status``. One of the four CHECK-constrained
    domains declared once as TextChoices and referenced symbolically."""

    ACTIVE = "active", "Active"
    ON_NOTICE = "on_notice", "On notice"
    EXITED = "exited", "Exited"
    SUSPENDED = "suspended", "Suspended"


class EmployeeDocumentType(models.TextChoices):
    """Pinned by ``ck_employee_documents_type``."""

    ID_PROOF = "id_proof", "ID proof"
    ADDRESS_PROOF = "address_proof", "Address proof"
    QUALIFICATION = "qualification", "Qualification"
    APPOINTMENT_LETTER = "appointment_letter", "Appointment letter"
    OTHER = "other", "Other"


class Employee(TimeStamped, SoftDelete):
    id = models.UUIDField(**uuid_pk_kwargs())
    employee_code = CITextField()
    full_name = models.TextField()
    department = fk("core.Department", models.PROTECT, related_name="employees")
    # Nullable in the schema: a new joiner may not have a title on day one.
    designation = fk(
        "core.Designation", models.PROTECT, null=True, blank=True, related_name="employees"
    )
    reports_to = fk(
        "self", models.SET_NULL, null=True, blank=True, related_name="direct_reports"
    )
    photo_document = fk(
        "core.Document", models.SET_NULL, null=True, blank=True, related_name="employee_photos"
    )
    date_of_joining = models.DateField()
    date_of_exit = models.DateField(null=True, blank=True)
    employment_status = models.TextField(
        choices=EmploymentStatus.choices,
        db_default=EmploymentStatus.ACTIVE,
        default=EmploymentStatus.ACTIVE,
    )
    personal_phone = models.TextField(null=True, blank=True)
    personal_email = CITextField(null=True, blank=True)

    class Meta:
        db_table = "hr_employees"
        default_permissions = ()
        verbose_name = "employee"
        constraints = [
            models.UniqueConstraint(fields=["employee_code"], name="uk_employees_code"),
            models.CheckConstraint(
                condition=models.Q(employment_status__in=EmploymentStatus.values),
                name="ck_employees_status",
            ),
            models.CheckConstraint(
                condition=models.Q(date_of_exit__isnull=True)
                | models.Q(date_of_exit__gte=models.F("date_of_joining")),
                name="ck_employees_exit_date",
            ),
            models.CheckConstraint(
                condition=~models.Q(reports_to=models.F("id")), name="ck_employees_not_self"
            ),
            # A regex CHECK on a citext column — the exact combination that
            # rules out Django's suggested non-deterministic collation
            # (deviation 3.1).
            models.CheckConstraint(
                condition=models.Q(personal_email__isnull=True)
                | models.Q(
                    personal_email__regex=r"^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$"
                ),
                name="ck_employees_email",
            ),
        ]
        indexes = [
            models.Index(fields=["department"], name="idx_employees_department"),
            models.Index(fields=["designation"], name="idx_employees_designation"),
            models.Index(fields=["reports_to"], name="idx_employees_reports_to"),
            models.Index(
                fields=["department"],
                name="idx_employees_active",
                condition=models.Q(deleted_at__isnull=True)
                & models.Q(employment_status=EmploymentStatus.ACTIVE),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.employee_code} — {self.full_name}"

    @property
    def account(self):
        """The employee's login, or None.

        The relationship is one-to-one — ``uk_user_accounts_employee`` enforces
        it — but it is modelled as a ForeignKey plus a UNIQUE constraint,
        exactly as the schema declares it, rather than as a OneToOneField that
        would emit a second unique index. The consequence is that the reverse
        accessor is a manager, not an instance, and calling ``.is_active`` on
        it fails in a confusing way. This property is the intended entry point.
        """
        return self.user_account.first()


class EmployeeDocument(SoftDelete):
    """Personal ID documents.

    ``is_sensitive`` defaults to TRUE — the safe default for a table designed
    to hold Aadhaar and PAN scans. It gates reads at ``perm_level`` 2
    (Appendix B). Whether such scans should be stored at all is an open
    question for the business (D9 / BACKEND_PLAN.md section 12), not something
    this model settles.
    """

    id = models.UUIDField(**uuid_pk_kwargs())
    employee = fk("hr.Employee", models.CASCADE, related_name="documents")
    document = fk("core.Document", models.PROTECT, related_name="employee_documents")
    doc_type = models.TextField(choices=EmployeeDocumentType.choices)
    is_sensitive = models.BooleanField(db_default=True, default=True)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        db_table = "hr_employee_documents"
        default_permissions = ()
        verbose_name = "employee document"
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "doc_type", "document"], name="uk_employee_documents"
            ),
            models.CheckConstraint(
                condition=models.Q(doc_type__in=EmployeeDocumentType.values),
                name="ck_employee_documents_type",
            ),
        ]
        # idx_employee_documents_employee and idx_employee_documents_document
        # are 31 characters, and Django rejects any name in Meta.indexes over
        # 30 (system check models.E034) even though PostgreSQL allows 63. The
        # schema's names win — defect #8 in the review was specifically about
        # constraint names being readable — so these two are created verbatim
        # in core/migrations/0003_database_objects.py instead of here. This is
        # a deviation the plan did not anticipate; it is recorded in
        # IMPLEMENTATION.md.
        indexes = []

    def __str__(self) -> str:
        return f"{self.doc_type} for {self.employee_id}"
