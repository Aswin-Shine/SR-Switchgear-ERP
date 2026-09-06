# DATABASE SCHEMA DESIGN — SR Switchgear ERP

**Database:** PostgreSQL 16
**Domain:** Custom ERP / EMS — Module 1 (HR, identity, RBAC) + Module 2 (Sales enquiry, quotation, job pipeline)
**Status:** v2.1 — reviewed and redesigned from v1, plus dispatch policy
**Validated:** full DDL executed against PostgreSQL 16.15; 12-case behavioural smoke test passed; 7-case dispatch policy test passed; rollback and re-apply verified

### Changes in v2.1

Confirmed with the business that a single enquiry does split into independently-tracked
items, and that whether an order may ship in parts is a **per-client commercial default,
overridable per order** — some clients accept partial shipment (which frees factory floor
space), others require the whole order together.

- `sales.clients.default_dispatch_policy` — `partial_allowed` | `complete_only`, default
  `partial_allowed`. Seeded onto each new job card at creation.
- `sales.job_cards.dispatch_policy` — same domain, overridable per order. Already covered
  by the audit trigger on `job_cards`, so a mid-order change is logged with actor and
  timestamp. This matters the first time there is a dispute over whether partial shipment
  was authorised.

Both are `TEXT` with `CHECK` constraints rather than free-text notes, because the dispatch
module needs to answer as a query: *which finished job lines am I permitted to ship right
now?* — job lines at a ready stage whose parent card is `partial_allowed`.

**Deferred to the dispatch module (Module 5/6), not built now:** the convergence gate. When
a card is `complete_only`, no line may enter Dispatch until every sibling line on that card
has reached ready. This is one conditional inside `perform_transition`, driven by the column
above. No schema change will be required to add it.

No index was added for the shippable-now query. The dispatch module does not exist yet and
there is no measured workload; revisit when it does.

---

## == REVIEW OF v1 ==

### Defects found in the previous design

| # | Defect | Severity | Fix in v2 |
|---|--------|----------|-----------|
| 1 | `job_card` was the unit that moved through stages. A single enquiry for 3 ATS panels + 2 AMF panels cannot move as one unit — they have different lead times and often ship separately. | **Critical** | New `sales.job_lines` table. Stage and transition history moved from the card to the line. |
| 2 | No path for traded goods. Every job was forced through design and production, contradicting the company's registered primary business. | **Critical** | New `sales.product_categories.is_manufactured`. A non-manufactured line takes a different edge out of the Quotation stage — a data change, not a code change. |
| 3 | `revision_no` *and* `supersedes_id` both present on quotations, with no rule making them agree. Two sources of truth for "which quotation is current". | High | Kept both but constrained: `UNIQUE (job_card_id, revision_no)`, `UNIQUE (supersedes_id)` making the chain strictly linear, and a partial unique index allowing exactly one `active` revision per job card. |
| 4 | `current_stage_id` was a denormalised cache with nothing keeping it in sync with the transition log. | High | `pipeline.apply_transition()` trigger. It takes a row lock, rejects any transition whose `from_stage_id` does not match the line's actual current stage, then advances the pointer. Lost-update and stale-write both impossible. |
| 5 | Status columns were free `text`. Any typo became a new, silent status. | Medium | `CHECK` constraints on every status/enum-like column. |
| 6 | No session or credential-lockout storage. Login was undesignable. | Medium | `auth.sessions` (revocable refresh tokens), plus `failed_login_count` / `locked_until` on the account. |
| 7 | No timestamps on several tables; no soft delete; no `updated_at` maintenance. | Medium | `created_at` / `updated_at` / `deleted_at` per policy below, with a shared `set_updated_at()` trigger. |
| 8 | No constraint names. Postgres would auto-generate them, making errors unreadable and migrations fragile. | Medium | Every constraint explicitly named `pk_` / `uk_` / `fk_` / `ck_` / `idx_`. |
| 9 | Quotation could reach `sent` status with no PDF attached. | Medium | `ck_quotations_pdf_needed` and `ck_quotations_sent`. |
| 10 | No attachment table for client drawings, site photos, or purchase orders — only the quotation PDF had a home. | Low | `sales.job_attachments`. |
| 11 | Audit log unpartitioned; would grow unbounded on a table that only ever receives inserts. | Low | `PARTITION BY RANGE (occurred_at)`, quarterly partitions. |
| 12 | Singular table names, inconsistent with the convention this review applies. | Low | All tables pluralised. |

### Where this design deliberately departs from the skill's stated best practices

The skill's checklist is written for a generic CRUD application. Four of its rules are wrong for this system, and following them would introduce defects:

**"Use ENUM for fixed sets of values."** Rejected. PostgreSQL native `ENUM` types require `ALTER TYPE` to add a value and are effectively impossible to remove values from. Two of this schema's most-changed columns are status-like, and the entire pipeline design depends on stages being *rows that non-developers can add*. Native enums would convert every new department into a schema migration — destroying the main architectural property. Used `CHECK` constraints for genuinely fixed sets (`operation`, `employment_status`) and lookup tables for anything the business will extend (`pipeline.stages`, `sales.product_categories`).

**"Cascade deletes where appropriate."** Applied narrowly, not by default. `ON DELETE CASCADE` is used only where the child is meaningless without the parent and carries no audit value: `job_lines` under `job_cards`, `sessions` under `user_accounts`, junction tables. Everything touching money, approval, or attribution uses `ON DELETE RESTRICT` — deleting a client should never silently erase the quotation history that proves what was promised.

**"Add appropriate indexes."** Split into two categories. Structural indexes (every foreign key, plus partial uniques that enforce business rules) are included, because they are correctness and constraint machinery, not speculative tuning. Workload-specific composite and covering indexes are **deliberately omitted** — there is no data, no query log, and no measured baseline, and inventing them now would violate the companion optimizer discipline of never optimising without a baseline. Revisit once `pg_stat_statements` has real traffic.

**"Add soft delete flags if needed"** — applied selectively, not universally. Masters and transactional records get `deleted_at`. `core.audit_logs`, `pipeline.job_line_transitions`, `sales.job_notes` and `sales.quotation_lines` deliberately do **not**: they are append-only history, and a "deleted" audit row is a contradiction.

### Resolved decision

`job_lines` was originally added without confirmation, on the balance of cost. **This has since been confirmed with the business:** items on a single enquiry do sit at different stages simultaneously — one panel type waiting on material while another is being wired — and partial dispatch does occur when the client permits it. The multi-line model is correct and is no longer provisional.

---

## == ENTITY RELATIONSHIP DIAGRAM ==

```
MODULE 1 — HR, identity, RBAC
=============================

+---------------------------+          +---------------------------+
|    core.departments       |          |    core.designations      |
+---------------------------+          +---------------------------+
| id (PK)                   |<--+      | id (PK)                   |
| code (UK)                 |   |      | code (UK)                 |
| name                      |   |      | name                      |
| parent_department_id (FK) +---+      +-------------+-------------+
| is_active                 |                        |
+-------------+-------------+                        |
              | 1:N                                  | 1:N
              |            +-------------------------+
              v            v
+---------------------------------------+
|            hr.employees               |
+---------------------------------------+          +---------------------------+
| id (PK)               <-- surrogate   |          |     core.documents        |
| employee_code (UK)    <-- paper code  |          +---------------------------+
| full_name                             |   1:1    | id (PK)                   |
| department_id (FK)                    +--------->| storage_key (UK)          |
| designation_id (FK)                   | photo    | mime_type / byte_size     |
| reports_to_id (FK, self)              |          | sha256                    |
| photo_document_id (FK)                |          | uploaded_by (FK)          |
| date_of_joining / date_of_exit        |          +-------------+-------------+
| employment_status (CHECK)             |                        ^ 1:N
| created_at / updated_at / deleted_at  |                        |
+------+-----------------------+--------+          +-------------+-------------+
       | 1:N                   | 1:0..1            |  hr.employee_documents    |
       |                       |                   +---------------------------+
       +---------------------->|                   | id (PK)                   |
                               |                   | employee_id (FK)          |
                               v                   | document_id (FK)          |
+---------------------------------------+          | doc_type (CHECK)          |
|        auth.user_accounts             |          | is_sensitive              |
+---------------------------------------+          +---------------------------+
| id (PK)                               |
| employee_id (FK, UK)  <-- 0..1 login  |          +---------------------------+
| username (UK)                         |   1:N    |      auth.sessions        |
| password_hash                         +--------->+---------------------------+
| must_change_password                  |          | id (PK)                   |
| failed_login_count / locked_until     |          | user_id (FK)              |
| last_login_at                         |          | refresh_token_hash (UK)   |
+------+--------------------------+-----+          | expires_at / revoked_at   |
       | 1:N                      | 1:N            +---------------------------+
       |                          |
       |                          v
       |            +---------------------------+
       |            |     core.audit_logs       |  (append-only, partitioned)
       |            +---------------------------+
       |            | id + occurred_at (PK)     |
       |            | table_schema / table_name |
       |            | record_id / operation     |
       |            | changed_by (FK)           |
       |            | old_data / new_data JSONB |
       |            +---------------------------+
       v
+---------------------------+  N:M   +---------------------------+
|     auth.user_roles       |<------>|        auth.roles         |
+---------------------------+        +---------------------------+
| user_id (PK, FK)          |        | id (PK)                   |
| role_id (PK, FK)          |        | code (UK)                 |
| assigned_by (FK)          |        | name / is_system          |
| assigned_at               |        +-------------+-------------+
+---------------------------+                      | 1:N
                                                   v
                              +--------------------------------------+
                              |       auth.role_permissions          |
                              +--------------------------------------+
                              | role_id (PK, FK)                     |
                              | permission_id (PK, FK)               |
                              | perm_level (PK)  <-- field tiers     |
                              | if_owner        <-- own-row only     |
                              +------------------+-------------------+
                                                 | N:M
                                                 v
                              +--------------------------------------+
                              |         auth.permissions             |
                              +--------------------------------------+
                              | id (PK)                              |
                              | resource + action (UK)               |
                              +--------------------------------------+


MODULE 2 — Sales enquiry, quotation, job pipeline
=================================================

+---------------------------+          +---------------------------+
|      sales.clients        |   1:N    |  sales.client_contacts    |
+---------------------------+--------->+---------------------------+
| id (PK)                   |          | id (PK)                   |
| client_code (UK)          |          | client_id (FK)            |
| legal_name                |          | contact_name              |
| gstin (UK, CHECK)         |          | is_primary  <-- 1 per client
| default_dispatch_policy   |          |
+-------------+-------------+          +-------------+-------------+
              | 1:N                                  | 0..1
              v                                      v
+-------------------------------------------------------------+
|                     sales.job_cards                         |
|              (commercial container, no stage)               |
+-------------------------------------------------------------+
| id (PK)                                                     |
| job_no (UK)          <-- from core.number_series            |
| client_id (FK) / client_contact_id (FK)                     |
| owner_user_id (FK)   <-- the sales rep; attribution lives   |
|                          here, NOT inside job_no            |
| lifecycle_status (CHECK: open|quoted|won|lost|cancelled)     |
| dispatch_policy (CHECK: partial_allowed|complete_only)       |
|     seeded from client default; gates partial shipment       |
| enquiry_source (CHECK: indiamart|website|phone|...)          |
| requirements JSONB                                          |
+---+---------------+------------------+----------------------+
    | 1:N           | 1:N              | 1:N
    |               |                  |
    |               v                  v
    |   +---------------------+  +---------------------------+
    |   |  sales.job_notes    |  |  sales.job_attachments    |
    |   +---------------------+  +---------------------------+
    |   | job_card_id (FK)    |  | job_card_id (FK)          |
    |   | job_line_id (FK)    |  | document_id (FK)          |
    |   | author_user_id (FK) |  | attached_by (FK)          |
    |   +---------------------+  +---------------------------+
    v
+-------------------------------------------------------------+
|                     sales.job_lines                         |
|          *** the unit that travels the pipeline ***         |
+-------------------------------------------------------------+          +--------------------------+
| id (PK)                                                     |   N:1    | sales.product_categories |
| job_card_id (FK)                                            +--------->+--------------------------+
| line_no          UK(job_card_id, line_no)                   |          | id (PK) / code (UK)      |
| product_category_id (FK)                                    |          | is_manufactured          |
| description / quantity / specs JSONB                        |          |   FALSE => skips design  |
| current_stage_id (FK)  <-- denormalised cache               |          |            and production|
| line_status (CHECK)                                         |          +--------------------------+
+------------------------+------------------------------------+
                         | 1:N (append-only)
                         v
+-------------------------------------------------------------+
|             pipeline.job_line_transitions                   |
|                 *** source of truth ***                     |
+-------------------------------------------------------------+
| id (PK, bigserial)                                          |
| job_line_id (FK)                                            |
| from_stage_id (FK) / to_stage_id (FK)                       |
| action_code / performed_by (FK) / performed_at / note       |
+------------------------+------------------------------------+
                         | N:1
                         v
+-------------------------------------------------------------+
|                    pipeline.stages                          |
|        add a department = INSERT a row, not a migration     |
+-------------------------------------------------------------+
| id (PK) / code (UK)                                         |
| module_code + sequence_no (UK)                              |
| department_id (FK -> core.departments)                      |
| is_initial (1 per module) / is_terminal / is_active         |
+------------------------+------------------------------------+
                         | 1:N
                         v
+-------------------------------------------------------------+
|                pipeline.transition_rules                    |
|                  the allowed edges + authority              |
+-------------------------------------------------------------+
| id (PK)                                                     |
| from_stage_id (FK) / action_code / to_stage_id (FK)         |
|   UK(from_stage_id, action_code, allowed_role_id)           |
| allowed_role_id (FK -> auth.roles)                          |
| allow_self_approval  <-- FALSE enforces two-person rule     |
| requires_note / condition_expr / is_active                  |
+-------------------------------------------------------------+
   NOTE: a backward edge (rework/rejection) is just a rule whose
   to_stage_id has a LOWER sequence_no. No special mechanism.


+-------------------------------------------------------------+
|                    sales.quotations                         |
+-------------------------------------------------------------+          +--------------------------+
| id (PK) / quotation_no (UK)                                 |   N:1    |     core.documents       |
| job_card_id (FK)                                            +--------->+--------------------------+
| revision_no      UK(job_card_id, revision_no)               |  the PDF | id (PK) / storage_key    |
| supersedes_id (FK, self, UK)  <-- strictly linear chain     |  produced| mime_type / byte_size    |
| status (CHECK)   partial UK: one 'active' per job_card      |  by the  +--------------------------+
| quoted_amount NUMERIC(14,2) / currency / valid_till         |  external
| pdf_document_id (FK)                                        |  quoting
| prepared_by (FK) / sent_by (FK) / sent_at                   |  software
+------------------------+------------------------------------+
                         | 1:N
                         v
+-------------------------------------------------------------+
|                 sales.quotation_lines                       |
|      which job lines this revision actually priced          |
+-------------------------------------------------------------+
| quotation_id (PK, FK) / job_line_id (PK, FK) / line_amount  |
+-------------------------------------------------------------+
```

---

## == TABLE DEFINITIONS, RELATIONSHIPS, INDEXES, MIGRATION SCRIPTS ==

Full DDL: **`sr_erp_schema_v2.sql`** (up migration, single transaction)
Rollback: **`sr_erp_schema_v2_rollback.sql`** (down migration)

Both were executed against PostgreSQL 16.15. The up migration applies cleanly, the rollback drops cleanly, and the up migration re-applies afterwards without error.

### Verification results

| Test | Expected | Result |
|------|----------|--------|
| Number generator issues sequential numbers | `JOB-2026-00001`, `JOB-2026-00002` | pass |
| Valid transition advances the line | line 1 → Quotation | pass |
| Stale transition (concurrent double-move) | rejected | pass — raised `Stale transition` |
| Lines on one card move independently | line 1 at Quotation, line 2 at Enquiry | pass |
| Backward transition (rework/rejection) | allowed | pass |
| Malformed GSTIN | rejected | pass — `ck_clients_gstin` |
| Two `active` quotations on one job | rejected | pass — `uk_quotations_one_active` |
| Duplicate `line_no` on one job card | rejected | pass — `uk_job_lines_line_no` |
| Employee reporting to self | rejected | pass — `ck_employees_not_self` |
| Two initial stages in one module | rejected | pass — `uk_stages_one_initial` |
| Audit triggers captured inserts and updates | rows in `core.audit_logs` | pass |
| Transition history retained after rework | both edges present | pass |
| Client dispatch policy defaults to `partial_allowed` | default applied | pass |
| Client set to `complete_only` | accepted | pass |
| Invalid client dispatch policy | rejected | pass — `ck_clients_dispatch` |
| Job card policy override | `complete_only` on a `partial_allowed` client | pass |
| Invalid job card dispatch policy | rejected | pass — `ck_job_cards_dispatch` |
| Mid-order policy change captured by audit | old and new values logged | pass |
| Shippable-now query returns only `partial_allowed` lines | correct rows | pass |

---

## == OPTIMIZATION NOTES ==

### Performance considerations

**Index strategy.** Structural indexes only at this stage: every foreign key column (PostgreSQL does not index these automatically, and unindexed FKs make parent deletes and joins scan), plus partial unique indexes that carry business rules. Two partial indexes are also tuned for the two queries that certainly exist — the per-rep open-jobs list and the active-employee-by-department lookup. Everything else waits for `pg_stat_statements` evidence.

**The pipeline board query** — "which stage is every job line at" — is a single indexed lookup on `job_lines.current_stage_id` rather than a window function over transition history. That is the entire reason the denormalised pointer exists, and the `apply_transition` trigger is the price paid to keep it honest.

**Partitioning.** `core.audit_logs` is range-partitioned on `occurred_at`, quarterly. This is the only table with unbounded insert-only growth. At 50–100 users the volume is modest, but partitioning costs nothing now and makes retention (`DROP TABLE audit_logs_2026_q3`) trivial later. Create partitions ahead of time or automate with `pg_partman`.

**Denormalisation opportunities.** None taken beyond `current_stage_id`. Deliberately resisted denormalising client name onto job cards, or quoted totals onto job cards — at this data volume the join is free and the staleness risk is not.

### Scaling strategy

**Sharding:** not applicable and should not be planned for. 100 users generating panel quotations will not approach single-node PostgreSQL limits this decade.

**Read replicas:** unnecessary at launch. Reconsider only if reporting queries begin interfering with transactional work — a streaming replica for the dashboard/reporting workload is the natural first step, well before any sharding conversation.

**Caching:** none in the database layer. Session lookups are the highest-frequency read; if they become hot, move session validation to an in-memory store and keep `auth.sessions` as the revocation record of truth.

**Connection pooling:** required from day one. PgBouncer in transaction mode. Note that `current_setting('app.current_user_id')` used by the audit trigger is session state — set it per transaction, not per connection, or pooling will attribute audit rows to the wrong user.

### Data integrity

**Constraint strategy.** Integrity is enforced in the database, not only in application code. Every relationship has a named foreign key with an explicit delete action. Every status column has a `CHECK`. Business rules that can be expressed as partial unique indexes are (one primary contact per client, one active quotation per job card, one initial stage per module) rather than left to application logic.

**Validation rules.** GSTIN format, email shape, SHA-256 hex, positive quantities and amounts, exit date not before joining date, no self-reference on the two self-referencing tables, and a state-consistency check tying quotation status to whether a PDF and a sender exist.

**Audit logging.** `core.record_audit()` captures full old/new JSONB snapshots via `AFTER` triggers, so nothing bypasses it — including direct `psql` access. Attached to the seven tables where "who changed this and when" carries real consequence: employees, user accounts, role assignments, role permissions, job cards, job lines, quotations. The actor is read from `app.current_user_id`, which the application must set at transaction start.

**Concurrency.** `pipeline.apply_transition()` takes `FOR UPDATE` on the job line and rejects any transition whose claimed source stage does not match reality. Two users pressing "approve" simultaneously produces one success and one clear error, not two transitions and a corrupted pointer.

**Separation of duties.** `pipeline.transition_rules.allow_self_approval` exists specifically because the electrical design head and the production manager are currently the same person. Set it `TRUE` today so work is not blocked; set it `FALSE` on the engineering-release gate once a deputy exists. No schema change required — one `UPDATE`.

### Remaining risks

- `condition_expr` stores an expression evaluated at transition time. Evaluate it in a sandboxed expression parser, never `eval()`. Restrict write access to this table to a single administrative role.
- Personal identity documents (`hr.employee_documents`) may attract data-protection obligations depending on jurisdiction — encryption at rest in object storage, retention limits, and access logging. Confirm before storing real Aadhaar or PAN scans.
- `pipeline.stages.sequence_no` still encodes a strictly linear order. Genuinely parallel stages (design running alongside long-lead procurement) will need a rethink — most likely a separate `stage_dependencies` table — but that is a Module 4+ problem, not a Module 2 one.
