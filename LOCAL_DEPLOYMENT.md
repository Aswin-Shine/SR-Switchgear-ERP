# Local deployment — no Docker

Running the whole stack on a bare machine: a natively installed PostgreSQL,
a Python venv for the backend, Node for the frontend. Two ways to run it are
covered below — pick one:

- **Split dev mode** — two processes (Vite + Django), hot reload on both
  sides. What you want while changing code.
- **Integrated mode** — one process (Django serving the built SPA), no Vite
  running. What you want to sanity-check what Docker will actually ship,
  without building the image.

Commands below assume macOS (Homebrew) with a note for Linux where it
differs. Everything runs from the repo root unless a `cd` is shown.

---

## 1. Install PostgreSQL 16 natively

**macOS:**
```bash
brew install postgresql@16
brew services start postgresql@16
/opt/homebrew/opt/postgresql@16/bin/createuser -s srerp
/opt/homebrew/opt/postgresql@16/bin/createdb -O srerp srerp
/opt/homebrew/opt/postgresql@16/bin/psql -c "ALTER USER srerp WITH PASSWORD 'srerp';"
```

**Linux (Debian/Ubuntu):**
```bash
sudo apt-get install postgresql-16
sudo -u postgres createuser -s srerp
sudo -u postgres createdb -O srerp srerp
sudo -u postgres psql -c "ALTER USER srerp WITH PASSWORD 'srerp';"
```

The schema needs the `citext` extension available. `apps/core/migrations`
enables it itself (`CITextExtension()`), so nothing manual is needed here —
just confirm the role above has permission to run `CREATE EXTENSION`, which
a superuser role (`-s` above) always does.

Verify: `psql -U srerp -h localhost -d srerp -c "SELECT version();"` should
report PostgreSQL 16.

## 2. Backend

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -e ".[dev]"

cp .env.example .env
# .env's defaults (POSTGRES_HOST=localhost, STORAGE_BACKEND=filesystem)
# already match a native Postgres with no MinIO — no edits needed for this
# path. Document uploads write to backend/media/ instead of object storage.

.venv/bin/python manage.py migrate
.venv/bin/python manage.py bootstrap_admin --username owner --full-name "Your Name"
```

`bootstrap_admin` prints a generated password once — this is the only way
to create the first account; `createsuperuser` does not work here (see
`backend/IMPLEMENTATION.md` §1 for why).

Run the backend test suite here too, since it needs the same native
Postgres: `.venv/bin/pytest` (320 tests, real database — no SQLite path).

## 3. Frontend

```bash
cd frontend
npm install
```

## 4a. Split dev mode (hot reload, what you want while coding)

Two terminals:

```bash
# terminal 1 — backend, serves /api, /admin, /login
cd backend && .venv/bin/python manage.py runserver

# terminal 2 — frontend, proxies /api, /admin, /static, /login to :8000
cd frontend && npm run dev
```

Open `http://localhost:5173/app`. Vite's dev server proxies every
Django-owned path (`/api`, `/admin`, `/static`, `/media`, `/login`,
`/logout`, `/password`, `/print`, `/healthz` — see
`frontend/vite.config.ts`) back to `:8000`, so cookies stay same-origin and
the session `/login/` sets is the one `/api/v1/me` reads. This is also the
mode `frontend/README.md`'s `VITE_API_MODE=fixtures` variant runs in, if you
want the UI with no backend at all.

## 4b. Integrated mode (one process — what Docker ships)

```bash
cd frontend
npm run build                                   # → frontend/dist

cd ../backend
.venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py runserver
```

Open `http://localhost:8000/app`. This exercises the exact wiring the
production image uses: `config/settings/base.py` puts `frontend/dist` ahead
of `backend/templates/` in `TEMPLATES["DIRS"]` once it exists, so
`apps/identity/views.py::app_shell` renders the real built `index.html`
(hashed `<script>` tag included) instead of the empty placeholder — and
`STATICFILES_DIRS` publishes the built assets under `/static/spa/`, matching
the `base: "/static/spa/"` Vite built them with. See
[`IMPLEMENTATION.md`](IMPLEMENTATION.md) if either of those settings ever
needs touching again.

Re-run both commands (`npm run build` then `collectstatic`) after any
frontend change — nothing watches `frontend/dist` for you in this mode,
unlike 4a.

## 5. What differs from the Docker path

- No object storage container: `STORAGE_BACKEND=filesystem` (the `.env.example`
  default) writes uploaded documents straight to `backend/media/` on disk.
  Switch to `STORAGE_BACKEND=s3` with real credentials, or run
  `docker compose --profile minio up -d minio` for a local S3-compatible
  target, if you need to exercise the object-storage path.
- No entrypoint script: `migrate`, `ensure_audit_partitions` and
  `collectstatic` are commands you run yourself (above), not steps a
  container runs on boot.
- `DJANGO_SETTINGS_MODULE=config.settings.local` (the `.env.example`
  default) — not `production`. Debug is on, `ALLOWED_HOSTS = ["*"]`, and
  password hashing is deliberately weak (`MD5PasswordHasher`) to keep the
  fixture chain fast. Never point this settings module at a real database
  of real people.

## 6. End-to-end check

The one Playwright journey (`frontend/tests/e2e/journey.spec.ts`) runs
against a real running stack — either mode above — and skips unless
`E2E_BASE_URL` is set:

```bash
cd frontend
E2E_BASE_URL=http://localhost:8000 npm run e2e     # against integrated mode (4b)
```

It logs in, creates an enquiry with two job lines, moves one line to
Quotation, uploads a quotation revision and marks it sent, then asserts the
other line is untouched and the board shows them in different columns.
