"""Populate a freshly migrated + bootstrapped database with sample data for
local development: one more department/employee/account, two product
categories, one client, and one job card with the "3 ATS + 2 AMF" job lines
CLAUDE.md itself uses as the canonical example of "one card, two lines."

Every write here goes through the same services.py functions the API uses
(create_employee, create_client, create_job_card, add_job_line, ...) under
an Owner actor — not raw ORM inserts — so it's exercised exactly like a real
request and can never drift from what the app actually enforces.

Requires bootstrap_admin to have run first (there has to be an Owner account
to act as). Idempotent: running it again is a no-op once the demo client
exists.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError

from apps.core.models import Department, Designation
from apps.hr import services as hr_services
from apps.identity import services as identity_services
from apps.identity.constants import ROLE_OWNER, ROLE_SALES
from apps.identity.models import Role, UserAccount, UserRole
from apps.sales import services as sales_services
from apps.sales.models import Client, DispatchPolicy, EnquirySource, ProductCategory

DEMO_CLIENT_LEGAL_NAME = "Acme Switchgear Buyers Pvt Ltd"


class Command(BaseCommand):
    help = (
        "Seed sample HR + sales data for local development (one client, one "
        "job card, two job lines). Idempotent. Requires bootstrap_admin to "
        "have run first."
    )

    def handle(self, *args, **options):
        owner = self._find_owner()

        if Client.objects.filter(legal_name=DEMO_CLIENT_LEGAL_NAME).exists():
            self.stdout.write(self.style.WARNING("Demo data already present — nothing to do."))
            return

        department, _ = Department.objects.get_or_create(
            code="SALES", defaults={"name": "Sales"}
        )
        designation, _ = Designation.objects.get_or_create(
            code="SALESEXEC", defaults={"name": "Sales Executive"}
        )

        employee = hr_services.create_employee(
            owner,
            full_name="Priya Sharma",
            department=department,
            designation=designation,
            date_of_joining=date.today(),
        )

        account, password = identity_services.create_user_account(
            owner, employee, username="priya.sharma"
        )
        identity_services.assign_role(owner, account, Role.objects.get(code=ROLE_SALES))

        ats, _ = ProductCategory.objects.get_or_create(
            code="ATS", defaults={"name": "ATS Panel", "is_manufactured": True}
        )
        amf, _ = ProductCategory.objects.get_or_create(
            code="AMF", defaults={"name": "AMF Panel", "is_manufactured": True}
        )

        client = sales_services.create_client(
            owner,
            legal_name=DEMO_CLIENT_LEGAL_NAME,
            billing_city="Pune",
            billing_state="Maharashtra",
            default_dispatch_policy=DispatchPolicy.PARTIAL_ALLOWED,
        )
        sales_services.add_client_contact(
            owner,
            client,
            contact_name="Rahul Deshmukh",
            phone="+91-9876543210",
            is_primary=True,
        )

        job_card = sales_services.create_job_card(
            owner,
            client,
            owner_user=account,
            enquiry_source=EnquirySource.WEBSITE,
            enquiry_date=date.today(),
            required_by=date.today() + timedelta(days=30),
            requirements="3 ATS panels + 2 AMF panels for a new substation.",
        )
        sales_services.add_job_line(
            owner,
            job_card,
            product_category=ats,
            description="ATS Panel, 415V, 200A",
            quantity=3,
        )
        sales_services.add_job_line(
            owner,
            job_card,
            product_category=amf,
            description="AMF Panel, 415V, 320A",
            quantity=2,
        )

        self.stdout.write(self.style.SUCCESS(f"Seeded employee  {employee.employee_code}"))
        self.stdout.write(
            self.style.SUCCESS(f"Seeded account   {account.username} (password: {password})")
        )
        self.stdout.write(self.style.SUCCESS(f"Seeded client    {client.client_code}"))
        self.stdout.write(
            self.style.SUCCESS(f"Seeded job card  {job_card.job_no} (2 lines: 3x ATS, 2x AMF)")
        )

    def _find_owner(self) -> UserAccount:
        owner_role_user = (
            UserRole.objects.filter(role__code=ROLE_OWNER).select_related("user").first()
        )
        if owner_role_user is None:
            raise CommandError(
                "No Owner account found — run `manage.py bootstrap_admin` first."
            )
        return owner_role_user.user
