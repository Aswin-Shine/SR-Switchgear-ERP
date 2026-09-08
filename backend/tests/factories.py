"""factory_boy fixtures.

Built once, in Phase 1, rather than per app. The NOT NULL columns force a deep
chain — department -> employee -> user account -> (client, product category,
stage) -> job card -> job line — and every later phase needs most of it.
"""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from apps.core.models import Department, Designation, Document, NumberSeries
from apps.hr.models import Employee, EmployeeDocument, EmployeeDocumentType
from apps.identity.models import (
    LoginSession,
    Permission,
    Role,
    RolePermission,
    UserAccount,
    UserRole,
)
from apps.pipeline.models import Stage, TransitionRule
from apps.sales.models import (
    Client,
    ClientContact,
    JobAttachment,
    JobCard,
    JobLine,
    JobNote,
    ProductCategory,
    Quotation,
    QuotationLine,
)

DEFAULT_PASSWORD = "correct-horse-battery-staple"


class DepartmentFactory(DjangoModelFactory):
    class Meta:
        model = Department
        django_get_or_create = ("code",)

    code = factory.Sequence(lambda n: f"DEPT{n:03d}")
    name = factory.LazyAttribute(lambda o: f"Department {o.code}")


class DesignationFactory(DjangoModelFactory):
    class Meta:
        model = Designation
        django_get_or_create = ("code",)

    code = factory.Sequence(lambda n: f"DESIG{n:03d}")
    name = factory.LazyAttribute(lambda o: f"Designation {o.code}")


class EmployeeFactory(DjangoModelFactory):
    class Meta:
        model = Employee

    employee_code = factory.Sequence(lambda n: f"HR-EMP-{n:05d}")
    full_name = factory.Sequence(lambda n: f"Employee {n}")
    department = factory.SubFactory(DepartmentFactory)
    designation = factory.SubFactory(DesignationFactory)
    date_of_joining = factory.Faker("date_between", start_date="-3y", end_date="today")
    personal_email = factory.Sequence(lambda n: f"employee{n}@srswitchgear.example")


class UserAccountFactory(DjangoModelFactory):
    class Meta:
        model = UserAccount
        skip_postgeneration_save = True

    username = factory.Sequence(lambda n: f"user{n:04d}")
    employee = factory.SubFactory(EmployeeFactory)
    must_change_password = False

    @factory.post_generation
    def password(obj, create, extracted, **kwargs):
        if not create:
            return
        obj.set_password(extracted or DEFAULT_PASSWORD)
        obj.save(update_fields=["password"])


class RoleFactory(DjangoModelFactory):
    class Meta:
        model = Role
        django_get_or_create = ("code",)

    code = factory.Sequence(lambda n: f"ROLE{n:03d}")
    name = factory.LazyAttribute(lambda o: f"Role {o.code}")


class PermissionFactory(DjangoModelFactory):
    class Meta:
        model = Permission
        django_get_or_create = ("resource", "action")

    resource = factory.Sequence(lambda n: f"resource_{n}")
    action = "view"


class RolePermissionFactory(DjangoModelFactory):
    class Meta:
        model = RolePermission

    role = factory.SubFactory(RoleFactory)
    permission = factory.SubFactory(PermissionFactory)
    perm_level = 0
    if_owner = False


class UserRoleFactory(DjangoModelFactory):
    class Meta:
        model = UserRole

    user = factory.SubFactory(UserAccountFactory)
    role = factory.SubFactory(RoleFactory)


class DocumentFactory(DjangoModelFactory):
    class Meta:
        model = Document

    storage_key = factory.Sequence(lambda n: f"documents/{n:08d}.pdf")
    original_filename = factory.Sequence(lambda n: f"file-{n}.pdf")
    mime_type = "application/pdf"
    byte_size = 1024
    sha256 = factory.Sequence(lambda n: f"{n:064x}")
    uploaded_by = factory.SubFactory(UserAccountFactory)


class EmployeeDocumentFactory(DjangoModelFactory):
    class Meta:
        model = EmployeeDocument

    employee = factory.SubFactory(EmployeeFactory)
    document = factory.SubFactory(DocumentFactory)
    doc_type = EmployeeDocumentType.ID_PROOF
    is_sensitive = True


class LoginSessionFactory(DjangoModelFactory):
    class Meta:
        model = LoginSession

    user = factory.SubFactory(UserAccountFactory)
    refresh_token_hash = factory.Sequence(lambda n: f"{n:064x}")
    expires_at = factory.Faker("future_datetime", end_date="+30d", tzinfo=None)


class StageFactory(DjangoModelFactory):
    class Meta:
        model = Stage
        django_get_or_create = ("code",)

    code = factory.Sequence(lambda n: f"STAGE{n:03d}")
    name = factory.LazyAttribute(lambda o: f"Stage {o.code}")
    module_code = "JOB"
    sequence_no = factory.Sequence(lambda n: (n + 1) * 10)


class TransitionRuleFactory(DjangoModelFactory):
    class Meta:
        model = TransitionRule

    from_stage = factory.SubFactory(StageFactory)
    to_stage = factory.SubFactory(StageFactory)
    action_code = "advance"
    allowed_role = factory.SubFactory(RoleFactory)


class ClientFactory(DjangoModelFactory):
    class Meta:
        model = Client

    client_code = factory.Sequence(lambda n: f"CL{n:05d}")
    legal_name = factory.Sequence(lambda n: f"Client {n} Pvt Ltd")


class ClientContactFactory(DjangoModelFactory):
    class Meta:
        model = ClientContact

    client = factory.SubFactory(ClientFactory)
    contact_name = factory.Sequence(lambda n: f"Contact {n}")
    phone = factory.Sequence(lambda n: f"+9199{n:08d}")


class ProductCategoryFactory(DjangoModelFactory):
    class Meta:
        model = ProductCategory
        django_get_or_create = ("code",)

    code = factory.Sequence(lambda n: f"CAT{n:03d}")
    name = factory.LazyAttribute(lambda o: f"Category {o.code}")
    is_manufactured = True


class JobCardFactory(DjangoModelFactory):
    class Meta:
        model = JobCard

    job_no = factory.Sequence(lambda n: f"JOB-2026-JAN-{n:05d}")
    client = factory.SubFactory(ClientFactory)
    owner_user = factory.SubFactory(UserAccountFactory)
    # The card carries no free-text title: the schema describes the work on the
    # job *lines*, and the card is only the commercial container.
    requirements = factory.LazyFunction(dict)


class JobLineFactory(DjangoModelFactory):
    class Meta:
        model = JobLine

    job_card = factory.SubFactory(JobCardFactory)
    line_no = factory.Sequence(lambda n: (n % 30) + 1)
    product_category = factory.SubFactory(ProductCategoryFactory)
    description = factory.Sequence(lambda n: f"Panel {n}")
    quantity = 1
    current_stage = factory.SubFactory(StageFactory)


class QuotationFactory(DjangoModelFactory):
    class Meta:
        model = Quotation

    quotation_no = factory.Sequence(lambda n: f"QT-2026-JAN-{n:05d}")
    job_card = factory.SubFactory(JobCardFactory)
    revision_no = 0
    prepared_by = factory.SubFactory(UserAccountFactory)


class QuotationLineFactory(DjangoModelFactory):
    class Meta:
        model = QuotationLine

    quotation = factory.SubFactory(QuotationFactory)
    job_line = factory.SubFactory(JobLineFactory)
    line_amount = 100000


class JobNoteFactory(DjangoModelFactory):
    class Meta:
        model = JobNote

    job_card = factory.SubFactory(JobCardFactory)
    author_user = factory.SubFactory(UserAccountFactory)
    body = factory.Sequence(lambda n: f"Note body {n}")


class JobAttachmentFactory(DjangoModelFactory):
    class Meta:
        model = JobAttachment

    job_card = factory.SubFactory(JobCardFactory)
    document = factory.SubFactory(DocumentFactory)
    attached_by = factory.SubFactory(UserAccountFactory)


class NumberSeriesFactory(DjangoModelFactory):
    class Meta:
        model = NumberSeries
        django_get_or_create = ("prefix",)

    prefix = "JOB-2026-"
    current = 0
