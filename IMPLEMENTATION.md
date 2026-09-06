# SR Switchgear ERP — implementation notes (frontend + backend integration)

This document covers only the seam between the two halves: how a backend
built in one session and a frontend built in another actually become one
running application. Backend-internal decisions (D1–D11, the RBAC engine,
the pipeline engine, traps in `pipeline/services.py`) are in
[`backend/IMPLEMENTATION.md`](backend/IMPLEMENTATION.md); frontend-internal
structure is in [`frontend/README.md`](frontend/README.md). Read those first
for their halves — this file is about the join.

---

## 1. What was actually broken when the two halves were combined

Both halves were built to the same plan
([`backend/FRONTEND_PLAN.md`](backend/FRONTEND_PLAN.md)) and the API
contract lines up exactly — 25 endpoints, matching response shapes, the
same permission model on both sides. But the plumbing that serves the SPA
*through* Django was written before `frontend/` existed, as a deliberately
inert stub (see `backend/FRONTEND_PLAN.md`'s "Not built, deliberately" /
`backend/IMPLEMENTATION.md` §7's "The React SPA" note), and three pieces of
it were never finished once the frontend arrived:

1. **`TEMPLATES["DIRS"]`** in `backend/config/settings/base.py` pointed only
   at `backend/templates/`. `apps/identity/views.py::app_shell` renders
   `render(request, "index.html")` — with only one `DIRS` entry, that
   always resolved to the placeholder `backend/templates/index.html`
   (empty `<div id="root">`, no `<script>` tag), never to the real,
   Vite-built `frontend/dist/index.html` with its hashed entry script. The
   SPA route existed and returned 200, but rendered nothing.

   **Fixed**: `_FRONTEND_DIST` (`frontend/dist`) is now prepended to
   `TEMPLATES["DIRS"]` when it exists, ahead of `backend/templates/`, so the
   built shell wins once a build has run. The placeholder still exists and
   still answers when no build exists yet (e.g. `manage.py runserver`
   before anyone has run `npm run build`), so nothing 500s in that case.

2. **`STATICFILES_DIRS`** pointed at `frontend/dist` with no prefix. Vite
   builds with `base: "/static/spa/"` (`frontend/vite.config.ts`), so the
   built HTML references assets at `/static/spa/assets/main-<hash>.js`. An
   unprefixed `STATICFILES_DIRS` entry publishes `frontend/dist/assets/...`
   at `/static/assets/...` instead — one path segment short, so every asset
   the built page requests would 404.

   **Fixed**: `STATICFILES_DIRS = [("spa", _FRONTEND_DIST)]` — the
   `(prefix, path)` tuple form namespaces everything under `/static/spa/`,
   matching Vite's `base` exactly.

3. **`backend/Dockerfile`'s `frontend-builder` stage was commented out.**
   Its four build lines (`npm ci`, `npm run build`, ...) were left as
   comments with a note to uncomment them "once `frontend/` exists." It now
   does, so the image was still shipping an empty `frontend/dist/` — the
   two settings fixes above would have had nothing to serve.

   **Fixed**: the stage now actually runs `npm ci && npm run build`. This
   also exposed the real structural issue underneath it — see next section.

## 2. The build-context problem, and why it touched three more files

The `frontend-builder` stage needs `COPY frontend/...`, but
`backend/compose.yaml` built with `context: .` — resolved relative to
`backend/compose.yaml`, i.e. `backend/` itself. `frontend/` is a sibling
directory, outside that context; Docker cannot `COPY` a path that isn't
inside the build context, no matter what the Dockerfile says. Uncommenting
the SPA build lines alone would have made every build fail at that `COPY`.

The fix is that **the build context is now the repository root**, not
`backend/`, so `backend/Dockerfile` can reach both halves:

- `backend/Dockerfile` — every `COPY` source is now prefixed
  `backend/...` or `frontend/...` (previously bare, e.g. `COPY manage.py`
  is now `COPY backend/manage.py`). It documents at the top how it must be
  built: `docker build -f backend/Dockerfile -t srerp .` from the repo
  root, never from inside `backend/`.
- `backend/compose.yaml` — its `web` service now sets
  `context: ..` (repo root, relative to where `compose.yaml` lives) and
  `dockerfile: backend/Dockerfile` explicitly, instead of the old
  `context: .`.
- `docker-compose.yml` (repo root, new) — the production stack. Sets
  `context: .` (it already lives at the root) and
  `dockerfile: backend/Dockerfile`.
- `.dockerignore` — moved from `backend/.dockerignore` to a root
  `.dockerignore`, since Docker resolves `.dockerignore` relative to the
  build context, and the context is now the root for both compose files.
  It excludes dev/test artifacts from both `backend/` and `frontend/`.

Both compose files were validated with `docker compose config` after the
change, and the image was built end-to-end from the repo root to confirm
the multi-stage `COPY`s resolve and the SPA actually lands in the runtime
stage.

## 3. Two docker-compose files, on purpose

| File | Purpose |
|---|---|
| `backend/compose.yaml` | Backend-only local dev: `db` (+ `minio` for object storage), `web` optional. This is what `backend/README.md`'s quick start means by `docker compose up -d db` — most backend iteration is `manage.py runserver` against just the database, not the built image. |
| `docker-compose.yml` (root) | The production stack: `db` + `web` (the full image, frontend included), with a `minio` profile for self-hosted object storage. Hardened: non-root (baked into the image), `read_only: true` + a `/tmp` tmpfs (matching the image's own read-only-rootfs assumption — see `backend/IMPLEMENTATION.md` §6), `cap_drop: [ALL]`, `no-new-privileges`, resource limits, health-gated startup ordering. |

They share one `backend/Dockerfile`, so there's one build definition for the
image, not two.

## 4. The API contract between the two halves

This is unchanged from `backend/FRONTEND_PLAN.md` — recorded here only so
it doesn't have to be re-derived from two documents:

- Session-cookie auth, `X-CSRFToken` on unsafe methods, same origin, no
  CORS anywhere (there's nothing to configure — the SPA and the API are the
  same origin by construction).
- Responses are always objects, `{results, page}` for lists, errors as
  `{"error": {"code", "message", "fields"}}`. `401` is JSON, not a
  redirect — the client sends the user to `/login/?next=` itself.
- `403` (`PermissionDenied`) is real enforcement; `409`
  (`StaleTransition`) means the pipeline trigger rejected a transition
  whose claimed source stage had already moved; `422` (`RuleViolation`) is
  a business-rule failure, e.g. a missing required note. All three are
  mapped once, in `apps/core/middleware.py::DomainErrorMiddleware` — see
  `backend/IMPLEMENTATION.md` for the exception hierarchy behind them.
- `GET /api/v1/me` returns **resolved grants**
  (`{resource, action, perm_level, if_owner}`), not role names — this is
  what stops the client from having to re-implement the permission grid.
  `frontend/src/auth/can.ts` is the one place in the client that reasons
  about them, and it's checked against the backend's own
  `identity.services.has_permission` via the shared fixture
  `frontend/fixtures/permission_cases.json` (`pytest` and `vitest` both run
  it; CI fails if the two disagree).

## 5. Verification performed on the integration

| Check | Result |
|---|---|
| `docker compose -f docker-compose.yml config` (default + `--profile minio`) | Valid |
| `docker compose -f backend/compose.yaml config` | Valid after the context change |
| `docker build -f backend/Dockerfile -t srerp .` from repo root | Builds; `frontend/dist/assets/*` present in the runtime stage under `./frontend/dist` |
| `TEMPLATES["DIRS"]` / `STATICFILES_DIRS` ordering | `frontend/dist` present and prefixed `spa` only when built; falls back cleanly when absent |

What was **not** re-verified here (out of scope for a documentation and
Docker-wiring pass, and already covered by each half's own suite): the 320
backend tests in `backend/tests/`, and the frontend's `vitest`/`playwright`
suites. Run those from `backend/` and `frontend/` respectively — see each
README.

## 6. Reverse proxy: TLS, HSTS, and a Basic Auth gate in front (Caddy)

`docker-compose.yml` bundles an **opt-in `caddy` service**, same
`profiles: ["caddy"]` pattern as `minio` — plain
`docker compose up -d --build` never starts it. Config is the repo-root
`Caddyfile`: TLS with automatic HTTP→HTTPS redirect, HSTS + standard
hardening headers, and a `basic_auth` gate ahead of everything so an
anonymous scanner never even reaches Django's `/login/`. That's a second,
shared-credential layer — Django's own per-employee session auth
(`app_shell` is `@login_required`, `/api/v1/` returns `401` without a
session) is unchanged and still the real access control.

The Caddyfile is env-driven (`{$CADDY_SITE_ADDRESS}`,
`tls {$CADDY_TLS_ARG}`) rather than hardcoded, so the same file covers
both local dev (`localhost` / `internal` — Caddy's own local CA, no
internet/DNS needed, browser trust warning expected) and a real
deployment host (your real domain / your real email — switches Caddy to
ACME, which needs the domain resolving here with 80/443 reachable). See
`.env.example`'s "Caddy reverse proxy" section and the README quick start
for the exact commands.

`web`'s port is now `127.0.0.1:8000:8000` (was `8000:8000`) —
loopback-only, since Caddy reaches `web:8000` over the compose network by
service name and never needed the published port. Without this, a
stranger could `curl http://host:8000/` on a real deployment host and skip
the proxy entirely.

`docker-compose.caddy.yaml` is a one-shot helper, not a third stack —
`docker compose -f docker-compose.caddy.yaml run --rm hash-password` turns
`CADDY_BASIC_AUTH_PASSWORD` into the bcrypt hash `basic_auth` needs.
**Double every `$` to `$$`** when pasting that hash into `.env` as
`CADDY_BASIC_AUTH_HASH` (e.g. `$2a$14$abc...` → `$$2a$$14$$abc...`) —
Compose treats a bare `$` in `.env` as its own `${...}` interpolation and
silently mangles an unescaped hash. Caddy itself then reads
`{$CADDY_BASIC_AUTH_USERNAME}` / `{$CADDY_BASIC_AUTH_HASH}` from the
environment at startup — unrelated to Compose's `$$` escaping, and the
plaintext password is never written to the Caddyfile.
