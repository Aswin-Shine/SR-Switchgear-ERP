"""The error paths.

These messages are what a user actually sees when something goes wrong, so
they are worth asserting rather than leaving to chance. Each one turns a named
constraint into a sentence — which is only possible because defect #8 in the
schema review insisted every constraint be explicitly named.
"""

import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.core.exceptions import RuleViolation
from apps.core.services import document_url, soft_delete_document, upload_document
from apps.hr.models import EmployeeDocumentType, EmploymentStatus
from apps.hr.services import attach_employee_document, update_employee
from apps.identity import constants
from apps.identity.models import Role
from tests.factories import EmployeeFactory, UserAccountFactory, UserRoleFactory


def with_role(code: str):
    user = UserAccountFactory()
    UserRoleFactory(user=user, role=Role.objects.get(code=code))
    return user


@pytest.fixture
def hr_user(db):
    return with_role(constants.ROLE_HR)


def a_file(name="scan.pdf", content=b"%PDF-1.4 fake"):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


@pytest.mark.django_db
def test_unknown_field_on_update_is_refused(hr_user):
    with pytest.raises(RuleViolation, match="Unknown employee field"):
        update_employee(hr_user, EmployeeFactory(), salary=999999)


@pytest.mark.django_db
def test_marking_someone_exited_without_an_exit_date_is_refused(hr_user):
    with pytest.raises(RuleViolation, match="needs an exit date"):
        update_employee(
            hr_user, EmployeeFactory(), employment_status=EmploymentStatus.EXITED
        )


@pytest.mark.django_db
def test_an_employee_cannot_be_set_to_report_to_themselves(hr_user):
    employee = EmployeeFactory()

    with pytest.raises(RuleViolation, match="report to themselves"):
        update_employee(hr_user, employee, reports_to=employee)


@pytest.mark.django_db
def test_exit_date_before_joining_is_refused_on_update(hr_user):
    employee = EmployeeFactory(date_of_joining=datetime.date(2026, 6, 1))

    with pytest.raises(RuleViolation, match="exit date"):
        update_employee(hr_user, employee, date_of_exit=datetime.date(2026, 1, 1))


@pytest.mark.django_db
def test_the_same_employee_may_hold_several_documents_of_one_type(hr_user):
    """uk_employee_documents is (employee, doc_type, document), not
    (employee, doc_type) — two different ID proofs are legitimate, and the
    constraint deliberately permits them."""
    employee = EmployeeFactory()

    first = attach_employee_document(
        hr_user, employee, EmployeeDocumentType.ID_PROOF, a_file(content=b"scan one")
    )
    second = attach_employee_document(
        hr_user, employee, EmployeeDocumentType.ID_PROOF, a_file(content=b"scan two")
    )

    assert first.pk != second.pk
    assert first.document_id != second.document_id


@pytest.mark.django_db
def test_uploading_nothing_is_refused(hr_user):
    with pytest.raises(RuleViolation, match="No file"):
        upload_document(hr_user, None)


@pytest.mark.django_db
def test_a_filename_with_no_extension_still_gets_a_key(hr_user):
    document = upload_document(hr_user, a_file(name="README"))
    assert document.storage_key.startswith("documents/")


@pytest.mark.django_db
def test_a_hostile_extension_is_dropped_from_the_key(hr_user):
    document = upload_document(hr_user, a_file(name="x.pdf/../../evil"))
    assert ".." not in document.storage_key
    assert document.storage_key.startswith("documents/")


@pytest.mark.django_db
def test_document_url_is_derivable(hr_user):
    document = upload_document(hr_user, a_file())
    assert isinstance(document_url(document), str)


@pytest.mark.django_db
def test_soft_deleting_a_document_leaves_the_bytes_alone(hr_user):
    """Retention of the object itself is a storage-lifecycle question, and for
    identity documents a data-protection one (D9). Other tables reference this
    row with ON DELETE RESTRICT."""
    document = upload_document(hr_user, a_file())
    key = document.storage_key

    soft_delete_document(hr_user, document)

    document.refresh_from_db()
    assert document.deleted_at is not None
    assert document.storage_key == key

    from django.core.files.storage import default_storage

    assert default_storage.exists(key)


@pytest.mark.django_db
def test_two_uploads_of_identical_bytes_get_distinct_keys(hr_user):
    """Deduplication is not attempted. Two employees' identical scans are two
    documents with two access-control stories, and collapsing them would let a
    deletion for one erase the other's evidence."""
    first = upload_document(hr_user, a_file(content=b"identical"))
    second = upload_document(hr_user, a_file(content=b"identical"))

    assert first.sha256 == second.sha256
    assert first.storage_key != second.storage_key


@pytest.mark.django_db
def test_soft_deleted_documents_drop_out_of_an_employees_list(hr_user):
    from apps.hr.selectors import documents_for

    employee = EmployeeFactory()
    record = attach_employee_document(
        hr_user, employee, EmployeeDocumentType.ID_PROOF, a_file()
    )
    assert documents_for(hr_user, employee).count() == 1

    record.deleted_at = timezone.now()
    record.save(update_fields=["deleted_at"])

    assert documents_for(hr_user, employee).count() == 0
