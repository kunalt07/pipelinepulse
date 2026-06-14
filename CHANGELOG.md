# Changelog

All notable changes to PipelinePulse. Format loosely based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

This file is the human-readable narrative of what shipped when. For full
detail, see `git log`. Each entry maps to one or more commits; commit hashes
are included for traceability.

## [Unreleased]

### Planned
- (No specific roadmap items at the moment. Session 3 closed out the
  multi-tenant rebuild. Possible Session 4: SaaS infra — domain, HTTPS,
  production DB, backups, Sentry, password-reset email — mostly config.)

---

## 2026-06-14 — Multi-tenant rebuild, Session 3

### Added
- **Per-user APScheduler sync jobs.** Each user with at least one env gets
  their own `sync_user_<id>` job. Registered on first env creation,
  removed on last env deletion, rescheduled live when the user changes
  their `sync_interval_minutes`. Two users can sync at different cadences.
- **Per-user settings.** `webhook_url`, `gemini_api_key`, `gemini_model`,
  `sync_interval_minutes` are now per-user. Stuck-run thresholds stay
  global. `settings` table gains an `owner_user_id` column with `0` as
  the global sentinel; PK swaps to `(owner_user_id, key)`.
- **Strict per-user resolution rule.** New users do NOT inherit env-var
  webhook/Gemini values. The migration seeds admin's per-user rows from
  the existing env vars so admin's setup keeps working — but signup of
  a new user gives them blank settings, so they don't accidentally fire
  alerts to admin's Discord.
- **Rate limiting on auth.** `slowapi` per-IP limits: `/auth/login` 5/min,
  `/auth/signup` 3/hour. Verified via 6-rapid-attempts test → 6th request
  returns 429.

### Changed
- README repositions PipelinePulse as a multi-tenant SaaS (or self-host).
  New "Multi-tenant accounts", "First-run wizard", "Per-user sync",
  "Rate limiting" features called out in the auth section.
- Webhook delivery (`notifier.send_failure_alert`, `send_sla_alert`,
  `send_report_notification`) now resolves the URL per env's owning user.
- AI Gemini handle now built per env so each user's API key is used.
- The `/settings` GET/PUT endpoints scope reads + writes to the current
  user's row (per-user keys) or the global sentinel row (global keys).

### Verified end-to-end
- Admin's sync interval = 2 min; Alice's = 5 min; backend logs confirm
  independent reschedule. `settings.user_id=5` row exists post-change.
- Alice's `webhook_url` shows `set: false` despite the env-var being set
  — proving the no-inherit rule works.
- 6 rapid login attempts returns 429 on the 6th.

Commit: forthcoming

---

## 2026-06-14 — Multi-tenant rebuild, Session 2

### Added
- **Per-user data isolation.** Every env-scoped table (`environments`,
  `dag_runs`, `task_instances`, `notifications`, `ai_insights`,
  `report_runs`, `report_schedules`, `dag_alert_configs`, `dag_sla_configs`,
  `run_annotations`) gained a `user_id` column. Existing data backfilled to
  `user_id = 1` (the seeded admin). Each user now sees only their own
  envs/runs/alerts/reports.
- `environment.py:get_user_env` and `env_dep` now resolve env names within
  a user's tenant — cross-tenant access is structurally impossible.
- Frontend `activeEnv` localStorage key namespaced per user
  (`pipelinepulse:active-env:user_<id>`) so two accounts on one browser
  don't collide. Legacy unscoped key auto-migrates on first login.

### Changed
- `environments.name` UNIQUE constraint went from global to `(user_id, name)` —
  two users can both have an env called "production".
- `report_schedules` UNIQUE went from `(environment_id)` to
  `(user_id, environment_id)`.
- Composite-PK tables (`dag_alert_configs`, `dag_sla_configs`,
  `run_annotations`) gained `user_id` as the leading PK column.
- Sync loop iterates over all envs across all users; `_maybe_alert`,
  `_check_sla_breaches`, `_maybe_generate_scheduled_report` all derive
  `user_id` from `env.user_id` and propagate into queries + writes.

### Migration safety
- Pre-migration `pg_dump` taken to `.backups/pre-tenancy-20260614-140935.sql`
  (gitignored). Migration is idempotent — re-runnable, no `DELETE`s.
- Verified end-to-end: admin (user_id=1) sees their 131 runs in "production";
  a fresh signup sees zero envs and the first-run wizard; same `dag_run_id`
  co-exists across tenants without UNIQUE collision; cross-tenant probes
  return 404.

Commit: `92efcbf`

---

## 2026-06-13 — First-run wizard

### Added
- 5-step wizard (Welcome → Connect Airflow → Webhook → Gemini key → Done)
  that triggers when `envCount === 0`, walking new users through their
  initial setup.
- `POST /environments/probe` and `POST /settings/probe-webhook` for
  pre-save connection validation.
- `?wizard=preview` URL flag forces wizard render even with envs configured;
  preview mode no-ops every save call so it can't touch the DB.

### Fixed
- Wizard wasn't rendering on a fresh deploy because env-scoped 404s on
  `/summary` etc. caused `loadGlobal()` to reject before the wizard could
  trigger. Fixed by loading `/environments` first and short-circuiting
  the env-scoped calls when empty.

### Notes
- Reverted once mid-session due to me wiping the user's DB during testing
  (commit `dac75ba`); reapplied with the preview-mode flag (`893f0ab` +
  `edd90ac`) so future testing doesn't need to nuke data.

Commits: `888930f`, `73f85fa`, `dac75ba` (revert), `893f0ab`, `edd90ac`

---

## 2026-06-12 — Phase A.5: close auth gate + API tokens

### Added
- `Authorization: Bearer pp_<64 hex>` token auth for curl/scripts.
- `api_tokens` table with two-step lookup (8-char `token_prefix` then
  bcrypt verify, à la Stripe/GitHub). `pp_` prefix makes leaked tokens
  greppable.
- 3 endpoints: `GET /api-tokens`, `POST /api-tokens` (returns plaintext
  ONCE), `DELETE /api-tokens/{id}` (soft-delete).
- New "API tokens" card in Settings: list, create-with-one-time-reveal,
  revoke (type-DELETE-to-confirm).
- CORS `expose_headers` for `Content-Disposition`, `X-Report-Id`,
  `X-Report-Summary` (latent cross-origin bug for report downloads).

### Changed
- `require_auth` now actually gates: accepts session cookie OR bearer
  token, else 401. Bootstrap endpoints (`/`, `/health`, `/auth/signup`,
  `/auth/login`) remain public.

### Polish pass (same day)
- README rewritten to reflect Phase 2/3 + auth state.
- `render.yaml` + Deploy-to-Render badge.
- Cascade-delete envs (`?cascade=true`).
- AI prompts include env name.
- Dashboard breadcrumb shows active env pill.

Commits: `859eb7c`, `688e07d`, `f37cc01` (screenshots)

---

## 2026-06-11 — Phase A: login + signup + sessions

### Added
- `users` + `user_sessions` tables. Bcrypt password hashing via
  passlib. Server-side sessions with sliding 30-day expiry, hard-capped
  at 60 days from creation.
- `/auth/{signup,login,logout,me}` endpoints. First user becomes admin.
- `AuthProvider` wraps the app, fetches `/auth/me`, redirects unauthed
  users to `/login`.
- `UserMenu` in sidebar header.

### Changed
- `AUTH_USER`/`AUTH_PASS` env vars now seed the first admin on initial
  boot (email = `<user>@local` if not already an email) and become
  unused after that. Phase A deliberately kept the API callable without
  auth — closed in Phase A.5 the next day.

Commits: `43d22f5`

---

## 2026-06-11 — Multi-environment

### Added
- Connect to multiple Airflow instances at once; data fully scoped per
  env. `environments` table seeded from existing `AIRFLOW_*` env vars on
  first migration.
- `environment_id` (NOT NULL FK) added to 8 historical/config tables.
- `dag_runs` uniqueness changed from `(run_id)` to `(environment_id,
  run_id)` — two Airflow instances can independently emit the same
  `dag_run_id`.
- 5 new endpoints `/environments[/{id}][/test]`.
- Frontend `EnvSwitcher` in sidebar header, `EnvironmentsCard` in
  Settings, `setActiveEnv()` / `withEnv()` wrapper threads `?env=<name>`
  into every API call.
- Pinned DAGs localStorage now keyed `pipelinepulse:pinned-dags:<env>`.

Commits: `854d424` (backend), `b09d025` (frontend)

---

## 2026-06-11 — Run annotations

### Added
- Single editable note per run (PUT empty deletes). Three surfaces:
  AnnotationPanel inside Failure analysis card; sticky-note badge in
  runs table; auto-included in `top_failures` section of reports.
- New `run_annotations` table (PK `dag_id+run_id`).

### Fixed
- AnnotationPanel was reverting edits on parent re-renders due to
  `onChange` in the load-effect deps + `key={...}` force-remounting.

Commits: `3576e50`, `0fdf026`

---

## 2026-06-11 — Run-vs-run diff baseline picker

### Added
- Generalized existing diff endpoint with optional
  `?baseline_dag_id=&baseline_run_id=` query params (cross-DAG
  supported); default behavior preserved.
- Frontend `DiffPanel` gets a popover baseline picker with shortcut
  buttons (Last success, Previous run), DAG dropdown, and run list.
- Diff panel now shown for any selected run, not just failures.

Commit: `c25e6a5`

---

## 2026-06-10 — Sidebar DAG filter

### Added
- Substring filter over the DAG list (both pinned and unpinned).
- `/` keyboard shortcut to focus, Esc to clear.
- Match count + empty state.

Commit: `d591363`

---

## 2026-06-10 — SLA tracking

### Added
- Per-DAG SLA config: daily wall-clock deadline (with IANA tz) +
  absolute `max_runtime_seconds`.
- New `backend/sla.py` is a pure evaluator (no DB/HTTP coupling).
- Storage in `dag_sla_configs` table.
- `_check_sla_breaches` APScheduler job (every 2 min), fires via
  notifications table with event `sla_deadline_missed`/`sla_max_runtime`.
  Honors existing mute/quiet hours from `dag_alert_configs`.
- 4 endpoints: `GET/PUT /sla/configs[/{dag_id}]`, `GET /sla/at-risk`,
  `GET /sla/breaches?range=`.
- Reports gained "SLA performance" section.
- UI: SlaConfigPanel auto-saving table, SlaAtRiskBanner above
  StuckRunsBanner, Clock badge on breached runs.

Commit: `290d18d`

---

## 2026-06-10 — Settings view (Phase 2 #3)

### Added
- New `backend/settings.py` is a key-value DB-overrides-env helper
  (5s TTL cache); high-frequency call sites read through it.
- `gemini` global became a lazy `get_gemini()` cache keyed by
  `(api_key, model)`.
- APScheduler `sync_airflow_data` job got an `id=` and is re-scheduled
  in-place on `sync_interval_minutes` change via a `register_scheduler()`
  callback.
- Endpoints: `GET/PUT /settings`, plus 4× `/settings/danger/*` (reset
  alert configs, clear notifications, clear reports, full re-sync).
- Frontend SettingsView with Integrations / Sync / Stuck / Appearance /
  Danger zone cards. Secrets render as `••••••••` with Replace/Clear.
  Danger actions need typed DELETE confirmation.

Commit: `cfc71b3`

---

## 2026-06-10 — Reports

### Added
- Markdown / HTML / PDF (WeasyPrint) snapshots of 7d/30d.
- On-demand `/reports?range=&format=`, history (`/reports/history`),
  schedule (`/reports/schedule`) with weekly/monthly cron via
  APScheduler 15-min check.
- AI narrative (Gemini) optional.
- Webhook delivers a *link* back to the app via `PUBLIC_BASE_URL`, not
  the file itself.
- New module `backend/reports.py`, Jinja template at
  `backend/templates/report.html.j2`. Self-contained HTML (inline CSS +
  inline SVG).
- Two new tables: `report_runs`, `report_schedules`.

Commit: `877f12b`

---

## 2026-06-10 — UI polish pass

### Changed
- Animated metric tiles with sparklines + accent borders.
- New `HealthStrip` (24h per-DAG run-history bars).
- Reusable `EmptyState` component.
- Brand + sidebar CSS tokens, framer-motion entry animations.
- Surfaces `upstream_failed` state.

Commit: `c94e455`

---

## 2026-06-09 — Analytics view (Phase 2 #1)

### Added
- `/analytics?range=7d|30d` endpoint with prior-period delta tiles,
  failure-rate trend line, slowest + most-failure-prone rankings,
  busy-hours histogram.
- Sidebar nav switches main pane via `view` state (Dashboard /
  Analytics / Reports / Settings).

Commit: `4b2a34a`

---

## 2026-06-09 — Phase 1 dashboard features

### Added
- Stuck-run detection (running > 2× p95).
- Pin/favorite DAGs in sidebar (localStorage).
- Date range filter + pagination on `/runs/{dag_id}`
  (`?range=24h|7d|30d|all`).
- Re-trigger run button (POST to Airflow `/dagRuns`).
- "What changed?" diff panel (last-success vs current-failed).
- Per-DAG alert config (mute, threshold, quiet hours).

Commits: `eaabac9`, `f4ffc16`, `c3a719a`, `5853d8a`, `70436a7`,
`999fed9`

---

## 2026-06-09 — PipelinePulse open-source release

Initial public release on GitHub. Backend (FastAPI + APScheduler +
Postgres), frontend (Next.js 15 + Tailwind + Recharts), full Docker
Compose stack with sample DAGs. AI failure analysis (Gemini, optional),
webhook alerts, HTTP basic auth, captured task errors, run history.

Commit: `713076f` (public release), with prior commits squashed during
the OSS conversion.
