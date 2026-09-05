# SR Switchgear ERP

Django 5.2 + PostgreSQL 16 backend and a React 19 + TypeScript SPA, built as
one deployable: one Docker image, one origin, one session. Covers Modules 1
(HR, identity, RBAC) and 2 (Sales enquiry, quotation, job pipeline).

```
sr-switchgear-erp/
├── backend/    Django app — models, services, the JSON API, Django admin
├── frontend/   React SPA at /app — sales and the pipeline board
├── docker-compose.yml     production stack (this file's directory)
└── LOCAL_DEPLOYMENT.md    running both halves with no Docker at all
```

## Three surfaces, one origin

| Surface | What it's for | Built by |
|---|---|---|
| `/admin/` | HR, roles, permissions, masters, audit log | Django admin |
| `/app/` | Sales enquiries and the pipeline board | The React SPA in [`frontend/`](frontend/README.md) |
| `/login/`, `/password/change/` | Auth, forced password change | Server-rendered Django views |
| `/api/v1/` | JSON the SPA calls | Hand-written Django views, no DRF |

There's no separate frontend server or container: the SPA is built once
(`npm run build`) into `frontend/dist`, Django serves the built assets
through WhiteNoise, and `frontend/dist/index.html` is rendered as a Django
*template* — not served as a static file — so the CSRF token can be embedded
in a `<meta>` tag while `CSRF_COOKIE_HTTPONLY` stays `True`. See
[`backend/FRONTEND_PLAN.md`](backend/FRONTEND_PLAN.md#serving-and-build) for
why that's deliberate, and [`IMPLEMENTATION.md`](IMPLEMENTATION.md) for
exactly how the two halves are wired together.

## Quick start

**New to this repo? This is the path — Docker, production-shaped, no local
Python/Node/Postgres install needed:**

1. **Copy the env file and fill in the required values.**
   ```bash
   cp .env.example .env
   ```
   At minimum, set `DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD` (the file
   has generator one-liners in comments next to each). Everything else has
   a working default for local use.

2. **Build and start the stack** (Postgres + the Django/React image):
   ```bash
   docker compose up -d --build
   ```

3. **Create the first login** — there's no `createsuperuser` in this repo
   (see `backend/IMPLEMENTATION.md` §1 for why); this is the only way to
   get an initial account:
   ```bash
   docker compose exec web python manage.py bootstrap_admin --username owner --full-name "Your Name"
   ```

4. **Open the app**: `http://localhost:8000/login/`. `/admin/` is the
   Django admin (HR, roles, masters); `/app/` is the React SPA (sales,
   pipeline board) — same login, same session.

That's the whole path. Full reference: the compose file's own header
comment, or [`IMPLEMENTATION.md`](IMPLEMENTATION.md).

**Optional — TLS + HSTS + a Basic Auth gate in front, via Caddy**, for
deploying to a real host reachable from the internet (skip this for local
use):
```bash
docker compose -f docker-compose.caddy.yaml run --rm hash-password   # after setting CADDY_BASIC_AUTH_PASSWORD in .env
# paste the printed hash into .env as CADDY_BASIC_AUTH_HASH (double every $ to $$)
# set CADDY_SITE_ADDRESS/CADDY_TLS_ARG in .env to your real domain/email
docker compose --profile caddy up -d --build
```
Details: [`IMPLEMENTATION.md`](IMPLEMENTATION.md) §6.

**No Docker (native Python + Node + Postgres):** see
[`LOCAL_DEPLOYMENT.md`](LOCAL_DEPLOYMENT.md).

**Backend or frontend only**, with their own dev workflows (fixtures-only
frontend, `--reuse-db` test runs, `ruff`/`biome`, individual test suites):
see [`backend/README.md`](backend/README.md) and
[`frontend/README.md`](frontend/README.md) — each covers its half in full.

## Documents in this repo

| Document | Covers |
|---|---|
| [`README.md`](README.md) | This file — the whole system, at a glance |
| [`IMPLEMENTATION.md`](IMPLEMENTATION.md) | How frontend and backend are actually wired together, and what changed to make them one working app |
| [`LOCAL_DEPLOYMENT.md`](LOCAL_DEPLOYMENT.md) | Running everything on a bare machine, no Docker |
| [`docker-compose.yml`](docker-compose.yml) | The production stack |
| [`db/README.md`](db/README.md) | Dev seed data, backup/restore scripts — not the schema itself (`backend/docs/schema/`) |
| [`backend/README.md`](backend/README.md) · [`backend/IMPLEMENTATION.md`](backend/IMPLEMENTATION.md) | Backend architecture, RBAC engine, pipeline engine, decisions D1–D11, traps |
| [`backend/docs/BACKEND_PLAN.md`](backend/docs/BACKEND_PLAN.md) | The plan the backend was built to; schema is the source of truth |
| [`frontend/README.md`](frontend/README.md) · [`backend/FRONTEND_PLAN.md`](backend/FRONTEND_PLAN.md) | Frontend architecture, the API contract, the permission-drift test harness |

## The four rules the whole system is built to keep

1. **Stages, actions and permissions are data**, never a literal compared in
   code — not in Python, not in a `.tsx` file. Moving authority between roles,
   or adding a pipeline stage, is a database row, not a deployment.
2. **The server is the only enforcement.** The client mirrors
   `identity.services.has_permission` (in `frontend/src/auth/can.ts`) purely
   to decide what to render; every endpoint re-checks, and the 403 is what
   actually stops anything. A shared fixture,
   [`frontend/fixtures/permission_cases.json`](frontend/fixtures/permission_cases.json),
   is run by both `pytest` and `vitest` so the mirror can't silently drift.
3. **No business logic in the client.** It never computes a next stage,
   decides whether a quotation may be sent, or seeds a default — it renders
   what the server says is possible.
4. **Money is never a float.** The server sends decimal strings; the client
   formats them and does no arithmetic on them.
