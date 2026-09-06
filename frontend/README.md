# SR Switchgear ERP — frontend

The React + TypeScript SPA served at `/app`, covering sales and the pipeline board.
Built to `FRONTEND_PLAN.md` at the repository root; read that first for the reasoning.

Three surfaces share one origin and one deployment: `/admin` (HR, roles, permissions,
masters, audit log), `/app` (this), and Django's own auth pages (`/login/`,
`/password/change/`). Credentials never pass through this code.

## Running it

```bash
npm install

# No backend needed: the whole app runs off in-memory fixtures (FE0 in the plan).
VITE_API_MODE=fixtures npx vite --base=/ --port 5178      # then open /app

# Against a real Django on :8000 (proxies /api, /admin, /static, /login, /print).
npm run dev                                                # then open /app on :5173

npm run typecheck   # tsc --noEmit
npm run test        # vitest
npm run lint        # biome
npm run build       # tsc && vite build → dist/
npm run e2e         # playwright; skips unless E2E_BASE_URL is set
```

`VITE_API_MODE=fixtures` swaps the transport inside `api/client.ts` for
`src/fixtures/transport.ts`, an in-memory stand-in that answers the same paths with the
same shapes and keeps state for the page load, so a transition really does move a line
between board columns. The import is dynamic and the flag is compiled away, so no fixture
code reaches a production bundle — confirm with `npm run build` and look for a single
app chunk.

## What is wired to what

```
src/
├── main.tsx                 root, providers, style imports
├── app/                     router (basename /app), queryClient, shell/
├── api/                     client.ts (CSRF, 401 → /login, error mapping),
│                            types.ts (the wire contract), queryKeys.ts, endpoints/
├── auth/                    SessionProvider (GET /me), can.ts, permissions.ts
├── components/              Button, Table, Field, Select, Combobox, Dialog, Drawer,
│                            Toast, EmptyState, StageChip, Money, DateText, …
├── features/                board/, job-cards/, job-lines/, clients/, quotations/,
│                            dashboard/ — each with its own strings.ts
├── fixtures/                dev/test only; never imported by app code
├── lib/                     format.ts (money, dates, stage hues), cx, useMediaQuery
└── styles/                  tokens.css, base.css, components.css
```

Four rules the code is built to keep, from the plan:

1. **Stages, actions and permissions are data.** No stage code, action code or role code
   appears in a `.tsx` file. Columns come from `GET /pipeline/stages` (or the board
   payload), a line's buttons come from its `available_actions`, status labels come from
   `GET /enums`. `BoardPage.test.tsx` proves it by rendering stages the source has never
   seen. The one status code the client names — `open`, the default job-card filter —
   lives in `features/job-cards/filters.ts` and nowhere else.
2. **Client-side permission checks decide visibility only.** Every endpoint re-checks; the
   403 is the enforcement.
3. **No business logic in the client.** It never computes a next stage, never decides
   whether a quotation may be sent, never seeds `dispatch_policy` itself — it offers the
   client's default and says where the value came from.
4. **Money is never a float.** Decimal strings from the server, `Intl.NumberFormat('en-IN')`
   to render, no arithmetic anywhere.

Stage colour is derived from the stage code by hashing it into one of twelve hue classes
declared in `components.css`. A class rather than a `style` attribute, so the CSP can stay
`default-src 'self'` with no `'unsafe-inline'` — there are no inline styles in this app.

## Permission drift control

`auth/can.ts` mirrors `identity.services.has_permission`. The shared case table is
`tests/fixtures/permission_cases.json` at the repository root: `vitest` runs it here,
`pytest` runs it against the server implementation, and CI fails when they disagree. The
evaluation rules are written out at the top of `can.ts`; `tests/fixtures/README.md` states
the same contract for the Python side.

## What the backend has to provide

Everything in the plan's endpoint table, plus two additions this build needed:

| Endpoint | Why |
|---|---|
| `GET /api/v1/dashboard` | The plan's dashboard is four bulk queries ("lines where I have an available action" is the `available_actions` join run in bulk). Composing it client-side would be a request per card. |
| `GET /api/v1/attachments/{id}/download` | The plan has attachment upload and listing but no download; like `/quotations/{id}/pdf` it should 302 to storage rather than proxy bytes. |

Two fields the client reads that the plan does not spell out:

- `me.user.is_staff` — gates the sidebar link to Django admin.
- `grants[]` shaped `{resource, action, perm_level, if_owner}` with `perm_level` one of
  `none | own | all`, and `*` accepted for resource or action.

Response conventions assumed everywhere: objects not bare arrays, `{results, page}` for
lists, `{"error": {code, message, fields}}` for failures, `409` for a stale transition,
`422` for a rule violation, `401` as JSON rather than a redirect.

## Serving it from Django

Vite builds to `frontend/dist` with `base: '/static/spa/'`. Django renders the built
`index.html` as a template — that is deliberate: `CSRF_COOKIE_HTTPONLY` stays `True` and
the client reads the token from the `<meta name="csrf-token">` tag instead of the cookie.

```python
# settings.py
TEMPLATES[0]["DIRS"] += [BASE_DIR / "frontend" / "dist"]
STATICFILES_DIRS = [BASE_DIR / "frontend" / "dist" / "assets"]
STATIC_URL = "/static/"
STORAGES["staticfiles"]["BACKEND"] = "whitenoise.storage.CompressedManifestStaticFilesStorage"
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# urls.py
path("app/", TemplateView.as_view(template_name="index.html")),
re_path(r"^app/.*$", TemplateView.as_view(template_name="index.html")),
```

The template needs `csrf_token` in its context (Django's context processor provides it) and
may pass `bootstrap_json`; `api/client.ts` reads both and tolerates neither being rendered,
which is what makes `vite dev` work against the same file.

Docker gains a `frontend-builder` stage on a digest-pinned `node:22-slim` whose only output
is `dist/`, copied into the runtime image. No Node and no `node_modules` in the final image.

## Tests

```
npm run test
```

- `auth/can.test.ts` — the shared permission table, plus the object/no-object rule.
- `lib/format.test.ts` — lakh/crore grouping, decimal strings that never become floats,
  dd/mm/yyyy in Asia/Kolkata, stage-hue stability.
- `api/client.test.ts` — CSRF header on unsafe methods only, empty query values dropped,
  409 → stale, field errors preserved, non-JSON error bodies survived.
- `components/Combobox.test.tsx` — keyboard selection, `aria-activedescendant`, and the
  create row withheld while a search is in flight.
- `app/shell/Sidebar.test.tsx` — navigation appears and disappears with grants.
- `features/board/BoardPage.test.tsx` — columns built from an unseen stage payload.
- `features/job-lines/TransitionDialog.test.tsx` — `requires_note` gating, the 409 message,
  and that a 409 is not retried.
- `features/job-cards/NewJobCardPage.test.tsx` — dispatch policy seeded from the client,
  the hint cleared on override, and one request carrying both lines.

`tests/e2e/journey.spec.ts` is the single Playwright journey from the plan. It skips unless
`E2E_BASE_URL` points at a running stack, because a journey that cannot reach a server
proves nothing.

## Deliberately not here

Realtime push (refetch on focus plus an explicit Refresh), drag-and-drop (on a permissioned
state machine most drop targets are a lie, and a wrong drop writes an audit row that cannot
be deleted), offline support, an i18n library (strings are collected per feature so a Hindi
pass has one place to work), and any UI for HR, roles, masters or the audit log — those are
Django admin's, per the plan.
