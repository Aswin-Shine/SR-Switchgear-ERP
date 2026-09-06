"""Everything Django's ORM cannot express.

Copied from ``docs/schema/sr_erp_schema_v2.sql`` with only the table names
adjusted: the schema uses PostgreSQL schemas (``core.departments``), Django
uses a flat namespace (``core_departments``). Nothing else is reworded, and in
particular ``apply_transition()`` and ``record_audit()`` are carried across
verbatim rather than reimplemented in Python.

What lives here, and why it cannot live in a model:

1. ``set_updated_at()`` and its 13 ``BEFORE UPDATE`` triggers.
2. ``apply_transition()`` and ``trg_apply_transition``. This is a concurrency
   guard: it takes ``FOR UPDATE`` on the job line and rejects any transition
   whose claimed source stage does not match reality. Django has no equivalent.
3. ``record_audit()`` and its 7 ``AFTER`` triggers. Triggers, not signals, so
   nothing bypasses the trail — including direct ``psql`` access.
4. ``core_audit_logs``: range-partitioned with a composite ``(id, occurred_at)``
   primary key. Django supports neither, hence ``managed = False``.
5. ``next_number()``.
6. All 46 foreign keys, with the schema's own names, its explicit ``ON DELETE``
   actions, and ``NOT DEFERRABLE`` (D8). Django emits deferrable FKs with no
   ``ON DELETE`` clause at all, because it implements delete behaviour in the
   Python collector; reproducing them here keeps the database correct on its
   own terms, and delivers the readable constraint names that defect #8 in the
   schema review asked for.
7. Two indexes whose schema names are 31 characters, which Django's
   ``models.E034`` refuses to accept in ``Meta.indexes`` even though PostgreSQL
   allows 63.

Reversing this migration DROPS THE AUDIT LOG. There is no other copy. The
REVERSE block carries the same warning as
``docs/schema/sr_erp_schema_v2_rollback.sql``.
"""

from django.db import migrations

from apps.core.partitions import INITIAL_PARTITION_DDL

# --- 1. updated_at ----------------------------------------------------------

SET_UPDATED_AT = """
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at := NOW();
  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_departments_updated        BEFORE UPDATE ON core_departments         FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_designations_updated       BEFORE UPDATE ON core_designations        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_user_accounts_updated      BEFORE UPDATE ON auth_user_accounts       FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_roles_updated              BEFORE UPDATE ON auth_roles               FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_employees_updated          BEFORE UPDATE ON hr_employees             FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_stages_updated             BEFORE UPDATE ON pipeline_stages          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_transition_rules_updated   BEFORE UPDATE ON pipeline_transition_rules FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_clients_updated            BEFORE UPDATE ON sales_clients            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_client_contacts_updated    BEFORE UPDATE ON sales_client_contacts    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_product_categories_updated BEFORE UPDATE ON sales_product_categories FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_job_cards_updated          BEFORE UPDATE ON sales_job_cards          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_job_lines_updated          BEFORE UPDATE ON sales_job_lines          FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_quotations_updated         BEFORE UPDATE ON sales_quotations         FOR EACH ROW EXECUTE FUNCTION set_updated_at();
"""

# --- 2. the transition guard ------------------------------------------------

APPLY_TRANSITION = """
CREATE OR REPLACE FUNCTION apply_transition()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  actual_stage UUID;
BEGIN
  SELECT current_stage_id INTO actual_stage
  FROM sales_job_lines WHERE id = NEW.job_line_id FOR UPDATE;

  IF NEW.from_stage_id IS DISTINCT FROM actual_stage THEN
    RAISE EXCEPTION 'Stale transition: line is at % but transition claims %',
      actual_stage, NEW.from_stage_id;
  END IF;

  UPDATE sales_job_lines
     SET current_stage_id = NEW.to_stage_id
   WHERE id = NEW.job_line_id;

  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_apply_transition
  AFTER INSERT ON pipeline_job_line_transitions
  FOR EACH ROW EXECUTE FUNCTION apply_transition();
"""

# --- 3 & 4. the audit log and its triggers ----------------------------------

# NOTE ON table_schema: the schema records TG_TABLE_SCHEMA, which is meaningful
# when tables live in core/hr/auth/sales/pipeline schemas. Django puts every
# table in `public`, so this column records 'public' for every row. The
# table_name column still distinguishes them, and the function is carried over
# verbatim rather than "improved", per the precedence rules. Recorded in
# IMPLEMENTATION.md so it is not mistaken for a bug.
AUDIT_LOG = f"""
CREATE TABLE core_audit_logs (
  id            BIGSERIAL,
  occurred_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  table_schema  TEXT NOT NULL,
  table_name    TEXT NOT NULL,
  record_id     UUID,
  operation     TEXT NOT NULL,
  changed_by    UUID,
  old_data      JSONB,
  new_data      JSONB,
  CONSTRAINT pk_audit_logs      PRIMARY KEY (id, occurred_at),
  CONSTRAINT ck_audit_operation CHECK (operation IN ('INSERT','UPDATE','DELETE'))
) PARTITION BY RANGE (occurred_at);

{INITIAL_PARTITION_DDL}

CREATE INDEX idx_audit_logs_record
  ON core_audit_logs(table_schema, table_name, record_id, occurred_at DESC);

CREATE OR REPLACE FUNCTION record_audit()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  INSERT INTO core_audit_logs(table_schema, table_name, record_id, operation,
                              changed_by, old_data, new_data)
  VALUES (
    TG_TABLE_SCHEMA,
    TG_TABLE_NAME,
    COALESCE((to_jsonb(NEW)->>'id')::uuid, (to_jsonb(OLD)->>'id')::uuid),
    TG_OP,
    NULLIF(current_setting('app.current_user_id', TRUE), '')::uuid,
    CASE WHEN TG_OP IN ('UPDATE','DELETE') THEN to_jsonb(OLD) END,
    CASE WHEN TG_OP IN ('INSERT','UPDATE') THEN to_jsonb(NEW) END
  );
  RETURN NULL;
END;
$$;

CREATE TRIGGER trg_audit_employees     AFTER INSERT OR UPDATE OR DELETE ON hr_employees           FOR EACH ROW EXECUTE FUNCTION record_audit();
CREATE TRIGGER trg_audit_user_accounts AFTER INSERT OR UPDATE OR DELETE ON auth_user_accounts     FOR EACH ROW EXECUTE FUNCTION record_audit();
CREATE TRIGGER trg_audit_user_roles    AFTER INSERT OR UPDATE OR DELETE ON auth_user_roles        FOR EACH ROW EXECUTE FUNCTION record_audit();
CREATE TRIGGER trg_audit_role_perms    AFTER INSERT OR UPDATE OR DELETE ON auth_role_permissions  FOR EACH ROW EXECUTE FUNCTION record_audit();
CREATE TRIGGER trg_audit_job_cards     AFTER INSERT OR UPDATE OR DELETE ON sales_job_cards        FOR EACH ROW EXECUTE FUNCTION record_audit();
CREATE TRIGGER trg_audit_job_lines     AFTER INSERT OR UPDATE OR DELETE ON sales_job_lines        FOR EACH ROW EXECUTE FUNCTION record_audit();
CREATE TRIGGER trg_audit_quotations    AFTER INSERT OR UPDATE OR DELETE ON sales_quotations       FOR EACH ROW EXECUTE FUNCTION record_audit();
"""

# --- 5. number generation ---------------------------------------------------

NEXT_NUMBER = """
CREATE OR REPLACE FUNCTION next_number(p_prefix TEXT, p_width INT DEFAULT 5)
RETURNS TEXT
LANGUAGE plpgsql
AS $$
DECLARE
  v_next BIGINT;
BEGIN
  INSERT INTO core_number_series(prefix, current)
  VALUES (p_prefix, 1)
  ON CONFLICT (prefix) DO UPDATE
    SET current = core_number_series.current + 1,
        updated_at = NOW()
  RETURNING current INTO v_next;

  RETURN p_prefix || lpad(v_next::text, p_width, '0');
END;
$$;
"""

# --- 6. foreign keys --------------------------------------------------------

# All 46, NOT DEFERRABLE, with the schema's names and delete actions (D8).
# Ordering does not matter: every referenced table already exists by now.
FOREIGN_KEYS = """
ALTER TABLE core_departments ADD CONSTRAINT fk_departments_parent
  FOREIGN KEY (parent_department_id) REFERENCES core_departments(id) ON DELETE RESTRICT;
ALTER TABLE core_documents ADD CONSTRAINT fk_documents_uploaded_by
  FOREIGN KEY (uploaded_by) REFERENCES auth_user_accounts(id) ON DELETE RESTRICT;

ALTER TABLE auth_user_accounts ADD CONSTRAINT fk_user_accounts_employee
  FOREIGN KEY (employee_id) REFERENCES hr_employees(id) ON DELETE RESTRICT;
ALTER TABLE auth_user_accounts ADD CONSTRAINT fk_user_accounts_created_by
  FOREIGN KEY (created_by) REFERENCES auth_user_accounts(id) ON DELETE SET NULL;
ALTER TABLE auth_sessions ADD CONSTRAINT fk_sessions_user
  FOREIGN KEY (user_id) REFERENCES auth_user_accounts(id) ON DELETE CASCADE;
ALTER TABLE auth_user_roles ADD CONSTRAINT fk_user_roles_user
  FOREIGN KEY (user_id) REFERENCES auth_user_accounts(id) ON DELETE CASCADE;
ALTER TABLE auth_user_roles ADD CONSTRAINT fk_user_roles_role
  FOREIGN KEY (role_id) REFERENCES auth_roles(id) ON DELETE RESTRICT;
ALTER TABLE auth_user_roles ADD CONSTRAINT fk_user_roles_assigner
  FOREIGN KEY (assigned_by) REFERENCES auth_user_accounts(id) ON DELETE SET NULL;
ALTER TABLE auth_role_permissions ADD CONSTRAINT fk_role_permissions_role
  FOREIGN KEY (role_id) REFERENCES auth_roles(id) ON DELETE CASCADE;
ALTER TABLE auth_role_permissions ADD CONSTRAINT fk_role_permissions_perm
  FOREIGN KEY (permission_id) REFERENCES auth_permissions(id) ON DELETE CASCADE;

ALTER TABLE hr_employees ADD CONSTRAINT fk_employees_department
  FOREIGN KEY (department_id) REFERENCES core_departments(id) ON DELETE RESTRICT;
ALTER TABLE hr_employees ADD CONSTRAINT fk_employees_designation
  FOREIGN KEY (designation_id) REFERENCES core_designations(id) ON DELETE RESTRICT;
ALTER TABLE hr_employees ADD CONSTRAINT fk_employees_reports_to
  FOREIGN KEY (reports_to_id) REFERENCES hr_employees(id) ON DELETE SET NULL;
ALTER TABLE hr_employees ADD CONSTRAINT fk_employees_photo
  FOREIGN KEY (photo_document_id) REFERENCES core_documents(id) ON DELETE SET NULL;
ALTER TABLE hr_employee_documents ADD CONSTRAINT fk_employee_documents_emp
  FOREIGN KEY (employee_id) REFERENCES hr_employees(id) ON DELETE CASCADE;
ALTER TABLE hr_employee_documents ADD CONSTRAINT fk_employee_documents_doc
  FOREIGN KEY (document_id) REFERENCES core_documents(id) ON DELETE RESTRICT;

ALTER TABLE pipeline_stages ADD CONSTRAINT fk_stages_department
  FOREIGN KEY (department_id) REFERENCES core_departments(id) ON DELETE RESTRICT;
ALTER TABLE pipeline_transition_rules ADD CONSTRAINT fk_transition_rules_from
  FOREIGN KEY (from_stage_id) REFERENCES pipeline_stages(id) ON DELETE RESTRICT;
ALTER TABLE pipeline_transition_rules ADD CONSTRAINT fk_transition_rules_to
  FOREIGN KEY (to_stage_id) REFERENCES pipeline_stages(id) ON DELETE RESTRICT;
ALTER TABLE pipeline_transition_rules ADD CONSTRAINT fk_transition_rules_role
  FOREIGN KEY (allowed_role_id) REFERENCES auth_roles(id) ON DELETE RESTRICT;
ALTER TABLE pipeline_job_line_transitions ADD CONSTRAINT fk_job_line_transitions_line
  FOREIGN KEY (job_line_id) REFERENCES sales_job_lines(id) ON DELETE CASCADE;
ALTER TABLE pipeline_job_line_transitions ADD CONSTRAINT fk_job_line_transitions_from
  FOREIGN KEY (from_stage_id) REFERENCES pipeline_stages(id) ON DELETE RESTRICT;
ALTER TABLE pipeline_job_line_transitions ADD CONSTRAINT fk_job_line_transitions_to
  FOREIGN KEY (to_stage_id) REFERENCES pipeline_stages(id) ON DELETE RESTRICT;
ALTER TABLE pipeline_job_line_transitions ADD CONSTRAINT fk_job_line_transitions_by
  FOREIGN KEY (performed_by) REFERENCES auth_user_accounts(id) ON DELETE RESTRICT;

ALTER TABLE sales_clients ADD CONSTRAINT fk_clients_creator
  FOREIGN KEY (created_by) REFERENCES auth_user_accounts(id) ON DELETE SET NULL;
ALTER TABLE sales_client_contacts ADD CONSTRAINT fk_client_contacts_client
  FOREIGN KEY (client_id) REFERENCES sales_clients(id) ON DELETE CASCADE;
ALTER TABLE sales_job_cards ADD CONSTRAINT fk_job_cards_client
  FOREIGN KEY (client_id) REFERENCES sales_clients(id) ON DELETE RESTRICT;
ALTER TABLE sales_job_cards ADD CONSTRAINT fk_job_cards_contact
  FOREIGN KEY (client_contact_id) REFERENCES sales_client_contacts(id) ON DELETE SET NULL;
ALTER TABLE sales_job_cards ADD CONSTRAINT fk_job_cards_owner
  FOREIGN KEY (owner_user_id) REFERENCES auth_user_accounts(id) ON DELETE RESTRICT;
ALTER TABLE sales_job_lines ADD CONSTRAINT fk_job_lines_job_card
  FOREIGN KEY (job_card_id) REFERENCES sales_job_cards(id) ON DELETE CASCADE;
ALTER TABLE sales_job_lines ADD CONSTRAINT fk_job_lines_category
  FOREIGN KEY (product_category_id) REFERENCES sales_product_categories(id) ON DELETE RESTRICT;
ALTER TABLE sales_job_lines ADD CONSTRAINT fk_job_lines_stage
  FOREIGN KEY (current_stage_id) REFERENCES pipeline_stages(id) ON DELETE RESTRICT;

ALTER TABLE sales_quotations ADD CONSTRAINT fk_quotations_job_card
  FOREIGN KEY (job_card_id) REFERENCES sales_job_cards(id) ON DELETE RESTRICT;
ALTER TABLE sales_quotations ADD CONSTRAINT fk_quotations_supersedes
  FOREIGN KEY (supersedes_id) REFERENCES sales_quotations(id) ON DELETE RESTRICT;
ALTER TABLE sales_quotations ADD CONSTRAINT fk_quotations_pdf
  FOREIGN KEY (pdf_document_id) REFERENCES core_documents(id) ON DELETE RESTRICT;
ALTER TABLE sales_quotations ADD CONSTRAINT fk_quotations_prepared_by
  FOREIGN KEY (prepared_by) REFERENCES auth_user_accounts(id) ON DELETE RESTRICT;
ALTER TABLE sales_quotations ADD CONSTRAINT fk_quotations_sent_by
  FOREIGN KEY (sent_by) REFERENCES auth_user_accounts(id) ON DELETE RESTRICT;
ALTER TABLE sales_quotation_lines ADD CONSTRAINT fk_quotation_lines_quote
  FOREIGN KEY (quotation_id) REFERENCES sales_quotations(id) ON DELETE CASCADE;
ALTER TABLE sales_quotation_lines ADD CONSTRAINT fk_quotation_lines_line
  FOREIGN KEY (job_line_id) REFERENCES sales_job_lines(id) ON DELETE RESTRICT;

ALTER TABLE sales_job_notes ADD CONSTRAINT fk_job_notes_job_card
  FOREIGN KEY (job_card_id) REFERENCES sales_job_cards(id) ON DELETE CASCADE;
ALTER TABLE sales_job_notes ADD CONSTRAINT fk_job_notes_job_line
  FOREIGN KEY (job_line_id) REFERENCES sales_job_lines(id) ON DELETE CASCADE;
ALTER TABLE sales_job_notes ADD CONSTRAINT fk_job_notes_author
  FOREIGN KEY (author_user_id) REFERENCES auth_user_accounts(id) ON DELETE RESTRICT;
ALTER TABLE sales_job_attachments ADD CONSTRAINT fk_job_attachments_card
  FOREIGN KEY (job_card_id) REFERENCES sales_job_cards(id) ON DELETE CASCADE;
ALTER TABLE sales_job_attachments ADD CONSTRAINT fk_job_attachments_line
  FOREIGN KEY (job_line_id) REFERENCES sales_job_lines(id) ON DELETE CASCADE;
ALTER TABLE sales_job_attachments ADD CONSTRAINT fk_job_attachments_doc
  FOREIGN KEY (document_id) REFERENCES core_documents(id) ON DELETE RESTRICT;
ALTER TABLE sales_job_attachments ADD CONSTRAINT fk_job_attachments_by
  FOREIGN KEY (attached_by) REFERENCES auth_user_accounts(id) ON DELETE RESTRICT;
"""

# --- 7. the two over-long index names ---------------------------------------

LONG_NAMED_INDEXES = """
CREATE INDEX idx_employee_documents_employee ON hr_employee_documents(employee_id);
CREATE INDEX idx_employee_documents_document ON hr_employee_documents(document_id);
"""

FORWARD = "\n".join(
    [SET_UPDATED_AT, APPLY_TRANSITION, AUDIT_LOG, NEXT_NUMBER, FOREIGN_KEYS, LONG_NAMED_INDEXES]
)

# --- REVERSE ----------------------------------------------------------------
#
# !! REVERSING THIS MIGRATION DESTROYS THE AUDIT HISTORY !!
#
# DROP TABLE core_audit_logs takes every partition with it. There is no other
# copy of who changed what. Take a dump first:
#     pg_dump -Fc -t core_audit_logs srerp > audit_pre_rollback.dump
#
# Dropped in dependency order: triggers, then functions, then foreign keys,
# then the audit table.

REVERSE = """
DROP TRIGGER IF EXISTS trg_departments_updated        ON core_departments;
DROP TRIGGER IF EXISTS trg_designations_updated       ON core_designations;
DROP TRIGGER IF EXISTS trg_user_accounts_updated      ON auth_user_accounts;
DROP TRIGGER IF EXISTS trg_roles_updated              ON auth_roles;
DROP TRIGGER IF EXISTS trg_employees_updated          ON hr_employees;
DROP TRIGGER IF EXISTS trg_stages_updated             ON pipeline_stages;
DROP TRIGGER IF EXISTS trg_transition_rules_updated   ON pipeline_transition_rules;
DROP TRIGGER IF EXISTS trg_clients_updated            ON sales_clients;
DROP TRIGGER IF EXISTS trg_client_contacts_updated    ON sales_client_contacts;
DROP TRIGGER IF EXISTS trg_product_categories_updated ON sales_product_categories;
DROP TRIGGER IF EXISTS trg_job_cards_updated          ON sales_job_cards;
DROP TRIGGER IF EXISTS trg_job_lines_updated          ON sales_job_lines;
DROP TRIGGER IF EXISTS trg_quotations_updated         ON sales_quotations;

DROP TRIGGER IF EXISTS trg_apply_transition ON pipeline_job_line_transitions;

DROP TRIGGER IF EXISTS trg_audit_employees     ON hr_employees;
DROP TRIGGER IF EXISTS trg_audit_user_accounts ON auth_user_accounts;
DROP TRIGGER IF EXISTS trg_audit_user_roles    ON auth_user_roles;
DROP TRIGGER IF EXISTS trg_audit_role_perms    ON auth_role_permissions;
DROP TRIGGER IF EXISTS trg_audit_job_cards     ON sales_job_cards;
DROP TRIGGER IF EXISTS trg_audit_job_lines     ON sales_job_lines;
DROP TRIGGER IF EXISTS trg_audit_quotations    ON sales_quotations;

DROP FUNCTION IF EXISTS set_updated_at();
DROP FUNCTION IF EXISTS apply_transition();
DROP FUNCTION IF EXISTS record_audit();
DROP FUNCTION IF EXISTS next_number(TEXT, INT);

ALTER TABLE core_departments             DROP CONSTRAINT IF EXISTS fk_departments_parent;
ALTER TABLE core_documents               DROP CONSTRAINT IF EXISTS fk_documents_uploaded_by;
ALTER TABLE auth_user_accounts           DROP CONSTRAINT IF EXISTS fk_user_accounts_employee;
ALTER TABLE auth_user_accounts           DROP CONSTRAINT IF EXISTS fk_user_accounts_created_by;
ALTER TABLE auth_sessions                DROP CONSTRAINT IF EXISTS fk_sessions_user;
ALTER TABLE auth_user_roles              DROP CONSTRAINT IF EXISTS fk_user_roles_user;
ALTER TABLE auth_user_roles              DROP CONSTRAINT IF EXISTS fk_user_roles_role;
ALTER TABLE auth_user_roles              DROP CONSTRAINT IF EXISTS fk_user_roles_assigner;
ALTER TABLE auth_role_permissions        DROP CONSTRAINT IF EXISTS fk_role_permissions_role;
ALTER TABLE auth_role_permissions        DROP CONSTRAINT IF EXISTS fk_role_permissions_perm;
ALTER TABLE hr_employees                 DROP CONSTRAINT IF EXISTS fk_employees_department;
ALTER TABLE hr_employees                 DROP CONSTRAINT IF EXISTS fk_employees_designation;
ALTER TABLE hr_employees                 DROP CONSTRAINT IF EXISTS fk_employees_reports_to;
ALTER TABLE hr_employees                 DROP CONSTRAINT IF EXISTS fk_employees_photo;
ALTER TABLE hr_employee_documents        DROP CONSTRAINT IF EXISTS fk_employee_documents_emp;
ALTER TABLE hr_employee_documents        DROP CONSTRAINT IF EXISTS fk_employee_documents_doc;
ALTER TABLE pipeline_stages              DROP CONSTRAINT IF EXISTS fk_stages_department;
ALTER TABLE pipeline_transition_rules    DROP CONSTRAINT IF EXISTS fk_transition_rules_from;
ALTER TABLE pipeline_transition_rules    DROP CONSTRAINT IF EXISTS fk_transition_rules_to;
ALTER TABLE pipeline_transition_rules    DROP CONSTRAINT IF EXISTS fk_transition_rules_role;
ALTER TABLE pipeline_job_line_transitions DROP CONSTRAINT IF EXISTS fk_job_line_transitions_line;
ALTER TABLE pipeline_job_line_transitions DROP CONSTRAINT IF EXISTS fk_job_line_transitions_from;
ALTER TABLE pipeline_job_line_transitions DROP CONSTRAINT IF EXISTS fk_job_line_transitions_to;
ALTER TABLE pipeline_job_line_transitions DROP CONSTRAINT IF EXISTS fk_job_line_transitions_by;
ALTER TABLE sales_clients                DROP CONSTRAINT IF EXISTS fk_clients_creator;
ALTER TABLE sales_client_contacts        DROP CONSTRAINT IF EXISTS fk_client_contacts_client;
ALTER TABLE sales_job_cards              DROP CONSTRAINT IF EXISTS fk_job_cards_client;
ALTER TABLE sales_job_cards              DROP CONSTRAINT IF EXISTS fk_job_cards_contact;
ALTER TABLE sales_job_cards              DROP CONSTRAINT IF EXISTS fk_job_cards_owner;
ALTER TABLE sales_job_lines              DROP CONSTRAINT IF EXISTS fk_job_lines_job_card;
ALTER TABLE sales_job_lines              DROP CONSTRAINT IF EXISTS fk_job_lines_category;
ALTER TABLE sales_job_lines              DROP CONSTRAINT IF EXISTS fk_job_lines_stage;
ALTER TABLE sales_quotations             DROP CONSTRAINT IF EXISTS fk_quotations_job_card;
ALTER TABLE sales_quotations             DROP CONSTRAINT IF EXISTS fk_quotations_supersedes;
ALTER TABLE sales_quotations             DROP CONSTRAINT IF EXISTS fk_quotations_pdf;
ALTER TABLE sales_quotations             DROP CONSTRAINT IF EXISTS fk_quotations_prepared_by;
ALTER TABLE sales_quotations             DROP CONSTRAINT IF EXISTS fk_quotations_sent_by;
ALTER TABLE sales_quotation_lines        DROP CONSTRAINT IF EXISTS fk_quotation_lines_quote;
ALTER TABLE sales_quotation_lines        DROP CONSTRAINT IF EXISTS fk_quotation_lines_line;
ALTER TABLE sales_job_notes              DROP CONSTRAINT IF EXISTS fk_job_notes_job_card;
ALTER TABLE sales_job_notes              DROP CONSTRAINT IF EXISTS fk_job_notes_job_line;
ALTER TABLE sales_job_notes              DROP CONSTRAINT IF EXISTS fk_job_notes_author;
ALTER TABLE sales_job_attachments        DROP CONSTRAINT IF EXISTS fk_job_attachments_card;
ALTER TABLE sales_job_attachments        DROP CONSTRAINT IF EXISTS fk_job_attachments_line;
ALTER TABLE sales_job_attachments        DROP CONSTRAINT IF EXISTS fk_job_attachments_doc;
ALTER TABLE sales_job_attachments        DROP CONSTRAINT IF EXISTS fk_job_attachments_by;

DROP INDEX IF EXISTS idx_employee_documents_employee;
DROP INDEX IF EXISTS idx_employee_documents_document;

DROP TABLE IF EXISTS core_audit_logs;
"""


class Migration(migrations.Migration):
    """Depends on the last initial migration of all five apps."""

    dependencies = [
        ("core", "0002_initial"),
        ("identity", "0001_initial"),
        ("hr", "0001_initial"),
        ("pipeline", "0002_initial"),
        ("sales", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=FORWARD, reverse_sql=REVERSE),
    ]
