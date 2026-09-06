"""Renumber every existing employee_code into the SRS-NNN sequence.

Before this migration, employee_code was free text: three different formats
coexisted in real data (HR-EMP-00001, ACC-EMP-001, and twenty rows as
SRS/01..SRS/020 with inconsistent zero-padding). Going forward,
apps.hr.services.create_employee and EmployeeAdmin both always call
apps.core.numbering.next_employee_code() — nobody, including Django admin,
can type a code by hand anymore.

This migration folds the existing 22 rows into that same sequence, oldest
first by created_at, so the renumbering and the counter it seeds
(core_number_series, prefix "SRS-") are the exact same call path a brand new
employee would go through — not a one-off backfill formula that could drift
from the real generator.

Not reversible: the original codes are gone once overwritten, and there is
no record of which row had which — this is a one-way data migration, like
sales/migrations/0002_remove_quotation_status_machine.py's status
reclassification.
"""

from __future__ import annotations

from django.db import migrations

from apps.core.numbering import next_employee_code


def renumber(apps, schema_editor):
    Employee = apps.get_model("hr", "Employee")
    for employee in Employee.objects.order_by("created_at"):
        employee.employee_code = next_employee_code()
        employee.save(update_fields=["employee_code"])


def unrenumber(apps, schema_editor):
    """Not reversible — see module docstring."""


class Migration(migrations.Migration):
    dependencies = [
        ("hr", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(renumber, unrenumber),
    ]
