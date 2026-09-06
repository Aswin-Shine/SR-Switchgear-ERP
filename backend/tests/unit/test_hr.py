"""HR: employee lifecycle, field tiers, and the sensitive-document gate."""

import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.exceptions import PermissionDenied, RuleViolation
from apps.core.models import Document
from apps.hr.models import EmployeeDocumentType, EmploymentStatus
from apps.hr.selectors import documents_for, employees_visible_to, search_employees
from apps.hr.services import (
    attach_employee_document,
    create_employee,
    may_read_employee_document,
    soft_delete_employee,
    update_employee,
)
from apps.identity import constants
from apps.identity.models import Role
from tests.factories import (
    DepartmentFactory,
    DesignationFactory,
    EmployeeFactory,
    UserAccountFactory,
    UserRoleFactory,
)


def with_role(code: str):
    user = UserAccountFactory()
    UserRoleFactory(user=user, role=Role.objects.get(code=code))
    return user


@pytest.fixture
def hr_user(db):
    return with_role(constants.ROLE_HR)


@pytest.fixture
def sales_user(db):
    return with_role(constants.ROLE_SALES)


def a_file(name="scan.pdf", content=b"%PDF-1.4 fake"):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


# --- creation -----------------------------------------------------------------


@pytest.mark.django_db
def test_hr_can_create_an_employee(hr_user):
    employee = create_employee(
        hr_user,
        full_name="Meera Iyer",
        department=DepartmentFactory(),
        designation=DesignationFactory(),
        date_of_joining=datetime.date(2026, 1, 5),
    )

    assert employee.pk is not None
    assert employee.employment_status == EmploymentStatus.ACTIVE
    # employee_code is never caller-supplied — the service always issues it.
    assert employee.employee_code.startswith("SRS-")


@pytest.mark.django_db
def test_employee_code_is_auto_assigned_sequentially(hr_user):
    department = DepartmentFactory()
    first = create_employee(
        hr_user, full_name="First", department=department,
        date_of_joining=datetime.date(2026, 1, 5),
    )
    second = create_employee(
        hr_user, full_name="Second", department=department,
        date_of_joining=datetime.date(2026, 1, 5),
    )

    assert first.employee_code != second.employee_code
    assert first.employee_code < second.employee_code


@pytest.mark.django_db
def test_a_salesperson_cannot_create_an_employee(sales_user):
    with pytest.raises(PermissionDenied):
        create_employee(
            sales_user,
            full_name="Should Not Exist",
            department=DepartmentFactory(),
            date_of_joining=datetime.date(2026, 1, 5),
        )


@pytest.mark.django_db
def test_unknown_fields_are_refused_rather_than_ignored(hr_user):
    """A mass-assignment guard: a payload key that is not writable should stop
    the request, not be silently dropped. employee_code is one such key now —
    it is issued by the service, never accepted from a caller."""
    with pytest.raises(RuleViolation, match="Unknown employee field"):
        create_employee(
            hr_user,
            full_name="Meera Iyer",
            department=DepartmentFactory(),
            date_of_joining=datetime.date(2026, 1, 5),
            employee_code="SRS-999",
        )


@pytest.mark.django_db
def test_duplicate_employee_code_is_rejected_by_the_database():
    """create_employee auto-generates the code now, so the app layer can
    never collide — uk_employees_code + citext still guard a direct write
    that bypasses the service (admin raw SQL, psql), exercised here at the
    model layer."""
    from django.db import IntegrityError, transaction

    EmployeeFactory(employee_code="SRS-090010")

    with pytest.raises(IntegrityError, match="uk_employees_code"):
        with transaction.atomic():
            EmployeeFactory(employee_code="srs-090010")


@pytest.mark.django_db
def test_an_invalid_email_is_rejected_by_the_regex_check(hr_user):
    """ck_employees_email is a regex CHECK on a citext column — the exact
    combination that ruled out a non-deterministic collation."""
    with pytest.raises(RuleViolation, match="valid address"):
        create_employee(
            hr_user,
            full_name="Bad Email",
            department=DepartmentFactory(),
            date_of_joining=datetime.date(2026, 1, 5),
            personal_email="not-an-email",
        )


@pytest.mark.django_db
def test_a_blank_personal_email_cleans_to_none_not_empty_string():
    """TextField.formfield(), unlike CharField's, never sets
    empty_value=None for a nullable field — an empty admin Textarea always
    cleaned to "", which is neither NULL nor a valid address and tripped
    ck_employees_email. django_db is needed here: full_clean() validates
    Meta.constraints against the database, not just in Python."""
    from django.forms import modelform_factory

    from apps.hr.models import Employee

    Form = modelform_factory(Employee, fields=["personal_email"])
    form = Form(data={"personal_email": ""})

    assert form.is_valid(), form.errors
    assert form.cleaned_data["personal_email"] is None


@pytest.mark.django_db
def test_exit_date_before_joining_is_refused(hr_user):
    with pytest.raises(RuleViolation, match="exit date"):
        create_employee(
            hr_user,
            full_name="Time Traveller",
            department=DepartmentFactory(),
            date_of_joining=datetime.date(2026, 6, 1),
            date_of_exit=datetime.date(2026, 1, 1),
        )


# --- the field tiers ------------------------------------------------------------


@pytest.mark.django_db
def test_hr_can_change_a_protected_field(hr_user):
    employee = EmployeeFactory(full_name="Before")

    update_employee(hr_user, employee, full_name="After")

    employee.refresh_from_db()
    assert employee.full_name == "After"


@pytest.mark.django_db
def test_an_employee_cannot_edit_their_own_name_or_photo(sales_user):
    """The rule the plan names explicitly. Sales holds employee:view with
    if_owner at level 0 and no employee:edit grant at all, so this is refused
    by the grid rather than by a special case."""
    own = sales_user.employee

    with pytest.raises(PermissionDenied):
        update_employee(sales_user, own, full_name="Self-Promoted")

    with pytest.raises(PermissionDenied):
        update_employee(sales_user, own, photo_document=None)

    own.refresh_from_db()
    assert own.full_name != "Self-Promoted"


@pytest.mark.django_db
def test_an_employee_cannot_edit_somebody_elses_record(sales_user):
    with pytest.raises(PermissionDenied):
        update_employee(sales_user, EmployeeFactory(), personal_phone="+91-90000-11111")


@pytest.mark.django_db
def test_protected_fields_need_level_1_even_for_a_level_0_editor(db):
    """A role granted employee:edit at level 0 may fix a phone number but not
    a job title. Nothing in the grid grants that today; the tier exists so the
    distinction is expressible without a code change."""
    from tests.factories import PermissionFactory, RoleFactory, RolePermissionFactory

    user = UserAccountFactory()
    role = RoleFactory(code="CLERK")
    permission = PermissionFactory(resource=constants.RES_EMPLOYEE, action="edit")
    RolePermissionFactory(role=role, permission=permission, perm_level=0)
    UserRoleFactory(user=user, role=role)

    employee = EmployeeFactory()

    update_employee(user, employee, personal_phone="+91-90000-22222")
    employee.refresh_from_db()
    assert employee.personal_phone == "+91-90000-22222"

    with pytest.raises(PermissionDenied):
        update_employee(user, employee, employment_status=EmploymentStatus.SUSPENDED)


@pytest.mark.django_db
def test_an_empty_update_is_a_no_op(hr_user):
    employee = EmployeeFactory()
    assert update_employee(hr_user, employee) is employee


# --- soft delete -------------------------------------------------------------------


@pytest.mark.django_db
def test_soft_delete_marks_the_row_and_deactivates_the_account(hr_user):
    from tests.factories import PermissionFactory, RoleFactory, RolePermissionFactory

    # HR does not hold employee:delete in the grid, so grant it explicitly.
    role = RoleFactory(code="HRDELETER")
    permission = PermissionFactory(resource=constants.RES_EMPLOYEE, action="delete")
    RolePermissionFactory(role=role, permission=permission, perm_level=1)
    UserRoleFactory(user=hr_user, role=role)

    account = UserAccountFactory()
    employee = account.employee

    soft_delete_employee(hr_user, employee)

    employee.refresh_from_db()
    account.refresh_from_db()
    assert employee.deleted_at is not None
    assert account.is_active is False


@pytest.mark.django_db
def test_soft_deleted_employees_drop_out_of_the_visible_list(hr_user):
    employee = EmployeeFactory()
    assert employee in employees_visible_to(hr_user)

    from django.utils import timezone

    employee.deleted_at = timezone.now()
    employee.save(update_fields=["deleted_at"])

    assert employee not in employees_visible_to(hr_user)


# --- visibility -----------------------------------------------------------------------


@pytest.mark.django_db
def test_hr_sees_everyone_and_sales_sees_only_themselves(hr_user, sales_user):
    stranger = EmployeeFactory()

    hr_visible = set(employees_visible_to(hr_user))
    assert stranger in hr_visible
    assert sales_user.employee in hr_visible

    sales_visible = set(employees_visible_to(sales_user))
    assert sales_visible == {sales_user.employee}


@pytest.mark.django_db
def test_a_user_with_no_employee_grants_sees_nobody(db):
    assert list(employees_visible_to(UserAccountFactory())) == []


@pytest.mark.django_db
def test_search_is_scoped_to_what_the_actor_may_see(hr_user, sales_user):
    EmployeeFactory(full_name="Findable Person")

    assert search_employees(hr_user, "Findable").exists()
    assert not search_employees(sales_user, "Findable").exists()


# --- documents ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_hr_can_attach_a_sensitive_document(hr_user):
    import hashlib

    employee = EmployeeFactory()
    payload = b"%PDF-1.4 fake"

    record = attach_employee_document(
        hr_user, employee, EmployeeDocumentType.ID_PROOF, a_file(content=payload)
    )

    assert record.is_sensitive is True
    # The digest is of the content, not of the name or a placeholder. If this
    # drifts, ck_documents_sha256 would still pass and the integrity check
    # would be quietly worthless.
    assert record.document.sha256 == hashlib.sha256(payload).hexdigest()


@pytest.mark.django_db
def test_the_document_row_records_metadata_not_bytes(hr_user):
    employee = EmployeeFactory()
    payload = b"%PDF-1.4 some bytes here"

    record = attach_employee_document(
        hr_user, employee, EmployeeDocumentType.ID_PROOF, a_file(content=payload)
    )

    document = record.document
    assert document.byte_size == len(payload)
    assert document.mime_type == "application/pdf"
    assert document.storage_key.startswith("documents/")
    # The bytes are not in the row.
    assert payload not in document.storage_key.encode()


@pytest.mark.django_db
def test_the_uploaded_filename_cannot_steer_the_storage_key(hr_user):
    """The filename is attacker-controlled."""
    employee = EmployeeFactory()

    record = attach_employee_document(
        hr_user,
        employee,
        EmployeeDocumentType.ID_PROOF,
        a_file(name="../../../etc/passwd"),
    )

    assert record.document.storage_key.startswith("documents/")
    assert ".." not in record.document.storage_key


@pytest.mark.django_db
def test_an_empty_file_is_refused(hr_user):
    with pytest.raises(RuleViolation, match="empty file"):
        attach_employee_document(
            hr_user,
            EmployeeFactory(),
            EmployeeDocumentType.ID_PROOF,
            SimpleUploadedFile("empty.pdf", b"", content_type="application/pdf"),
        )


@pytest.mark.django_db
def test_an_oversized_file_is_refused(hr_user, settings):
    settings.MAX_UPLOAD_BYTES = 16

    with pytest.raises(RuleViolation, match="limit is"):
        attach_employee_document(
            hr_user,
            EmployeeFactory(),
            EmployeeDocumentType.ID_PROOF,
            a_file(content=b"x" * 64),
        )

    assert Document.objects.count() == 0


@pytest.mark.django_db
def test_an_invalid_doc_type_is_explained(hr_user):
    with pytest.raises(RuleViolation, match="not a valid document type"):
        attach_employee_document(hr_user, EmployeeFactory(), "passport", a_file())


# --- the sensitive gate -------------------------------------------------------------------


@pytest.mark.django_db
def test_sensitive_documents_are_invisible_below_level_2(hr_user, sales_user):
    """Withheld, not merely un-openable: a level-0 holder should not learn that
    an Aadhaar scan exists."""
    employee = sales_user.employee
    attach_employee_document(
        hr_user, employee, EmployeeDocumentType.ID_PROOF, a_file(), is_sensitive=True
    )

    assert documents_for(hr_user, employee).count() == 1
    assert documents_for(sales_user, employee).count() == 0


@pytest.mark.django_db
def test_owner_holds_level_2_and_admin_does_not(hr_user):
    """Appendix B gives employee_document:view at level 2 to OWNER and HR only
    — pointedly not to ADMIN."""
    employee = EmployeeFactory()
    attach_employee_document(
        hr_user, employee, EmployeeDocumentType.ID_PROOF, a_file(), is_sensitive=True
    )

    owner = with_role(constants.ROLE_OWNER)
    admin = with_role(constants.ROLE_ADMIN)

    assert documents_for(owner, employee).count() == 1
    assert documents_for(admin, employee).count() == 0


@pytest.mark.django_db
def test_may_read_employee_document_agrees_with_the_selector(hr_user, sales_user):
    employee = sales_user.employee
    record = attach_employee_document(
        hr_user, employee, EmployeeDocumentType.ID_PROOF, a_file(), is_sensitive=True
    )

    assert may_read_employee_document(hr_user, record) is True
    assert may_read_employee_document(sales_user, record) is False


@pytest.mark.django_db
def test_a_salesperson_cannot_attach_a_sensitive_document_even_to_themselves(sales_user):
    with pytest.raises(PermissionDenied):
        attach_employee_document(
            sales_user,
            sales_user.employee,
            EmployeeDocumentType.ID_PROOF,
            a_file(),
            is_sensitive=True,
        )
