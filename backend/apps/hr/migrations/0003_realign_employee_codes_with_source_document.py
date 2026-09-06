"""Realign employee_code with the source document, and split off test accounts.

0002 renumbered every employee into SRS-NNN oldest-first by created_at. Two
rows in that ordering are not real employees at all — "Aswin" and "Govind
Sharma" were created first (2026-08-25) as throwaway accounts for deploying
and testing the software, before the real 20-person roster from
``company-docs/SR Switchgear Employee List.docx`` was seeded (2026-09-03).
Because 0002 renumbered purely by created_at, those two test accounts landed
on SRS-001/SRS-002 and pushed every real employee's code two off from the
number the source document actually assigned them (e.g. Shine Ts, document
SRS/01, ended up SRS-003).

This migration:
1. Reassigns the 20 real employees back to the SRS-NNN implied by the
   document's own per-person numbering (SRS/01 -> SRS-001, ... SRS/020 ->
   SRS-020), matched by full_name.
2. Moves the 2 test accounts onto a separate TEST-NNN sequence (TEST-001,
   TEST-002) so they're never confused with real SRS- employee codes again.

Matching by full_name (not by current employee_code, which is exactly what's
wrong) means this only touches these 22 specific already-known people; it is
not a general renumbering tool.

Uses a two-phase update (real code -> unique TMP- placeholder -> final code)
because uk_employees_code is a plain, non-deferrable UNIQUE constraint:
writing final codes directly would collide mid-migration wherever a target
code is still held by a different row (e.g. Aswin holds SRS-001, which Shine
Ts needs).

Not reversible: same reasoning as 0002 — once overwritten there's no record
of which row had which code before this ran.
"""

from __future__ import annotations

from django.db import migrations

# full_name (as currently stored) -> target employee_code
_REAL_EMPLOYEE_CODES = {
    "Shine Ts": "SRS-001",
    "Govind Singh": "SRS-002",
    "Santosh": "SRS-003",
    "Rajendra Saini": "SRS-004",
    "Shankal Lal Gurjar": "SRS-005",
    "Surandran K": "SRS-006",
    "Narpat Singh": "SRS-007",
    "Sarda": "SRS-008",
    "Dhiraj": "SRS-009",
    "Gopinathan K": "SRS-010",
    "Sharad Kumar": "SRS-011",
    "Govind Kumawat": "SRS-012",
    "Dharmahendra": "SRS-013",
    "Sanjeev Ji": "SRS-014",
    "Dinesh Sharma": "SRS-015",
    "Ansh Verma": "SRS-016",
    "Deepak Saini": "SRS-017",
    "Pankaj": "SRS-018",
    "Ashok": "SRS-019",
    "Vikram Singh": "SRS-020",
}

_TEST_EMPLOYEE_CODES = {
    "Aswin": "TEST-001",
    "Govind Sharma": "TEST-002",
}


def realign(apps, schema_editor):
    """No-op on any database that doesn't have this exact roster — a fresh
    CI database (``pytest --create-db``) or a different deployment's real
    data was never in the broken state this migration corrects."""
    Employee = apps.get_model("hr", "Employee")
    targets = {**_REAL_EMPLOYEE_CODES, **_TEST_EMPLOYEE_CODES}

    employees = {e.full_name: e for e in Employee.objects.filter(full_name__in=targets)}

    for employee in employees.values():
        employee.employee_code = f"TMP-{employee.pk}"
        employee.save(update_fields=["employee_code"])

    for full_name, employee in employees.items():
        employee.employee_code = targets[full_name]
        employee.save(update_fields=["employee_code"])


def unrealign(apps, schema_editor):
    """Not reversible — see module docstring."""


class Migration(migrations.Migration):
    dependencies = [
        ("hr", "0002_srs_employee_code_sequence"),
    ]

    operations = [
        migrations.RunPython(realign, unrealign),
    ]
