"""The audit trail attributes writes to the right person, or to nobody.

These are the assertions every later phase's audit expectations rest on.
"""

import pytest
from django.db import connection

from apps.core.db import audit_actor, current_audit_actor
from tests.factories import EmployeeFactory, UserAccountFactory


def _audit_rows(table_name: str) -> list[tuple]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT operation, record_id, changed_by
            FROM core_audit_logs
            WHERE table_name = %s
            ORDER BY occurred_at, id
            """,
            [table_name],
        )
        return cursor.fetchall()


@pytest.mark.django_db
def test_audit_actor_attributes_the_write():
    actor = UserAccountFactory()

    with audit_actor(actor):
        employee = EmployeeFactory(full_name="Attributed Write")

    rows = [r for r in _audit_rows("hr_employees") if r[1] == employee.id]
    assert rows, "the audit trigger recorded nothing"
    assert all(str(r[2]) == str(actor.id) for r in rows), rows


@pytest.mark.django_db
def test_no_actor_yields_changed_by_null():
    """A management command or data migration has no user. NULL is the honest
    answer, not a fabricated one."""
    with audit_actor(None):
        employee = EmployeeFactory(full_name="Unattributed Write")

    rows = [r for r in _audit_rows("hr_employees") if r[1] == employee.id]
    assert rows
    assert all(r[2] is None for r in rows), rows


@pytest.mark.django_db
def test_actor_is_set_inside_the_block_and_cleared_after():
    actor = UserAccountFactory()

    with audit_actor(actor):
        assert current_audit_actor() == str(actor.id)

    assert current_audit_actor() is None


@pytest.mark.django_db
def test_nested_actor_is_restored_not_leaked():
    """SET LOCAL is scoped to the transaction, not to the savepoint a nested
    atomic() opens. Without an explicit restore, an inner actor would keep
    claiming credit for the rest of the outer transaction — and with
    ATOMIC_REQUESTS the outer transaction is the entire request."""
    outer = UserAccountFactory()
    inner = UserAccountFactory()

    with audit_actor(outer):
        assert current_audit_actor() == str(outer.id)

        with audit_actor(inner):
            assert current_audit_actor() == str(inner.id)

        assert current_audit_actor() == str(outer.id), "inner actor leaked outward"

        employee = EmployeeFactory()

    rows = [r for r in _audit_rows("hr_employees") if r[1] == employee.id]
    assert rows
    assert all(str(r[2]) == str(outer.id) for r in rows), (
        "a write after the nested block was attributed to the inner actor"
    )


@pytest.mark.django_db
def test_update_captures_both_old_and_new():
    actor = UserAccountFactory()
    employee = EmployeeFactory(full_name="Before Rename")

    with audit_actor(actor):
        employee.full_name = "After Rename"
        employee.save(update_fields=["full_name"])

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT old_data ->> 'full_name', new_data ->> 'full_name'
            FROM core_audit_logs
            WHERE table_name = 'hr_employees' AND record_id = %s AND operation = 'UPDATE'
            ORDER BY id DESC LIMIT 1
            """,
            [str(employee.id)],
        )
        old_name, new_name = cursor.fetchone()

    assert old_name == "Before Rename"
    assert new_name == "After Rename"


@pytest.mark.django_db
def test_updated_at_trigger_overrides_whatever_the_writer_supplied():
    """The trigger's job is to make updated_at un-forgeable, so the test writes
    a deliberately wrong value and checks it is overwritten.

    Note what this test does *not* assert: that updated_at moves forward
    relative to created_at. set_updated_at() uses NOW(), which is the
    transaction timestamp, so a row created and updated in one transaction
    legitimately carries identical values. That is deviation 3.3 working as
    intended, not a bug — Django's own Now() would emit statement_timestamp()
    and give a different (and schema-violating) answer.
    """
    employee = EmployeeFactory()

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE hr_employees SET updated_at = TIMESTAMPTZ '2000-01-01' WHERE id = %s",
            [str(employee.id)],
        )
        cursor.execute("SELECT updated_at = NOW() FROM hr_employees WHERE id = %s",
                       [str(employee.id)])
        assert cursor.fetchone()[0] is True, "set_updated_at() did not override the write"


@pytest.mark.django_db
def test_created_at_and_updated_at_match_within_one_transaction():
    """Pins deviation 3.3 so a later change to Django's Now() cannot pass unnoticed."""
    employee = EmployeeFactory()
    assert employee.created_at == employee.updated_at


@pytest.mark.django_db
def test_direct_sql_write_is_audited_too():
    """Triggers, not Django signals. A write that bypasses the ORM entirely —
    a data fix run from psql — still lands in the trail."""
    employee = EmployeeFactory()

    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE hr_employees SET personal_phone = %s WHERE id = %s",
            ["+91-90000-00000", str(employee.id)],
        )

    rows = [
        r for r in _audit_rows("hr_employees") if r[1] == employee.id and r[0] == "UPDATE"
    ]
    assert rows, "an ORM-bypassing write escaped the audit trail"
