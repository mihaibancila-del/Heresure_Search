# CHANGELOG

[EN] Dated record of structural changes, why they were made, and anything a
future reader would otherwise have to reverse-engineer. Split out of `AGENTS.md`
§5 when that file approached the 500-line rule. Newest first.

[RU] Датированная запись структурных изменений, их причин и всего, что иначе
пришлось бы восстанавливать по коду. Вынесено из §5 `AGENTS.md`, когда тот файл
приблизился к лимиту в 500 строк. Новые сверху.

---

### 2026-08-19 — one app timezone for schedule and display

Times in the UI were printed as raw `timestamptz`, which psycopg2 returns in the
session zone (Etc/UTC), while the schedule ran in a named local zone. The imports
page therefore showed "Scheduled daily at 09:45" next to a run started "06:46" —
the same instant, two zones, on one page.

- `import_settings.schedule_timezone` renamed to `timezone`: it now decides both
  when the schedule fires and how every timestamp is displayed. Guarded `DO` block
  in `sql/create_imports_tables.sql` renames it on existing databases (Postgres has
  no `RENAME COLUMN IF EXISTS`); the file stays safe to re-run.
- New `in_tz` Jinja filter (`app/views/filters.py`). All seven timestamp sites now
  use it — imports history and status, import settings, admin users' last sign-in,
  and the scheduler warning, which had "UTC" hardcoded.
- Timezone moved out of the Schedule panel into its own panel on
  `/imports/settings`, because it governs the whole app rather than just the
  schedule. `POST /imports/settings/timezone` added; the schedule form now saves
  only the on/off flag and the time.
- Pages state the zone explicitly ("All times in Europe/Bucharest", "Last sign-in
  (Europe/Bucharest)") so no number is ambiguous.
- Poll interval tightened from 15 minutes to **every minute** (systemd
  `OnCalendar=*:*`, `RandomizedDelaySec=0`) and 60s to 30s in compose, so a slot
  starts within about a minute of its time instead of up to 15. Both the header and
  the settings page now say the start is "within a minute", not exact.
- Verified: filter unit checks (UTC→Bucharest/New York, naive input, unknown zone
  fallback), then every run on the live page asserted to show its local time and
  NOT its UTC time. Suites re-run: 43 model/schedule, 37 HTTP/permission, 47 auth.

### 2026-08-18 — UI-driven imports: trigger, filters, schedule, history (VOC-13/14/18)

Imports were a single hardcoded ETL on a fixed systemd timer, with no record of
what had run. They are now configurable and visible from the app.

- **New:** `sql/create_imports_tables.sql`, `app/import_catalog.py`, `app/jobs.py`,
  `app/models/imports.py`, `app/controllers/imports.py`, `scripts/run_import.py`,
  `app/templates/imports.html`, `app/templates/import_settings.html`,
  `app/static/css/imports.css`, and `to_duration` in `app/views/filters.py`.
- **VOC-13** "Run import now" on `/imports` (admin), spawned as a detached
  subprocess; the page auto-refreshes while a run is active and shows the log tail.
- **VOC-14** County and license-type filters on `/imports/settings`. The seeded
  values reproduce the old hardcoded sets *exactly* (verified: all 71 city
  spellings, same 4 license types), so applying this changes no behaviour until
  someone edits them. Palm Beach is available to opt into.
- **VOC-18** Schedule (enable, time, IANA timezone) stored in `import_settings`.
  `agent-licence-parser.timer` now polls every 15 minutes running
  `run_import --if-due` instead of firing the parser at a fixed 09:00.
- **New feature** `/imports` run history: status, trigger, who started it,
  duration, rows scanned/matched/inserted, the filters used, and the error. Any
  signed-in user can read it; only admins can run or reconfigure.
- `scripts/parser.py` lost its module-level `LIFE_DESCS`/`*_CITIES` constants;
  `filter_and_transform()` takes the filters as arguments and reports totals
  through a `counts` dict. `main()` delegates to `run_import` so a hand-run import
  is recorded like any other.
- Also fixed: a CSRF failure from an expired session returned a bare 400 on every
  form in the app; it now redirects to login with an explanation (a mismatch while
  signed in still returns 400).
- Added `import_settings.last_poll_at` plus a `scheduler` compose service after
  discovering that an enabled schedule silently never fired locally — compose has
  no systemd, so nothing was polling it.
- **⚠️ Server action required:** the systemd units changed, and units are not
  rsynced (see §4) — reinstall both and `daemon-reload`, or the old 09:00
  `-m scripts.parser` command keeps running. Also apply
  `sql/create_imports_tables.sql` to the existing database.
- Verified against a throwaway database (never the compose one the app uses):
  37 model/schedule checks, 34 HTTP/permission checks, a full runner run with the
  download stubbed (including the real psql load, idempotent re-run, empty-filter
  refusal and lock contention), plus the 47 VOC-12 auth checks re-run for regression.

### 2026-08-18 — invite-only login (VOC-12)

The site had **no authentication at all**: `BASIC_AUTH_USERS` was unset in `.env`,
and both `deploy/README.md` and `provision.sh` instructed the operator to leave it
that way, so ~64k real agent records were served to anyone with the URL. Replaced
with session login, invite only.

- **New:** `app/security.py`, `app/models/user.py`, `app/controllers/auth.py`,
  `app/controllers/admin.py`, `app/views/csrf.py`, `sql/create_users_table.sql`,
  `scripts/manage_users.py`, and the `base.html` / `login.html` /
  `accept_invite.html` / `admin_users.html` templates.
- **Removed:** `require_auth` and `BASIC_AUTH_USERS`. `app/views/auth.py` was
  rewritten as session helpers + `PUBLIC_ENDPOINTS` + `admin_required`.
- Access control moved from a per-route decorator to one app-wide
  `before_request`, which also CSRF-checks every POST. Default deny.
- `SECRET_KEY` is now required; `create_app()` fails fast on it like `PGPASSWORD`.
- Session cookie: `HttpOnly`, `SameSite=Lax`, `Secure` (configurable), 14-day
  permanent lifetime so a login survives a browser restart.
- No new dependencies — hashing is `werkzeug.security` (bundled with Flask).
- Compose gained a `02_create_users_table.sql` initdb mount and a dev `SECRET_KEY`.
  **Existing databases need the SQL applied by hand** (initdb only runs on a fresh
  volume — see the trap above).
- Verified end-to-end against the compose database with a 47-check script: anonymous
  denial on every route, CSRF rejection, single-use/expired/revoked invites,
  case-insensitive login, wrong-password and unknown-email both 401, open-redirect
  attempts on `?next=`, member vs admin separation, immediate effect of
  deactivation, and last-admin/self-deactivate protection.

### 2026-08-18 — flat layout → MVC

Restructured the project from four root-level Python files into the layout in
§2. The largest Python file went from 493 lines to 294, and the rendered HTML
is byte-identical to before apart from `<style>`→`<link>` and inline→external
`<script>` (verified by diffing both versions against the same database).

- `app.py` (493 lines) split into `wsgi.py` + nine files under `app/`. The
  275-line inline HTML string became `app/templates/index.html` +
  `app/static/css/main.css` + `app/static/js/main.js`;
  `render_template_string` → `render_template`.
- `parser.py`, `send_campaign.py`, `send_test_email.py` → `scripts/` (git
  tracked these as renames, so history is intact).
- `create_table.sql`, `load_script.sql`, `dedupe_licenses.sql` → `sql/`.
- Four duplicate copies of `load_env()` and three of `get_required()` collapsed
  into `app/config.py`.
- **Bug fixed:** `send_campaign.py` read `PGHOST`/`PGPORT`/`PGUSER`/
  `PGDATABASE` at import, *before* its own `load_env()` ran in `main()`, so
  `.env` was silently ignored for those four and it always hit
  `localhost:5432/postgres`. It now honours `.env` — which means it may target
  a **different database than before**. Always `--dry-run` first.
- CWD-relative paths in `parser.py` anchored to `PROJECT_ROOT`; psql subprocess
  given `cwd=` so the `\copy` works from any directory.
- Entry point `app:app` → `wsgi:app`: updated in `Dockerfile`,
  `deploy/agent-licence.service`. `deploy/agent-licence-parser.service` now runs
  `-m scripts.parser`. Compose mount → `./sql/create_table.sql`.
  `deploy/update.sh` gained `--delete` plus a `__pycache__` cleanup.
- `README.md`, `deploy/README.md`, `.env.example` updated. `deploy/README.md`
  gained a one-time server-migration section (reinstall both units and
  `daemon-reload`, or gunicorn loads `app:app`, dies, and nginx returns 502).

### Outstanding / known gaps

- **No tests.** Verification is end-to-end and manual; see §2 and the
  verification section of `deploy/README.md`. Highest-value first tests: the
  anonymous-redirect / signed-in-200 pair (guards `PUBLIC_ENDPOINTS`), invite
  single-use, and `to_tel_href` units. The VOC-12 work was verified with a
  throwaway curl script; it was not kept, because a `tests/` directory needs the
  `pyproject.toml` decision above to be revisited first.
- **No password reset** (VOC-19). Recovery today is: deactivate the account, then
  issue a fresh invite. `scripts/manage_users.py set-password` is the admin-side
  equivalent.
- **No login rate limiting.** Brute force is bounded only by scrypt's cost. Fine
  for an invite-only tool behind nginx, but a `failed_attempts`/`locked_until`
  pair on `users`, or a limit in nginx, would be the next hardening step.
- **A running import cannot be cancelled from the UI.** There is no stop button and
  no PID stored; you have to kill the process on the server, after which the
  heartbeat goes stale and the run is closed as failed within 5 minutes.
- **A scheduled import starts up to a poll interval late** — about a minute in
  production, `IMPORT_POLL_SECONDS` (30s) in compose. It is not exact by design; see
  the decision on not writing cron config from the app. Only one daily slot is
  supported: "every N hours" would need a second field and a change to `is_due()`.
- **The timezone is app-wide, not per user.** Everyone sees times in the one zone
  set on `/imports/settings`. A per-user display override would be additive — a
  `users.timezone` column falling back to the app value — and does not require
  changing anything built here.
- **`import_runs.log` grows unbounded.** One row per run holding the whole progress
  log; a few hundred bytes each, so it is not urgent, but nothing prunes old runs.
- **The history page is not paginated** — it shows the newest 50 runs and there is
  no way to reach older ones.
- **Deactivation ends access on the next request, but does not delete the row.**
  There is no account-deletion path; `users` is append-mostly by design.
- `sql/create_table.sql` has no index and no unique constraint on the dedupe key
  (`"Full Name"` + `"Business Email"`), so the anti-join in `load_script.sql`
  does the work.
- The "Send Email" button is still a stub — it only shows a toast. Wiring it up
  is the next feature, and is why the blueprint seam exists.
- A password (`1560`) is in git history; rotated on the server but not purged
  from history. See the end of `deploy/README.md`.
