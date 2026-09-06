-- =============================================================================
-- SR Switchgear ERP — Schema v2
-- Modules: 1 (HR, identity, RBAC)  +  2 (Sales enquiry, quotation, job pipeline)
-- Engine: PostgreSQL 14+
-- Migration: 001_init_modules_1_and_2  (UP)
-- =============================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS citext;

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS hr;
CREATE SCHEMA IF NOT EXISTS auth;
CREATE SCHEMA IF NOT EXISTS sales;
CREATE SCHEMA IF NOT EXISTS pipeline;

COMMENT ON SCHEMA core     IS 'Shared reference data, documents, numbering, audit';
COMMENT ON SCHEMA hr       IS 'Employee master (Module 1)';
COMMENT ON SCHEMA auth     IS 'Login accounts, roles, permissions (Module 1)';
COMMENT ON SCHEMA sales    IS 'Clients, job cards, quotations (Module 2)';
COMMENT ON SCHEMA pipeline IS 'Stage definitions and transition history (Module 2, shared by all future modules)';


-- -----------------------------------------------------------------------------
-- Shared trigger: maintain updated_at
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION core.set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at := NOW();
  RETURN NEW;
END;
$$;


-- =============================================================================
-- CORE
-- =============================================================================

-- Purpose: organisational units. Self-referencing for sub-departments.
CREATE TABLE core.departments (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code                  CITEXT NOT NULL,
  name                  TEXT   NOT NULL,
  parent_department_id  UUID,
  is_active             BOOLEAN NOT NULL DEFAULT TRUE,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at            TIMESTAMPTZ,
  CONSTRAINT uk_departments_code       UNIQUE (code),
  CONSTRAINT fk_departments_parent     FOREIGN KEY (parent_department_id)
                                       REFERENCES core.departments(id) ON DELETE RESTRICT,
  CONSTRAINT ck_departments_not_self   CHECK (parent_department_id IS DISTINCT FROM id)
);

-- Purpose: job titles, kept separate from department so titles can be reused.
CREATE TABLE core.designations (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code        CITEXT NOT NULL,
  name        TEXT   NOT NULL,
  is_active   BOOLEAN NOT NULL DEFAULT TRUE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at  TIMESTAMPTZ,
  CONSTRAINT uk_designations_code UNIQUE (code)
);

-- Purpose: metadata for every uploaded file. Bytes live in object storage,
-- referenced by storage_key. Never store the file itself here.
CREATE TABLE core.documents (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  storage_key        TEXT NOT NULL,
  original_filename  TEXT NOT NULL,
  mime_type          TEXT NOT NULL,
  byte_size          BIGINT NOT NULL,
  sha256             CHAR(64),
  uploaded_by        UUID NOT NULL,
  uploaded_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at         TIMESTAMPTZ,
  CONSTRAINT uk_documents_storage_key UNIQUE (storage_key),
  CONSTRAINT ck_documents_byte_size   CHECK (byte_size > 0),
  CONSTRAINT ck_documents_sha256      CHECK (sha256 IS NULL OR sha256 ~ '^[0-9a-f]{64}$')
);

-- Purpose: business-facing number counters, one row per prefix.
-- Separate from every surrogate primary key. Incremented under row lock.
CREATE TABLE core.number_series (
  prefix      TEXT PRIMARY KEY,
  current     BIGINT NOT NULL DEFAULT 0,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT ck_number_series_current CHECK (current >= 0)
);

-- Purpose: append-only change history. Partitioned monthly for retention.
-- No updated_at / deleted_at by design: rows are never modified or removed.
CREATE TABLE core.audit_logs (
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

CREATE TABLE core.audit_logs_2026_q3 PARTITION OF core.audit_logs
  FOR VALUES FROM ('2026-07-01') TO ('2026-10-01');
CREATE TABLE core.audit_logs_2026_q4 PARTITION OF core.audit_logs
  FOR VALUES FROM ('2026-10-01') TO ('2027-01-01');


-- =============================================================================
-- AUTH  (created before hr.employees because documents.uploaded_by needs it)
-- =============================================================================

-- Purpose: login credentials. Optional per employee — floor staff may have none.
CREATE TABLE auth.user_accounts (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  employee_id           UUID NOT NULL,
  username              CITEXT NOT NULL,
  password_hash         TEXT NOT NULL,
  is_active             BOOLEAN NOT NULL DEFAULT TRUE,
  must_change_password  BOOLEAN NOT NULL DEFAULT TRUE,
  password_changed_at   TIMESTAMPTZ,
  failed_login_count    SMALLINT NOT NULL DEFAULT 0,
  locked_until          TIMESTAMPTZ,
  last_login_at         TIMESTAMPTZ,
  created_by            UUID,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at            TIMESTAMPTZ,
  CONSTRAINT uk_user_accounts_username    UNIQUE (username),
  CONSTRAINT uk_user_accounts_employee    UNIQUE (employee_id),
  CONSTRAINT fk_user_accounts_created_by  FOREIGN KEY (created_by)
                                          REFERENCES auth.user_accounts(id) ON DELETE SET NULL,
  CONSTRAINT ck_user_accounts_username    CHECK (length(username) BETWEEN 3 AND 64),
  CONSTRAINT ck_user_accounts_failed      CHECK (failed_login_count >= 0)
);

-- Purpose: issued refresh sessions, so logout and forced revocation are possible.
CREATE TABLE auth.sessions (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             UUID NOT NULL,
  refresh_token_hash  TEXT NOT NULL,
  issued_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at          TIMESTAMPTZ NOT NULL,
  revoked_at          TIMESTAMPTZ,
  ip_address          INET,
  user_agent          TEXT,
  CONSTRAINT uk_sessions_token   UNIQUE (refresh_token_hash),
  CONSTRAINT fk_sessions_user    FOREIGN KEY (user_id)
                                 REFERENCES auth.user_accounts(id) ON DELETE CASCADE,
  CONSTRAINT ck_sessions_expiry  CHECK (expires_at > issued_at)
);

-- Purpose: coarse-grained roles. Keep the count low; express exceptions
-- through role_permissions, not by minting new roles.
CREATE TABLE auth.roles (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code        CITEXT NOT NULL,
  name        TEXT   NOT NULL,
  is_system   BOOLEAN NOT NULL DEFAULT FALSE,
  is_active   BOOLEAN NOT NULL DEFAULT TRUE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uk_roles_code UNIQUE (code)
);

-- Purpose: atomic (resource, action) capabilities, e.g. ('quotation','approve').
CREATE TABLE auth.permissions (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  resource     TEXT NOT NULL,
  action       TEXT NOT NULL,
  description  TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uk_permissions_resource_action UNIQUE (resource, action),
  CONSTRAINT ck_permissions_action CHECK (
    action IN ('view','create','edit','delete','submit','cancel','approve',
               'release','export','print','share')
  )
);

CREATE TABLE auth.user_roles (
  user_id      UUID NOT NULL,
  role_id      UUID NOT NULL,
  assigned_by  UUID,
  assigned_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT pk_user_roles           PRIMARY KEY (user_id, role_id),
  CONSTRAINT fk_user_roles_user      FOREIGN KEY (user_id)
                                     REFERENCES auth.user_accounts(id) ON DELETE CASCADE,
  CONSTRAINT fk_user_roles_role      FOREIGN KEY (role_id)
                                     REFERENCES auth.roles(id) ON DELETE RESTRICT,
  CONSTRAINT fk_user_roles_assigner  FOREIGN KEY (assigned_by)
                                     REFERENCES auth.user_accounts(id) ON DELETE SET NULL
);

-- if_owner   : permission applies only to rows the user owns (self-service password)
-- perm_level : 0 = normal fields, 1+ = protected fields (photo, name, salary band)
CREATE TABLE auth.role_permissions (
  role_id        UUID NOT NULL,
  permission_id  UUID NOT NULL,
  perm_level     SMALLINT NOT NULL DEFAULT 0,
  if_owner       BOOLEAN NOT NULL DEFAULT FALSE,
  CONSTRAINT pk_role_permissions       PRIMARY KEY (role_id, permission_id, perm_level),
  CONSTRAINT fk_role_permissions_role  FOREIGN KEY (role_id)
                                       REFERENCES auth.roles(id) ON DELETE CASCADE,
  CONSTRAINT fk_role_permissions_perm  FOREIGN KEY (permission_id)
                                       REFERENCES auth.permissions(id) ON DELETE CASCADE,
  CONSTRAINT ck_role_permissions_level CHECK (perm_level BETWEEN 0 AND 9)
);


-- =============================================================================
-- HR
-- =============================================================================

-- Purpose: employee master. Three identities are deliberately separate:
--   id            -> surrogate key, used by every FK
--   employee_code -> human/paper-facing code, system-issued from
--                     core.number_series (SRS-001, SRS-002, ...) — never
--                     free text, see apps.core.numbering.next_employee_code
--   user_account  -> optional login, in auth.user_accounts
CREATE TABLE hr.employees (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  employee_code      CITEXT NOT NULL,
  full_name          TEXT   NOT NULL,
  department_id      UUID   NOT NULL,
  designation_id     UUID,
  reports_to_id      UUID,
  photo_document_id  UUID,
  date_of_joining    DATE   NOT NULL,
  date_of_exit       DATE,
  employment_status  TEXT   NOT NULL DEFAULT 'active',
  personal_phone     TEXT,
  personal_email     CITEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at         TIMESTAMPTZ,
  CONSTRAINT uk_employees_code        UNIQUE (employee_code),
  CONSTRAINT fk_employees_department  FOREIGN KEY (department_id)
                                      REFERENCES core.departments(id) ON DELETE RESTRICT,
  CONSTRAINT fk_employees_designation FOREIGN KEY (designation_id)
                                      REFERENCES core.designations(id) ON DELETE RESTRICT,
  CONSTRAINT fk_employees_reports_to  FOREIGN KEY (reports_to_id)
                                      REFERENCES hr.employees(id) ON DELETE SET NULL,
  CONSTRAINT fk_employees_photo       FOREIGN KEY (photo_document_id)
                                      REFERENCES core.documents(id) ON DELETE SET NULL,
  CONSTRAINT ck_employees_status      CHECK (employment_status IN
                                      ('active','on_notice','exited','suspended')),
  CONSTRAINT ck_employees_exit_date   CHECK (date_of_exit IS NULL
                                      OR date_of_exit >= date_of_joining),
  CONSTRAINT ck_employees_not_self    CHECK (reports_to_id IS DISTINCT FROM id),
  CONSTRAINT ck_employees_email       CHECK (personal_email IS NULL
                                      OR personal_email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$')
);

ALTER TABLE auth.user_accounts
  ADD CONSTRAINT fk_user_accounts_employee FOREIGN KEY (employee_id)
      REFERENCES hr.employees(id) ON DELETE RESTRICT;

ALTER TABLE core.documents
  ADD CONSTRAINT fk_documents_uploaded_by FOREIGN KEY (uploaded_by)
      REFERENCES auth.user_accounts(id) ON DELETE RESTRICT;

-- Purpose: personal ID documents (Aadhaar, PAN, certificates).
-- is_sensitive drives stricter access checks in the application layer.
CREATE TABLE hr.employee_documents (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  employee_id   UUID NOT NULL,
  document_id   UUID NOT NULL,
  doc_type      TEXT NOT NULL,
  is_sensitive  BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at    TIMESTAMPTZ,
  CONSTRAINT uk_employee_documents      UNIQUE (employee_id, doc_type, document_id),
  CONSTRAINT fk_employee_documents_emp  FOREIGN KEY (employee_id)
                                        REFERENCES hr.employees(id) ON DELETE CASCADE,
  CONSTRAINT fk_employee_documents_doc  FOREIGN KEY (document_id)
                                        REFERENCES core.documents(id) ON DELETE RESTRICT,
  CONSTRAINT ck_employee_documents_type CHECK (doc_type IN
                                        ('id_proof','address_proof','qualification',
                                         'appointment_letter','other'))
);


-- =============================================================================
-- PIPELINE  (stage graph — shared by Module 2 and every future module)
-- =============================================================================

-- Purpose: one row per stage. Adding a department to the pipeline is an INSERT,
-- never a schema migration. This is why status is not an ENUM.
CREATE TABLE pipeline.stages (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code           CITEXT NOT NULL,
  name           TEXT   NOT NULL,
  module_code    TEXT   NOT NULL,
  sequence_no    INTEGER NOT NULL,
  department_id  UUID,
  is_initial     BOOLEAN NOT NULL DEFAULT FALSE,
  is_terminal    BOOLEAN NOT NULL DEFAULT FALSE,
  is_active      BOOLEAN NOT NULL DEFAULT TRUE,
  -- Hours after a line enters this stage before it stops appearing on
  -- GET /api/v1/board. NULL (every stage but CANCELLED) means never hidden.
  -- Nothing is deleted -- this only affects the board query (pipeline
  -- migration 0007).
  board_hide_after_hours SMALLINT,
  -- When every active line on a card reaches a stage sharing this value,
  -- sales.job_cards.lifecycle_status is set to match (apps.sales.signals).
  -- A plain string, not an FK/enum -- pipeline stays ignorant of sales
  -- (pipeline migration 0008). NULL means no card-level outcome.
  cascades_job_card_status TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uk_stages_code       UNIQUE (code),
  CONSTRAINT uk_stages_sequence   UNIQUE (module_code, sequence_no),
  CONSTRAINT fk_stages_department FOREIGN KEY (department_id)
                                  REFERENCES core.departments(id) ON DELETE RESTRICT,
  CONSTRAINT ck_stages_sequence   CHECK (sequence_no > 0),
  CONSTRAINT ck_stages_endpoints  CHECK (NOT (is_initial AND is_terminal)),
  CONSTRAINT ck_stages_cascade_status CHECK (cascades_job_card_status IS NULL
                                OR cascades_job_card_status IN ('won','lost','cancelled'))
);

-- Purpose: the allowed edges of the stage graph, with authority attached.
-- allow_self_approval = FALSE enforces two-person rule on a gate.
-- Backward edges (rework, rejection) are just rules pointing at a lower stage.
CREATE TABLE pipeline.transition_rules (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  from_stage_id        UUID NOT NULL,
  action_code          TEXT NOT NULL,
  to_stage_id          UUID NOT NULL,
  allowed_role_id      UUID NOT NULL,
  allow_self_approval  BOOLEAN NOT NULL DEFAULT TRUE,
  requires_note        BOOLEAN NOT NULL DEFAULT FALSE,
  condition_expr       TEXT,
  is_active            BOOLEAN NOT NULL DEFAULT TRUE,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uk_transition_rules       UNIQUE (from_stage_id, action_code, allowed_role_id),
  CONSTRAINT fk_transition_rules_from  FOREIGN KEY (from_stage_id)
                                       REFERENCES pipeline.stages(id) ON DELETE RESTRICT,
  CONSTRAINT fk_transition_rules_to    FOREIGN KEY (to_stage_id)
                                       REFERENCES pipeline.stages(id) ON DELETE RESTRICT,
  CONSTRAINT fk_transition_rules_role  FOREIGN KEY (allowed_role_id)
                                       REFERENCES auth.roles(id) ON DELETE RESTRICT,
  CONSTRAINT ck_transition_rules_loop  CHECK (from_stage_id <> to_stage_id)
);


-- =============================================================================
-- SALES
-- =============================================================================

CREATE TABLE sales.clients (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_code    CITEXT NOT NULL,
  legal_name     TEXT   NOT NULL,
  gstin          CHAR(15),
  billing_city   TEXT,
  billing_state  TEXT,
  -- Commercial default: may this client's orders ship in parts?
  -- Copied onto each new job card, which may override it per order.
  default_dispatch_policy TEXT NOT NULL DEFAULT 'partial_allowed',
  is_active      BOOLEAN NOT NULL DEFAULT TRUE,
  created_by     UUID,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at     TIMESTAMPTZ,
  CONSTRAINT uk_clients_code    UNIQUE (client_code),
  CONSTRAINT uk_clients_gstin   UNIQUE (gstin),
  CONSTRAINT fk_clients_creator FOREIGN KEY (created_by)
                                REFERENCES auth.user_accounts(id) ON DELETE SET NULL,
  CONSTRAINT ck_clients_dispatch CHECK (default_dispatch_policy IN
                                ('partial_allowed','complete_only')),
  CONSTRAINT ck_clients_gstin   CHECK (gstin IS NULL
                                OR gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3}$')
);

CREATE TABLE sales.client_contacts (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id     UUID NOT NULL,
  contact_name  TEXT NOT NULL,
  phone         TEXT,
  email         CITEXT,
  is_primary    BOOLEAN NOT NULL DEFAULT FALSE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at    TIMESTAMPTZ,
  CONSTRAINT fk_client_contacts_client FOREIGN KEY (client_id)
                                       REFERENCES sales.clients(id) ON DELETE CASCADE,
  CONSTRAINT ck_client_contacts_reach  CHECK (phone IS NOT NULL OR email IS NOT NULL)
);

-- Purpose: distinguishes manufactured panels from traded goods.
-- is_manufactured = FALSE lets a job line skip design and production stages.
CREATE TABLE sales.product_categories (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code             CITEXT NOT NULL,
  name             TEXT   NOT NULL,
  is_manufactured  BOOLEAN NOT NULL DEFAULT TRUE,
  is_active        BOOLEAN NOT NULL DEFAULT TRUE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uk_product_categories_code UNIQUE (code)
);

-- Purpose: the commercial container — one client enquiry.
-- Note: no current_stage_id here. Stage lives on job_lines.
CREATE TABLE sales.job_cards (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_no             TEXT NOT NULL,
  client_id          UUID NOT NULL,
  client_contact_id  UUID,
  owner_user_id      UUID NOT NULL,
  lifecycle_status   TEXT NOT NULL DEFAULT 'open',
  enquiry_source     TEXT NOT NULL DEFAULT 'other',
  -- Per-order commercial term. Seeded from the client default at creation,
  -- overridable, and change-tracked by the audit trigger on this table.
  -- 'partial_allowed' lets a finished job line dispatch before its siblings;
  -- 'complete_only' holds every line until all of them are ready.
  dispatch_policy    TEXT NOT NULL DEFAULT 'partial_allowed',
  enquiry_date       DATE NOT NULL DEFAULT CURRENT_DATE,
  required_by        DATE,
  requirements       JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at         TIMESTAMPTZ,
  CONSTRAINT uk_job_cards_job_no     UNIQUE (job_no),
  CONSTRAINT fk_job_cards_client     FOREIGN KEY (client_id)
                                     REFERENCES sales.clients(id) ON DELETE RESTRICT,
  CONSTRAINT fk_job_cards_contact    FOREIGN KEY (client_contact_id)
                                     REFERENCES sales.client_contacts(id) ON DELETE SET NULL,
  CONSTRAINT fk_job_cards_owner      FOREIGN KEY (owner_user_id)
                                     REFERENCES auth.user_accounts(id) ON DELETE RESTRICT,
  CONSTRAINT ck_job_cards_lifecycle  CHECK (lifecycle_status IN
                                     ('open','quoted','rework','won','lost','cancelled')),
  CONSTRAINT ck_job_cards_dispatch   CHECK (dispatch_policy IN
                                     ('partial_allowed','complete_only')),
  CONSTRAINT ck_job_cards_source     CHECK (enquiry_source IN
                                     ('indiamart','website','phone','referral','walk_in','other')),
  CONSTRAINT ck_job_cards_required   CHECK (required_by IS NULL OR required_by >= enquiry_date)
);

-- Purpose: the unit that actually travels the pipeline.
-- One enquiry for 3 ATS panels + 2 AMF panels = one job_card, two job_lines,
-- each moving through stages independently.
CREATE TABLE sales.job_lines (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_card_id          UUID NOT NULL,
  line_no              SMALLINT NOT NULL,
  product_category_id  UUID NOT NULL,
  description          TEXT NOT NULL,
  quantity             INTEGER NOT NULL DEFAULT 1,
  current_stage_id     UUID NOT NULL,
  line_status          TEXT NOT NULL DEFAULT 'active',
  required_by          DATE,
  specs                JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at           TIMESTAMPTZ,
  CONSTRAINT uk_job_lines_line_no    UNIQUE (job_card_id, line_no),
  CONSTRAINT fk_job_lines_job_card   FOREIGN KEY (job_card_id)
                                     REFERENCES sales.job_cards(id) ON DELETE CASCADE,
  CONSTRAINT fk_job_lines_category   FOREIGN KEY (product_category_id)
                                     REFERENCES sales.product_categories(id) ON DELETE RESTRICT,
  CONSTRAINT fk_job_lines_stage      FOREIGN KEY (current_stage_id)
                                     REFERENCES pipeline.stages(id) ON DELETE RESTRICT,
  CONSTRAINT ck_job_lines_quantity   CHECK (quantity > 0),
  CONSTRAINT ck_job_lines_status     CHECK (line_status IN
                                     ('active','on_hold','completed','cancelled'))
);

-- Purpose: append-only stage history. The source of truth for
-- job_lines.current_stage_id, which is a denormalised cache of the latest row.
CREATE TABLE pipeline.job_line_transitions (
  id             BIGSERIAL PRIMARY KEY,
  job_line_id    UUID NOT NULL,
  from_stage_id  UUID,
  to_stage_id    UUID NOT NULL,
  action_code    TEXT NOT NULL,
  performed_by   UUID NOT NULL,
  performed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  note           TEXT,
  CONSTRAINT fk_job_line_transitions_line  FOREIGN KEY (job_line_id)
                                           REFERENCES sales.job_lines(id) ON DELETE CASCADE,
  CONSTRAINT fk_job_line_transitions_from  FOREIGN KEY (from_stage_id)
                                           REFERENCES pipeline.stages(id) ON DELETE RESTRICT,
  CONSTRAINT fk_job_line_transitions_to    FOREIGN KEY (to_stage_id)
                                           REFERENCES pipeline.stages(id) ON DELETE RESTRICT,
  CONSTRAINT fk_job_line_transitions_by    FOREIGN KEY (performed_by)
                                           REFERENCES auth.user_accounts(id) ON DELETE RESTRICT
);

-- Purpose: quotation header. The priced PDF is produced by external software;
-- only the file and its commercial summary are stored here.
-- Revision model: linear chain. revision_no increments; supersedes_id points
-- at the row this one replaces. Exactly one 'active' revision per job card.
-- No activate/send/accept workflow: a revision is 'draft' (current) or
-- 'superseded' (a later one replaced it). ACCT's PDF upload is itself the
-- whole action; Sales downloads and sends it to the client outside this
-- system (sales migration 0002 removed the D7 status machine that used to
-- track that in-app).
CREATE TABLE sales.quotations (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  quotation_no     TEXT NOT NULL,
  job_card_id      UUID NOT NULL,
  revision_no      SMALLINT NOT NULL DEFAULT 0,
  supersedes_id    UUID,
  status           TEXT NOT NULL DEFAULT 'draft',
  quoted_amount    NUMERIC(14,2),
  currency         CHAR(3) NOT NULL DEFAULT 'INR',
  valid_till       DATE,
  pdf_document_id  UUID,
  prepared_by      UUID NOT NULL,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uk_quotations_no          UNIQUE (quotation_no),
  CONSTRAINT uk_quotations_revision    UNIQUE (job_card_id, revision_no),
  CONSTRAINT uk_quotations_supersedes  UNIQUE (supersedes_id),
  CONSTRAINT fk_quotations_job_card    FOREIGN KEY (job_card_id)
                                       REFERENCES sales.job_cards(id) ON DELETE RESTRICT,
  CONSTRAINT fk_quotations_supersedes  FOREIGN KEY (supersedes_id)
                                       REFERENCES sales.quotations(id) ON DELETE RESTRICT,
  CONSTRAINT fk_quotations_pdf         FOREIGN KEY (pdf_document_id)
                                       REFERENCES core.documents(id) ON DELETE RESTRICT,
  CONSTRAINT fk_quotations_prepared_by FOREIGN KEY (prepared_by)
                                       REFERENCES auth.user_accounts(id) ON DELETE RESTRICT,
  CONSTRAINT ck_quotations_status      CHECK (status IN ('draft','superseded')),
  CONSTRAINT ck_quotations_revision    CHECK (revision_no >= 0),
  CONSTRAINT ck_quotations_amount      CHECK (quoted_amount IS NULL OR quoted_amount >= 0)
);

-- Purpose: which job lines a given quotation revision covers.
CREATE TABLE sales.quotation_lines (
  quotation_id  UUID NOT NULL,
  job_line_id   UUID NOT NULL,
  line_amount   NUMERIC(14,2),
  CONSTRAINT pk_quotation_lines       PRIMARY KEY (quotation_id, job_line_id),
  CONSTRAINT fk_quotation_lines_quote FOREIGN KEY (quotation_id)
                                      REFERENCES sales.quotations(id) ON DELETE CASCADE,
  CONSTRAINT fk_quotation_lines_line  FOREIGN KEY (job_line_id)
                                      REFERENCES sales.job_lines(id) ON DELETE RESTRICT,
  CONSTRAINT ck_quotation_lines_amt   CHECK (line_amount IS NULL OR line_amount >= 0)
);

-- Purpose: free-text collaboration thread on a job card or a specific line.
CREATE TABLE sales.job_notes (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_card_id     UUID NOT NULL,
  job_line_id     UUID,
  author_user_id  UUID NOT NULL,
  body            TEXT NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT fk_job_notes_job_card FOREIGN KEY (job_card_id)
                                   REFERENCES sales.job_cards(id) ON DELETE CASCADE,
  CONSTRAINT fk_job_notes_job_line FOREIGN KEY (job_line_id)
                                   REFERENCES sales.job_lines(id) ON DELETE CASCADE,
  CONSTRAINT fk_job_notes_author   FOREIGN KEY (author_user_id)
                                   REFERENCES auth.user_accounts(id) ON DELETE RESTRICT,
  CONSTRAINT ck_job_notes_body     CHECK (length(btrim(body)) > 0)
);

-- Purpose: any file attached to a job card (client drawings, site photos, POs).
CREATE TABLE sales.job_attachments (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_card_id  UUID NOT NULL,
  job_line_id  UUID,
  document_id  UUID NOT NULL,
  label        TEXT,
  attached_by  UUID NOT NULL,
  attached_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uk_job_attachments        UNIQUE (job_card_id, document_id),
  CONSTRAINT fk_job_attachments_card   FOREIGN KEY (job_card_id)
                                       REFERENCES sales.job_cards(id) ON DELETE CASCADE,
  CONSTRAINT fk_job_attachments_line   FOREIGN KEY (job_line_id)
                                       REFERENCES sales.job_lines(id) ON DELETE CASCADE,
  CONSTRAINT fk_job_attachments_doc    FOREIGN KEY (document_id)
                                       REFERENCES core.documents(id) ON DELETE RESTRICT,
  CONSTRAINT fk_job_attachments_by     FOREIGN KEY (attached_by)
                                       REFERENCES auth.user_accounts(id) ON DELETE RESTRICT
);


-- =============================================================================
-- INDEXES
-- Structural only: every FK, plus partial uniques that enforce business rules.
-- Workload-specific composite indexes are deliberately deferred until there is
-- a measured query baseline.
-- =============================================================================

-- Foreign key indexes (Postgres does not create these automatically)
CREATE INDEX idx_departments_parent          ON core.departments(parent_department_id);
CREATE INDEX idx_documents_uploaded_by       ON core.documents(uploaded_by);
CREATE INDEX idx_employees_department        ON hr.employees(department_id);
CREATE INDEX idx_employees_designation       ON hr.employees(designation_id);
CREATE INDEX idx_employees_reports_to        ON hr.employees(reports_to_id);
CREATE INDEX idx_employee_documents_employee ON hr.employee_documents(employee_id);
CREATE INDEX idx_employee_documents_document ON hr.employee_documents(document_id);
CREATE INDEX idx_sessions_user               ON auth.sessions(user_id);
CREATE INDEX idx_user_roles_role             ON auth.user_roles(role_id);
CREATE INDEX idx_role_permissions_perm       ON auth.role_permissions(permission_id);
CREATE INDEX idx_stages_department           ON pipeline.stages(department_id);
CREATE INDEX idx_transition_rules_from       ON pipeline.transition_rules(from_stage_id);
CREATE INDEX idx_transition_rules_to         ON pipeline.transition_rules(to_stage_id);
CREATE INDEX idx_transition_rules_role       ON pipeline.transition_rules(allowed_role_id);
CREATE INDEX idx_client_contacts_client      ON sales.client_contacts(client_id);
CREATE INDEX idx_job_cards_client            ON sales.job_cards(client_id);
CREATE INDEX idx_job_cards_owner             ON sales.job_cards(owner_user_id);
CREATE INDEX idx_job_lines_job_card          ON sales.job_lines(job_card_id);
CREATE INDEX idx_job_lines_category          ON sales.job_lines(product_category_id);
CREATE INDEX idx_job_lines_current_stage     ON sales.job_lines(current_stage_id);
CREATE INDEX idx_job_line_transitions_line   ON pipeline.job_line_transitions(job_line_id, performed_at DESC);
CREATE INDEX idx_quotations_job_card         ON sales.quotations(job_card_id);
CREATE INDEX idx_quotation_lines_line        ON sales.quotation_lines(job_line_id);
CREATE INDEX idx_job_notes_job_card          ON sales.job_notes(job_card_id, created_at DESC);
CREATE INDEX idx_job_attachments_card        ON sales.job_attachments(job_card_id);

-- Business rules that are cheaper to enforce as partial unique indexes
CREATE UNIQUE INDEX uk_client_contacts_primary
  ON sales.client_contacts(client_id)
  WHERE is_primary AND deleted_at IS NULL;

CREATE UNIQUE INDEX uk_quotations_one_active
  ON sales.quotations(job_card_id)
  WHERE status = 'active';

CREATE UNIQUE INDEX uk_stages_one_initial
  ON pipeline.stages(module_code)
  WHERE is_initial AND is_active;

-- Soft-delete-aware lookups on the two highest-traffic masters
CREATE INDEX idx_employees_active
  ON hr.employees(department_id)
  WHERE deleted_at IS NULL AND employment_status = 'active';

CREATE INDEX idx_job_cards_open
  ON sales.job_cards(owner_user_id, enquiry_date DESC)
  WHERE deleted_at IS NULL AND lifecycle_status IN ('open','quoted','rework');

-- Audit log retrieval by record
CREATE INDEX idx_audit_logs_record
  ON core.audit_logs(table_schema, table_name, record_id, occurred_at DESC);


-- =============================================================================
-- TRIGGERS
-- =============================================================================

CREATE TRIGGER trg_departments_updated       BEFORE UPDATE ON core.departments       FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
CREATE TRIGGER trg_designations_updated      BEFORE UPDATE ON core.designations      FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
CREATE TRIGGER trg_user_accounts_updated     BEFORE UPDATE ON auth.user_accounts     FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
CREATE TRIGGER trg_roles_updated             BEFORE UPDATE ON auth.roles             FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
CREATE TRIGGER trg_employees_updated         BEFORE UPDATE ON hr.employees           FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
CREATE TRIGGER trg_stages_updated            BEFORE UPDATE ON pipeline.stages        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
CREATE TRIGGER trg_transition_rules_updated  BEFORE UPDATE ON pipeline.transition_rules FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
CREATE TRIGGER trg_clients_updated           BEFORE UPDATE ON sales.clients          FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
CREATE TRIGGER trg_client_contacts_updated   BEFORE UPDATE ON sales.client_contacts  FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
CREATE TRIGGER trg_product_categories_updated BEFORE UPDATE ON sales.product_categories FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
CREATE TRIGGER trg_job_cards_updated         BEFORE UPDATE ON sales.job_cards        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
CREATE TRIGGER trg_job_lines_updated         BEFORE UPDATE ON sales.job_lines        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
CREATE TRIGGER trg_quotations_updated        BEFORE UPDATE ON sales.quotations       FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();


-- Purpose: keep job_lines.current_stage_id in lockstep with the transition log.
-- Without this, the denormalised pointer and the history can diverge.
CREATE OR REPLACE FUNCTION pipeline.apply_transition()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
  actual_stage UUID;
BEGIN
  SELECT current_stage_id INTO actual_stage
  FROM sales.job_lines WHERE id = NEW.job_line_id FOR UPDATE;

  IF NEW.from_stage_id IS DISTINCT FROM actual_stage THEN
    RAISE EXCEPTION 'Stale transition: line is at % but transition claims %',
      actual_stage, NEW.from_stage_id;
  END IF;

  UPDATE sales.job_lines
     SET current_stage_id = NEW.to_stage_id
   WHERE id = NEW.job_line_id;

  RETURN NEW;
END;
$$;

CREATE TRIGGER trg_apply_transition
  AFTER INSERT ON pipeline.job_line_transitions
  FOR EACH ROW EXECUTE FUNCTION pipeline.apply_transition();


-- Purpose: generic audit capture. Attach to any table that needs history.
CREATE OR REPLACE FUNCTION core.record_audit()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  INSERT INTO core.audit_logs(table_schema, table_name, record_id, operation,
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

CREATE TRIGGER trg_audit_employees      AFTER INSERT OR UPDATE OR DELETE ON hr.employees          FOR EACH ROW EXECUTE FUNCTION core.record_audit();
CREATE TRIGGER trg_audit_user_accounts  AFTER INSERT OR UPDATE OR DELETE ON auth.user_accounts    FOR EACH ROW EXECUTE FUNCTION core.record_audit();
CREATE TRIGGER trg_audit_user_roles     AFTER INSERT OR UPDATE OR DELETE ON auth.user_roles       FOR EACH ROW EXECUTE FUNCTION core.record_audit();
CREATE TRIGGER trg_audit_role_perms     AFTER INSERT OR UPDATE OR DELETE ON auth.role_permissions FOR EACH ROW EXECUTE FUNCTION core.record_audit();
CREATE TRIGGER trg_audit_job_cards      AFTER INSERT OR UPDATE OR DELETE ON sales.job_cards       FOR EACH ROW EXECUTE FUNCTION core.record_audit();
CREATE TRIGGER trg_audit_job_lines      AFTER INSERT OR UPDATE OR DELETE ON sales.job_lines       FOR EACH ROW EXECUTE FUNCTION core.record_audit();
CREATE TRIGGER trg_audit_quotations     AFTER INSERT OR UPDATE OR DELETE ON sales.quotations      FOR EACH ROW EXECUTE FUNCTION core.record_audit();


-- =============================================================================
-- NUMBER GENERATION
-- =============================================================================

-- Purpose: issue the next business number for a prefix under a row lock.
-- Not gap-free: a rolled-back transaction leaves a gap. Acceptable for job
-- and quotation numbers; revisit if a tax rule ever demands gapless invoices.
CREATE OR REPLACE FUNCTION core.next_number(p_prefix TEXT, p_width INT DEFAULT 5)
RETURNS TEXT
LANGUAGE plpgsql
AS $$
DECLARE
  v_next BIGINT;
BEGIN
  INSERT INTO core.number_series(prefix, current)
  VALUES (p_prefix, 1)
  ON CONFLICT (prefix) DO UPDATE
    SET current = core.number_series.current + 1,
        updated_at = NOW()
  RETURNING current INTO v_next;

  RETURN p_prefix || lpad(v_next::text, p_width, '0');
END;
$$;

COMMIT;
