# SR Switchgear ERP — backend

Django 5.2 + PostgreSQL 16 backend for Modules 1 (HR, identity, RBAC) and 2
(Sales enquiry, quotation, job pipeline).

Built to `docs/BACKEND_PLAN.md`, against the schema in
`docs/schema/sr_erp_schema_v2.sql`, which is the source of truth and wins every
conflict.

---

## Quick start

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt -e ".[dev]"

docker compose up -d db
cp .env.example .env

python manage.py migrate
python manage.py bootstrap_admin --username owner --full-name "Your Name"
python manage.py runserver
```

`bootstrap_admin` prints a generated password once — `createsuperuser` cannot
work here, and `IMPLEMENTATION.md` §1 explains why.

Then: `/login/`, `/admin/`, `/app/`, `/api/v1/me`, `/healthz/`.

## Tests

```bash
pytest                  # reuses the test database
pytest --create-db      # as CI runs it: proves migrations build from nothing
ruff check .
```

320 tests. Every one runs against a real PostgreSQL 16 — there is no SQLite
path, because the schema leans on partial indexes, JSONB, range partitioning
and plpgsql triggers that SQLite would not exercise.

---

## Layout

```
apps/
  core/      departments, designations, documents, numbering, audit log
             + the custom fields, the audit-actor helper and the API helpers
  identity/  accounts, roles, permissions, the RBAC engine
  hr/        the employee master and personal documents
  pipeline/  the stage graph, transition rules, the transition engine
  sales/     clients, job cards, job lines, quotations, notes, attachments
config/      settings (base/local/production), URLs, WSGI
docs/        the plan, the schema, the schema review
tests/       unit / integration / contract
```

Each app carries `models.py`, `services.py`, `selectors.py`, `admin.py` and,
where it has one, `api.py`.

- **`services.py`** holds business logic. Views orchestrate; `save()` does
  nothing clever.
- **`selectors.py`** holds every read that is not `Model.objects.get(pk=...)`,
  including the soft-delete filter. Managers are deliberately *not* overridden
  to hide soft-deleted rows: an invisible default filter breaks the admin and
  hides referential reality, so `deleted_at IS NULL` is written out, matching
  the partial indexes.
- No stage code, role code or status string is compared against a literal in
  application logic. Stages, roles and permissions are rows. The one bounded
  exception is a status domain the database itself pins with a CHECK — those
  are declared once as `TextChoices` and referenced symbolically.

## How authority works

Nothing asks "is this user Sales?". Callers ask
`has_permission(user, resource, action, obj=..., level=...)`, which resolves
grants from `auth_role_permissions`. Three consequences:

- moving an authority between roles is an UPDATE, not a deployment;
- the Django admin and the JSON API give the same answer, because
  `RBACModelAdmin` routes the admin's four permission hooks into the same
  function;
- `/api/v1/me` returns resolved grants rather than role names, so the SPA
  cannot re-implement the grid in JavaScript and drift from it.

`perm_level` has concrete meaning: 0 ordinary fields, 1 protected employee
fields, 2 sensitive documents. `if_owner` narrows a grant to rows the user
owns, with ownership defined explicitly per model.

## How a job moves

A job card is the commercial container and has no stage. The **job line** is
what travels the pipeline, so one enquiry for 3 ATS panels and 2 AMF panels is
one card and two lines that move independently.

`perform_transition()` decides whether a move is *allowed*;
`apply_transition()` — a database trigger — decides whether it is still *valid*
when it lands, and advances `current_stage_id` under a row lock. Two people
pressing the same button produce one success and one 409, never two
transitions or a corrupted pointer.

Adding a department to the pipeline is an INSERT into `pipeline_stages` plus
rules in `pipeline_transition_rules`. It is not a migration and not a code
change.

---

## Further reading

- **`IMPLEMENTATION.md`** — decisions D1–D11 as implemented, the three places
  this build departs from the plan and why, two corrections to the source
  documents, the traps, and production notes. Read this before changing
  anything in `pipeline/services.py` or `core/migrations/0003`.
- **`docs/BACKEND_PLAN.md`** — the plan this was built to.
- **`docs/schema/sr_erp_schema_v2_review.md`** — why the schema is shaped the
  way it is, including the twelve defects it fixed.
