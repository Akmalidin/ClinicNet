# ClinicNet Frontend

Vue 3 SPA that talks to the ClinicNet Django/DRF API over JSON + JWT — a
separate app from the backend, not a set of Django templates. See
[`docs/ClinicNet-Phase2-Frontend-Prompt.md`](../docs/ClinicNet-Phase2-Frontend-Prompt.md)
for the plan this is built against and
[`docs/ClinicNet-Referrals-Prompt.md`](../docs/ClinicNet-Referrals-Prompt.md)
section 6 for the referral UI spec.

## Why a fresh SPA, not the `dental` stack

ClinicNet had no frontend at all before this. The obvious visual reference
(`Akmalidin/dental`) uses Vue 3 + Vite + Pinia too, but with Inertia.js —
server-rendered pages driven by Django, not a JSON API. ClinicNet's backend
is a pure DRF API (JWT auth, multi-tenant by subdomain), so this is a
standalone SPA instead: same component/style conventions as `dental`
(ported `tailwind.config.js` and `src/style.css` component classes —
`.btn-primary`, `.card`, `.badge-*`, etc. — so the two products read as
related), but its own axios-based API client, not Inertia.

## In-app navigation only — no full page reloads

Switching sections, creating/editing records, and auth state changes all go
through `vue-router` + Pinia, never `window.location`:

* `src/router/index.js` — all navigation is `router.push`/`beforeEach`
  guards, including the login redirect.
* `src/api/client.js` dispatches a `clinicnet:auth-failure` window event on
  an unrecoverable 401 (refresh token dead); `App.vue` listens for it and
  routes to `/login` via the router, not a hard redirect.
* `src/stores/loading.js` + `src/components/LoadingOverlay.vue` — a global
  top-of-page progress bar driven by in-flight request count (bumped/dropped
  by `api/client.js` interceptors), so every async action gets a visible
  loading state without each component wiring its own spinner.

## Structure

```
src/
  api/            axios instance (client.js) + typed endpoint modules (index.js)
  stores/         Pinia: auth.js (session/JWT), loading.js (global spinner)
  router/         vue-router, requiresAuth guard
  components/
    referrals/    ReferralModal.vue, (ReferralQueueWidget.vue, ReferralBadge.vue — pending)
  pages/          LoginPage, DashboardPage, PatientCardPage
```

## Local development

Needs the Django API running separately (`python manage.py runserver
127.0.0.1:8000` from the repo root, against a tenant whose domain matches
what you hit the SPA through — see the root `README.md`).

```bash
cd frontend
npm install
npm run dev       # http://127.0.0.1:5173 — /api/* proxied to :8000, see vite.config.js
npm run build      # production bundle -> dist/
```

Verified end-to-end against real tenants (Postgres schema, JWT login, DRF
`available_slots`/`referrals`/`branches/directory` endpoints) via scripted
Playwright runs: login → patient card → `ReferralModal` → doctor + slots →
submit → PENDING `Referral` created with `diagnosis_snapshot` correctly
derived server-side from the source visit (same-branch scenario); and,
against a two-branch tenant, the cross-branch scenario both with a specific
doctor picked and with none (`to_specialty` only) — both confirmed correct
in the DB.

## Referral status (this slice)

* ✅ `ReferralModal.vue` — same-branch scenario (spec step 5): pick a
  doctor in the visit's branch, see their free slots for the next 3 days,
  fill reason/clinical note (prefilled from the visit) + priority, submit.
* ✅ Cross-branch extension (spec step 6): a mode toggle adds
  specialty → branch (via `branchesApi.directory()` — see
  `apps/branches/views.py` `BranchDirectoryView`, a gap found while
  building this: `branch.view` alone only ever showed a doctor their own
  branch) → optional specific doctor, falling back to `to_specialty` when
  none is picked.
* ⬜ `ReferralQueueWidget.vue` (spec step 7). Per the spec's own explicit
  note: **must re-check `branch_scope`/`branches` from `/me/` client-side
  before rendering a row** — never assume the backend's queryset filtering
  is the only line of defense against showing another branch's queue.
* ⬜ `ReferralBadge.vue` (spec step 8).
