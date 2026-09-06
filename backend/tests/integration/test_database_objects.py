"""One smoke test for migration 0003, not a suite.

Per the prompt, no Django test re-tests a CHECK constraint that PostgreSQL
already enforces. What is worth asserting is that the objects Django cannot
express actually got created — because if the RunSQL silently no-ops, every
audit and concurrency guarantee in this system quietly disappears and nothing
else would notice.
"""

import pytest
from django.db import connection

# The 21 triggers the reference schema defines: 13 updated_at, 1 transition
# guard, 7 audit.
EXPECTED_TRIGGERS = {
    "trg_departments_updated",
    "trg_designations_updated",
    "trg_user_accounts_updated",
    "trg_roles_updated",
    "trg_employees_updated",
    "trg_stages_updated",
    "trg_transition_rules_updated",
    "trg_clients_updated",
    "trg_client_contacts_updated",
    "trg_product_categories_updated",
    "trg_job_cards_updated",
    "trg_job_lines_updated",
    "trg_quotations_updated",
    "trg_apply_transition",
    "trg_audit_employees",
    "trg_audit_user_accounts",
    "trg_audit_user_roles",
    "trg_audit_role_perms",
    "trg_audit_job_cards",
    "trg_audit_job_lines",
    "trg_audit_quotations",
}

EXPECTED_FUNCTIONS = {"set_updated_at", "apply_transition", "record_audit", "next_number"}


@pytest.mark.django_db
def test_all_21_triggers_exist():
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT t.tgname
            FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND NOT t.tgisinternal
            """
        )
        found = {row[0] for row in cursor.fetchall()}

    assert EXPECTED_TRIGGERS <= found, f"missing: {sorted(EXPECTED_TRIGGERS - found)}"
    assert len(EXPECTED_TRIGGERS) == 21


@pytest.mark.django_db
def test_plpgsql_functions_exist():
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT p.proname FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
            WHERE n.nspname = 'public' AND p.prolang = (
                SELECT oid FROM pg_language WHERE lanname = 'plpgsql'
            )
            """
        )
        found = {row[0] for row in cursor.fetchall()}

    assert EXPECTED_FUNCTIONS <= found, f"missing: {sorted(EXPECTED_FUNCTIONS - found)}"


@pytest.mark.django_db
def test_audit_log_is_partitioned_with_room_to_spare():
    """D10. A missing partition aborts the business transaction, not just the
    audit write, so this is an availability assertion."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relkind FROM pg_class WHERE relname = 'core_audit_logs'"
        )
        assert cursor.fetchone()[0] == "p", "core_audit_logs is not a partitioned table"

        cursor.execute(
            """
            SELECT c.relname FROM pg_inherits i
            JOIN pg_class c ON c.oid = i.inhrelid
            WHERE i.inhparent = 'core_audit_logs'::regclass
            ORDER BY c.relname
            """
        )
        partitions = [row[0] for row in cursor.fetchall()]

    assert len(partitions) >= 10, partitions
    assert "core_audit_logs_2026_q3" in partitions
    assert "core_audit_logs_2028_q4" in partitions

    # And the window really is open now — not merely a list of table names.
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO core_audit_logs (table_schema, table_name, operation)
            VALUES ('public', 'partition_probe', 'INSERT') RETURNING id
            """
        )
        assert cursor.fetchone()[0] is not None
        cursor.execute("DELETE FROM core_audit_logs WHERE table_name = 'partition_probe'")


@pytest.mark.django_db
def test_foreign_keys_are_not_deferrable_and_keep_their_delete_actions():
    """D8. This is the whole reason every FK field is db_constraint=False."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*) FROM pg_constraint
            WHERE contype = 'f' AND conname LIKE 'fk_%' AND condeferrable
            """
        )
        assert cursor.fetchone()[0] == 0, "a schema FK came out DEFERRABLE"

        # confdeltype 'a' is NO ACTION — what Django emits when it manages the
        # constraint itself and implements deletes in Python instead.
        cursor.execute(
            """
            SELECT conname FROM pg_constraint
            WHERE contype = 'f' AND conname LIKE 'fk_%' AND confdeltype = 'a'
            """
        )
        assert cursor.fetchall() == [], "a schema FK lost its ON DELETE action"

        cursor.execute(
            "SELECT count(*) FROM pg_constraint WHERE contype = 'f' AND conname LIKE 'fk_%'"
        )
        # 46 minus fk_quotations_sent_by, dropped by
        # sales/migrations/0002_remove_quotation_status_machine.py.
        assert cursor.fetchone()[0] == 45


@pytest.mark.django_db
def test_composite_primary_keys_survived():
    """quotation_lines keeps its natural key; audit_logs keeps (id, occurred_at)."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT pg_get_constraintdef(oid) FROM pg_constraint
            WHERE contype = 'p' AND conrelid = 'sales_quotation_lines'::regclass
            """
        )
        assert cursor.fetchone()[0] == "PRIMARY KEY (quotation_id, job_line_id)"

        cursor.execute(
            """
            SELECT pg_get_constraintdef(oid) FROM pg_constraint
            WHERE contype = 'p' AND conrelid = 'core_audit_logs'::regclass
            """
        )
        assert cursor.fetchone()[0] == "PRIMARY KEY (id, occurred_at)"


@pytest.mark.django_db
def test_citext_columns_are_really_citext():
    """Deviation 3.1. A varchar here would silently make usernames
    case-sensitive and let 'Asha' and 'asha' both register."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name || '.' || column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND udt_name = 'citext'
            ORDER BY 1
            """
        )
        found = {row[0] for row in cursor.fetchall()}

    assert "auth_user_accounts.username" in found
    assert "hr_employees.employee_code" in found
    assert "hr_employees.personal_email" in found
    assert len(found) == 10, sorted(found)


@pytest.mark.django_db
def test_fixed_width_char_columns():
    """Deviation 3.5: CharField would have emitted varchar."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name || '.' || column_name || '(' || character_maximum_length || ')'
            FROM information_schema.columns
            WHERE table_schema = 'public' AND data_type = 'character'
            ORDER BY 1
            """
        )
        found = {row[0] for row in cursor.fetchall()}

    assert found == {
        "core_documents.sha256(64)",
        "sales_clients.gstin(15)",
        "sales_quotations.currency(3)",
    }, found
