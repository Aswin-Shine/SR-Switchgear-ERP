# SR Switchgear ERP — implementation notes

What a developer picking this up needs to know that the code does not say for
itself. Everything here is a decision that was made deliberately, a discrepancy
between documents, or a trap that cost time once and should not cost it twice.

Companion documents: `docs/BACKEND_PLAN.md`, `docs/schema/sr_erp_schema_v2.sql`
(the source of truth), `docs/schema/sr_erp_schema_v2_review.md`.

---

## 1. Running it

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt -e ".[dev]"
docker compose up -d db
cp .env.example .env
python manage.py migrate
python manage.py bootstrap_admin --username owner --full-name "Your Name"
python manage.py runserver
```

`bootstrap_admin` prints a generated password once. `createsuperuser` does not
work and cannot be made to: `auth_user_accounts.employee_id` is NOT NULL, an
employee needs a department and a designation, and there is no `is_superuser`
column to set. The bootstrap command creates that whole chain in one
transaction — it is the only way in.

Tests: `pytest` (reuses the database) or `pytest --create-db` (as CI runs it).

---

## 2. Decisions D1–D11, as implemented

Every one was taken as the plan recommended. Where the answer is expressed in
data rather than code, changing it later is an UPDATE, not a deployment.

| ID | Answer | Where it lives |
|---|---|---|
| D1 | SPA at `/app` + Django admin + server-rendered login. Hand-written JSON views, no DRF. | `config/api_urls.py`, `apps/*/api.py` |
| D2 | Appendix B grid, verbatim | `apps/identity/constants.py`, seeded by `identity/0002` |
| D3 | HR is a ninth role; authority is the `user_account:create` permission, never a role-name check | `apps/identity/constants.py` |
| D4 | Reading (a): whoever moved the line into this stage may not move it out | `pipeline/services.py::_check_self_approval` |
| D5 | Appendix C graph, `module_code = 'JOB'` | `pipeline/0003_sales_stage_graph` |
| D6 | Calendar year in the prefix (`JOB-2026-00001`) | `apps/core/numbering.py` |
| D7 | Explicit transition map — **corrected, see §4** | `sales/services.py::QUOTATION_TRANSITIONS` |
| D8 | FKs reproduced verbatim in raw SQL; `db_constraint=False` on every field | `core/0003_database_objects` |
| D9 | MinIO in compose for development; `is_sensitive` gated at `perm_level` 2 from day one | `compose.yaml`, `hr/selectors.py` |
| D10 | Quarterly partitions through 2028-12-31 + `ensure_audit_partitions` from the entrypoint | `apps/core/partitions.py` |
| D11 | `auth_sessions` modelled and left empty | `identity/models.py::LoginSession` |

---

## 3. Where this build departs from the plan, and why

Three places. Each was forced by something measured, not preferred.

### 3.1 `perform_transition` takes a row lock (contradicts phase 4, step 1)

The plan says: *"Read the line's `current_stage_id`. No row lock here —
`apply_transition()` takes `FOR UPDATE` at insert time, and duplicating it in
Python would only widen the window."*

That reasoning assumes the trigger's `FOR UPDATE` is the first lock each writer
takes on the job line. It is not. `fk_job_line_transitions_line` references
`sales_job_lines`, so inserting a transition takes `FOR KEY SHARE` on the
parent row. `KEY SHARE` is shared, so two concurrent writers both acquire it —
and then the `AFTER INSERT` trigger asks each of them to upgrade to
`FOR UPDATE`, which neither can do while the other holds `KEY SHARE`.

Measured: **five deadlocks in six runs** of the two-writer test. The loser got
`OperationalError: deadlock detected` instead of a clean `StaleTransition`.

`_serialise_on()` takes `FOR UPDATE` before the insert, so writers queue in a
deterministic order. Zero deadlocks in eight runs afterwards. This does **not**
duplicate the staleness check: `from_stage_id` is still whatever the caller
believed before the lock, so the loser inserts a transition claiming a stage
the line has left, and the trigger remains the sole arbiter that rejects it.

### 3.2 `resolve_permissions` keeps an owner-scoped grant that outranks

The plan says *"`if_owner` is only dropped when a non-owner grant for the same
pair exists."* Read literally, a level-0 unrestricted grant plus a level-2
owner-only grant collapses into **level-2 unrestricted** — handing every
employee's Aadhaar scan to the holder of a level-0 grant.

Implemented instead: an owner-scoped grant is dropped only when an unrestricted
grant *covers* it (reaches the same level or higher). The two readings agree on
the Appendix B grid as written, so this costs nothing today and closes the
escalation if the grid is ever edited. A test fails against the literal
implementation.

### 3.3 Two indexes moved from `Meta.indexes` into raw SQL

`idx_employee_documents_employee` and `idx_employee_documents_document` are 31
characters. Django's system check `models.E034` refuses any name in
`Meta.indexes` over 30, though PostgreSQL allows 63. The schema's names win —
defect #8 in the review was specifically about constraint names being readable
— so those two are created in `core/0003_database_objects` instead.

---

## 4. Corrections to the source documents

Two statements in the supplied documents are wrong. The code follows the
measured behaviour and says so at the point of use.

### 4.1 `next_number()` is gapless, not gappy

Both `sr_erp_schema_v2.sql` and BACKEND_PLAN.md §11 say a rolled-back
transaction leaves a gap. Measured against PostgreSQL 16, it does not. That
warning is true of a `SEQUENCE`, whose `nextval` is deliberately
non-transactional — but `next_number()` is an ordinary `UPDATE` of a row in
`core_number_series`. It rolls back with its transaction, concurrent callers
serialise on the counter row, and the loser reuses the abandoned number.

The guarantee is therefore *stronger* than advertised, at the cost of one row
lock per prefix. Recorded because someone reading only the comment might "fix"
the imagined gap by switching to a sequence and introduce real ones.
Pinned by `tests/integration/test_numbering_concurrency.py`.

### 4.2 D7's map had an edge the schema forbids

The first draft of `QUOTATION_TRANSITIONS` allowed `active -> lost`.
`ck_quotations_sent` rejects it:

```sql
(status IN ('draft','active') AND sent_at IS NULL)
OR (sent_at IS NOT NULL AND sent_by IS NOT NULL)
OR status = 'superseded'
```

Any status past draft/active/superseded requires both `sent_at` and `sent_by`,
so an outcome can only be recorded on a quotation that was actually sent. The
schema is right — a client cannot decline an offer they were never given — and
the map now matches it.

---

## 5. Traps

### 5.1 Reversing `core/0003` destroys the audit log

`migrate core 0002` drops `core_audit_logs` and every partition. There is no
other copy of who changed what. Take a dump first:

```bash
pg_dump -Fc -t 'core_audit_logs*' srerp > audit_pre_rollback.dump
```

### 5.2 `core_audit_logs.table_schema` always reads `'public'`

`record_audit()` records `TG_TABLE_SCHEMA`, which is meaningful when tables
live in `core`/`hr`/`auth`/`sales`/`pipeline` schemas. Django puts every table
in `public`, so this column is uniformly `'public'`. `table_name` still
distinguishes them. The function is carried over verbatim rather than
"improved", per the precedence rules — this is a consequence of the flat
namespace, not a bug.

### 5.3 `auth_permission` vs `auth_permissions`

Django's own table is `auth_permission` (singular). Ours is `auth_permissions`
(plural). They differ by one character and hold unrelated data. Ours is the one
that matters; Django's stays empty of our models because every model declares
`default_permissions = ()` (verified: 20 rows, all from Django's contrib apps).
The prompt specified the `auth_` prefix. If the ambiguity ever bites, renaming
ours to `identity_*` is a decision to take before the first production migrate.

### 5.4 `job_line_transitions.from_stage_id` is nullable and never used

It reads as an invitation to log a line's entry into the initial stage with
`from_stage_id = NULL`. It cannot be used that way: `current_stage_id` is NOT
NULL, so a new line already sits at the initial stage, and `apply_transition()`
raises *Stale transition* for any insert whose `from_stage_id` does not equal
the line's current stage — including NULL. **Job line creation writes no
transition row.** Entry into the initial stage is recorded by
`job_lines.created_at` and `current_stage_id`.

### 5.5 `SET LOCAL` does not unwind with a nested `atomic()`

`SET LOCAL` is scoped to the *transaction*, not to the savepoint a nested
`atomic()` opens. `audit_actor()` therefore saves and restores the previous
value explicitly. Without that, an inner `audit_actor(B)` would keep
attributing writes to B for the rest of the outer transaction — and with
`ATOMIC_REQUESTS = True` the outer transaction is the entire request.

### 5.6 The employee/account relationship is a manager, not an instance

`uk_user_accounts_employee` makes it one-to-one, but it is modelled as a
ForeignKey plus a UNIQUE constraint, exactly as the schema declares it, rather
than as a `OneToOneField` that would emit a second unique index. So
`employee.user_account` is a `RelatedManager`. Use `employee.account`.

### 5.7 The test suite orders transactional tests last

`django_db(transaction=True)` truncates every table at teardown and
pytest-django does not restore the data migrations' rows. `conftest.py` sorts
`concurrency`-marked tests last (as Django's own runner orders `TestCase`
before `TransactionTestCase`) and re-seeds at session teardown so a
`--reuse-db` database is not left empty for the next run. Without both, the
suite takes 83s instead of 8s and fails depending on ordering.

---

## 6. Production notes

- **PgBouncer in transaction mode is assumed.** That is exactly why the audit
  actor is set with `SET LOCAL` inside the request transaction rather than once
  per connection: a plain `SET` would leak the actor to the next borrower of
  the connection and the trail would name the wrong person.
  `DISABLE_SERVER_SIDE_CURSORS` and `CONN_MAX_AGE = 0` are set for the same
  reason.
- **The entrypoint runs `migrate`.** With more than one replica that races.
  Acceptable for a single container; **the first thing to change when a second
  replica appears** — move `migrate` to a pre-deploy job or an init container.
- **`STATIC_ROOT` defaults to `/tmp/static`** because the container is expected
  to run with a read-only root filesystem apart from `/tmp`, and
  `collectstatic` must still have somewhere to write. Gunicorn gets
  `--worker-tmp-dir /dev/shm` for the same reason.
- **Audit partitions.** `ensure_audit_partitions` runs on every boot and is
  idempotent. A missing partition aborts the *business* transaction that
  provoked the audit write, not merely the audit row — running out of
  partitions is an outage, not a housekeeping lapse.
- **Base images are pinned by digest.** Re-resolve deliberately; the digests
  and the date they were resolved are in a comment above the `FROM` lines.

---

## 7. Not built, deliberately

Per BACKEND_PLAN.md §11, and none of it is stubbed or half-referenced:

- **The dispatch convergence gate.** `dispatch_policy` exists on client and job
  card, is seeded, copied and audited — but the rule "when a card is
  `complete_only`, no line may enter Dispatch until every sibling is ready"
  belongs to the dispatch module. It is one conditional inside
  `perform_transition` when that module arrives, and needs no schema change.
- **Parallel stages.** `sequence_no` is linear. Design running alongside
  long-lead procurement needs a `stage_dependencies` table. Module 4+.
- **Refresh tokens.** `auth_sessions` is created and left empty (D11).
- **The React SPA.** `FRONTEND_PLAN.md` was not supplied with this build. The
  JSON API it specifies is complete and contract-tested; the `frontend-builder`
  Docker stage is written and left inert, so adding the client is not also a
  Dockerfile rewrite. `templates/index.html` renders the shell and embeds the
  CSRF token in a meta tag, which is what lets `CSRF_COOKIE_HTTPONLY` stay
  `True`.
- **HR/payroll, attendance, leave. DRF, Celery, Redis, JWT, permission
  libraries, admin themes.** Excluded by the prompt.
- **Workload-tuned indexes.** Structural only, per the schema review. Revisit
  with `pg_stat_statements` evidence.

---

## 8. Verification performed

| Check | Result |
|---|---|
| Reference schema applies to PostgreSQL 16 | clean, single transaction |
| Django schema vs reference: tables | 25/25, all columns matching name/type/nullability |
| Django schema vs reference: foreign keys | 46/46 identical by name **and** delete action |
| Django schema vs reference: triggers | 21/21 name-for-name |
| Django schema vs reference: `idx_*` indexes | 27/27 name-for-name |
| FKs deferrable, or missing `ON DELETE` | 0 and 0 (D8 satisfied) |
| Composite PKs | `(quotation_id, job_line_id)` and `(id, occurred_at)` intact |
| `auth_permission` rows from our models | 0 (20 total, all Django contrib) |
| CHECKPOINT 1 down/up cycle | migrate → core 0002 → migrate → sales zero → migrate, all clean |
| `manage.py check --deploy` | no issues |
| `makemigrations --check` | no drift |
| Test suite | 320 passing |
| Coverage on `apps/*/services.py` | 93% (floor 85%) |
| Two-writer transition race | exactly one 201 and one 409; zero deadlocks in 8 runs |
| Twenty concurrent `next_number()` callers | 20 distinct, no gaps |

The only column-level differences from the reference schema are the two
surrogate primary keys deviation 3.8 sanctions, on `auth_user_roles` and
`auth_role_permissions`.
