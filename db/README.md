# db/

Operational tooling for the Postgres database — **not** the schema itself.
The schema is `backend/docs/schema/sr_erp_schema_v2.sql`, the source of
truth per the root `CLAUDE.md`; the schema that actually runs is the Django
migrations under `backend/apps/*/migrations/`. This folder holds scripts
that act on a running database, not its definition.

## Seed data (dev only)

```bash
docker compose exec web python manage.py seed_dev_data
```

Requires `bootstrap_admin` to have run first (see the root `README.md`
quick start). Creates one more employee/account, two product categories,
one client, and one job card with two job lines (3 ATS + 2 AMF panels —
the exact scenario `CLAUDE.md` itself uses as the canonical "one card, two
lines" example). Every write goes through the real `services.py`
functions the API uses, under an Owner actor, so it can't drift from what
the app actually enforces. Idempotent — running it again is a no-op once
the demo client exists. The command lives in
`backend/apps/core/management/commands/seed_dev_data.py`, next to
`bootstrap_admin.py`.

## Backup / restore

```bash
./db/backup.sh                      # dumps to db/backups/<db>-<timestamp>.sql.gz
./db/restore.sh db/backups/srerp-20260825-030000.sql.gz
```

Both wrap `docker compose exec db pg_dump`/`psql` against the `db` service
in the root `docker-compose.yml` — the stack must be up
(`docker compose up -d db` at minimum). `backup.sh` dumps with
`--clean --if-exists`, so the resulting file is self-contained: restoring
it drops and recreates everything it covers, rather than failing against a
non-empty database. `restore.sh` is destructive and asks you to type the
database name back before it touches anything.

`db/backups/` is gitignored — dumps can contain real business data and
should never be committed.
