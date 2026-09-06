"""Create the very first department, employee, account and Owner assignment.

``createsuperuser`` cannot work here. ``auth_user_accounts.employee_id`` is NOT
NULL, an employee needs a department, and there is no ``is_superuser`` column
to set. Without this command a freshly migrated database has no way to create
the first row of anything — a locked door with the key inside.

Everything happens in one transaction: either the whole chain exists or none of
it does.
"""

from __future__ import annotations

import secrets
import string

from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError

from apps.core.db import audit_actor
from apps.core.models import Department, Designation
from apps.core.numbering import next_employee_code
from apps.hr.models import Employee
from apps.identity.constants import ROLE_OWNER
from apps.identity.models import Role, UserAccount, UserRole

PASSWORD_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*-_"


def generate_password(length: int = 20) -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


class Command(BaseCommand):
    help = "Create the first department, employee, user account and Owner role assignment."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--full-name", required=True)
        parser.add_argument(
            "--password",
            help="Omit to have one generated and printed once. Never reuse the printed value.",
        )
        parser.add_argument("--department-code", default="MGMT")
        parser.add_argument("--department-name", default="Management")
        parser.add_argument("--designation-code", default="OWNER")
        parser.add_argument("--designation-name", default="Owner")
        parser.add_argument(
            "--date-of-joining", default=None, help="YYYY-MM-DD, defaults to today."
        )

    def handle(self, *args, **options):
        from datetime import date

        username: str = options["username"]
        password: str = options["password"] or generate_password()
        generated = not options["password"]

        if UserAccount.objects.filter(username=username).exists():
            raise CommandError(f"A user account named {username!r} already exists.")

        joining = (
            date.fromisoformat(options["date_of_joining"])
            if options["date_of_joining"]
            else date.today()
        )

        # No actor: nobody is logged in yet, and changed_by IS NULL is the
        # truthful record of that.
        try:
            with audit_actor(None):
                department, _ = Department.objects.get_or_create(
                    code=options["department_code"],
                    defaults={"name": options["department_name"]},
                )
                designation, _ = Designation.objects.get_or_create(
                    code=options["designation_code"],
                    defaults={"name": options["designation_name"]},
                )
                employee = Employee.objects.create(
                    employee_code=next_employee_code(),
                    full_name=options["full_name"],
                    department=department,
                    designation=designation,
                    date_of_joining=joining,
                )
                if UserAccount.objects.filter(employee=employee).exists():
                    raise CommandError(
                        f"Employee {employee.employee_code} already has an account."
                    )

                user = UserAccount.objects.create_user(
                    username=username,
                    employee=employee,
                    password=password,
                    # The bootstrap account is expected to rotate this at first
                    # login like any other.
                    must_change_password=True,
                )

                role = Role.objects.filter(code=ROLE_OWNER).first()
                if role is None:
                    raise CommandError(
                        f"Role {ROLE_OWNER!r} does not exist. Run `migrate` first — the "
                        "roles and the permission grid are seeded by a data migration."
                    )
                UserRole.objects.create(user=user, role=role, assigned_by=None)
        except IntegrityError as exc:
            raise CommandError(f"Bootstrap failed, nothing was created: {exc}") from exc

        self.stdout.write(self.style.SUCCESS(f"Created department  {department.code}"))
        self.stdout.write(self.style.SUCCESS(f"Created designation {designation.code}"))
        self.stdout.write(self.style.SUCCESS(f"Created employee    {employee.employee_code}"))
        self.stdout.write(self.style.SUCCESS(f"Created account     {user.username}"))
        self.stdout.write(self.style.SUCCESS(f"Assigned role       {role.code}"))
        if generated:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Generated password (shown once):"))
            self.stdout.write(f"    {password}")
            self.stdout.write(
                self.style.WARNING("must_change_password is set; it will be rotated at login.")
            )
