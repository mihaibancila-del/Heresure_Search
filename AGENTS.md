# AGENTS.md

Working notes for AI agents on this project. Read this before making changes.

---

## 1. Instructions to follow

### 🚨 Hard rule: no file over 500 lines

**Never leave a file longer than 500 lines.** If a change produces a file over
500 lines, it MUST be refactored — split it along a real seam (a layer, a
responsibility, a feature), not at an arbitrary line number. This applies to
every file: Python, HTML, CSS, SQL, shell, config, docs.

Current state — the longest file is **this one**, at ~476 lines, so it is the next
thing that must be split: the obvious seam is moving §5 Changes into a separate
`CHANGELOG.md` and leaving §1–§4 here. Do that before adding another entry.
Second longest is `app/static/css/main.css` at 371 — which is why page-specific CSS
now goes in its own stylesheet via the `styles` block in `base.html` (see
`imports.css`) rather than growing the shared one. Check before you finish:

```bash
find . -path ./.git -prune -o -name '__pycache__' -prune -o -type f \
  \( -name '*.py' -o -name '*.html' -o -name '*.css' -o -name '*.js' -o -name '*.sql' -o -name '*.sh' -o -name '*.md' -o -name '*.yml' \) \
  -print0 | xargs -0 wc -l | sort -rn | head -10
```

### Other conventions

- **Bilingual comments.** Every docstring, comment block and doc section is
  written `[EN]` then `[RU]`. Match this in anything you add or edit — the
  project is read by both an English- and a Russian-speaking maintainer. Do not
  drop the RU half when editing an existing block.
- **No new dependencies without asking.** `requirements.txt` is deliberately
  four lines (Flask, psycopg2-binary, gunicorn, requests). In particular the
  `.env` parser is hand-rolled on purpose — do **not** add `python-dotenv`.
- **Run scripts as modules from the repo root**: `python3 -m scripts.parser`,
  never `python3 scripts/parser.py`. A direct path puts `scripts/` on
  `sys.path[0]` instead of the repo root, and `import app.config` dies with
  `ModuleNotFoundError`.
- **Config goes in `app/config.py` only.** Never re-add a local `load_env()` or
  a second place that reads `PGHOST`/`SMTP_*`. That duplication (4 copies) is
  what this layout removed.
- **Never commit or push unless asked.** The working tree usually carries
  uncommitted edits from the maintainer; leave them alone.
- **Linear project.** All Linear issues for this repo belong to the
  **Heresure-Agent-Search** project on team Vocaledgesolutions. Always set
  `project` when creating or updating an issue; never leave one project-less.

### ⚠️ Real personal data

The `licenses` table holds **real** names, emails, phone numbers and mailing
addresses of Florida insurance agents. Therefore:

- Do not paste query results, CSV rows or dumps into chat, logs, commits or
  issue text. Report counts and shapes, not records.
- `AllValidLicensesIndividual.csv`, `staging_licenses.csv`, `*.dump` and `.env`
  are gitignored **and** dockerignored. Keep them that way.
- **Never send a live email.** `scripts/send_campaign.py` and
  `scripts/send_test_email.py` contact real people. Verify with
  `--dry-run` only, and ask the maintainer before any real send. The web app
  itself has no mail capability at all, deliberately — invites are copy-paste
  links, not emails.
- The whole site is behind an **invite-only session login**. Access is default
  deny: one `before_request` hook in `create_app()` requires a session for every
  endpoint not named in `PUBLIC_ENDPOINTS` (`app/views/auth.py`). Never add an
  endpoint to that set without checking what it renders, and never disable the
  hook to "test something" — the page serves real personal data.

---

## 2. Project structure

MVC-style Flask app plus standalone operational scripts.

```
wsgi.py                       WSGI entry point — `gunicorn wsgi:app`; also the dev server
app/
  __init__.py                 create_app() factory; registers THE auth before_request
  config.py                   THE config module: loads .env, exposes PG_*/session settings
  security.py                 password hashing + invite token primitives (no Flask, no SQL)
  import_catalog.py           counties -> city sets, license types (shared with scripts/)
  jobs.py                     spawns the import runner as a detached subprocess
  models/
    db.py                     psycopg2 connection + connection() context manager
    license.py                every SQL statement the web app runs against `licenses`
    user.py                   every SQL statement about accounts and invites
    imports.py                every SQL statement about import settings and run history
  controllers/
    licenses.py               the `/` route, as a Flask blueprint
    auth.py                   /login, /logout, /invite/<token>, and the app-wide guard
    admin.py                  /admin/users — invite, revoke, deactivate (admin only)
    imports.py                /imports history (all users) + run/filters/schedule (admin)
  views/
    auth.py                   PUBLIC_ENDPOINTS, session helpers, admin_required
    csrf.py                   hand-rolled synchroniser-token CSRF for all POSTs
    filters.py                to_tel_href + to_duration, registered as Jinja filters
  templates/base.html         shared layout: topbar, flashes
  templates/index.html        the paginated table
  templates/login.html        sign-in form
  templates/accept_invite.html  invited user sets their own password
  templates/admin_users.html  account list + invite form
  templates/imports.html      import status + run history
  templates/import_settings.html  county/license filters + schedule
  static/css/main.css         shared base; page CSS goes in its own file (`styles` block)
  static/css/imports.css      imports pages only
  static/js/main.js           toast, invite-link copy, import auto-refresh
scripts/
  parser.py                   ETL primitives: download → filter (filters passed in) → load
  run_import.py               THE import entry point: run tracking, locking, --if-due schedule
  send_campaign.py            one-at-a-time outreach; flips checked = true after each send
  send_test_email.py          SMTP smoke test (no DB)
  manage_users.py             CLI accounts: bootstrap the first admin, invite, deactivate
sql/
  create_table.sql            `licenses` schema; also compose's initdb script
  create_users_table.sql      `users` schema; compose initdb 02_, apply by hand elsewhere
  create_imports_tables.sql   `import_settings` + `import_runs`; compose initdb 03_
  load_script.sql             insert-only-new loader invoked by parser.py via psql
  dedupe_licenses.sql         one-off maintenance, run by hand
deploy/                       provision/update scripts, nginx conf, systemd units, runbook
Dockerfile docker-compose.yml .dockerignore
.env                          NOT in git. Must stay at the repo root (see §4)
```

### Layer boundaries

| Layer | Owns | Must not |
|---|---|---|
| `app/models/` | All SQL, connection lifecycle | Know about requests or HTML |
| `app/controllers/` | Query params, pagination math, choosing a template | Contain SQL |
| `app/views/` + templates | Formatting, session/CSRF helpers, decorators | Query the DB |
| `app/config.py` | Reading `.env` and the environment | Import Flask or any model |
| `app/security.py` | Password/token primitives | Import Flask, touch the DB or a request |
| `app/import_catalog.py` | Filter reference data (counties, types) | Import Flask, touch the DB |
| `app/jobs.py` | Spawning background processes | Import from `scripts/`, contain SQL |
| `scripts/` | Operational one-shots | Be imported by the web app |

Note the consequence for auth: the request guard has to read the `users` row on
every request, which is SQL, so it lives in `app/controllers/auth.py`
(`load_user_and_require_login`) and not in `app/views/auth.py`.

### How things run

```bash
python3 wsgi.py                                       # dev server, http://127.0.0.1:5000
gunicorn -w 2 -b 127.0.0.1:8000 wsgi:app              # production (behind nginx)
python3 -m scripts.run_import                         # import now, recorded in history
python3 -m scripts.run_import --trigger scheduled --if-due   # what the systemd timer runs
python3 -m scripts.parser                             # same as run_import (kept for habit)
python3 -m scripts.send_campaign --dry-run --limit 3  # safe preview
python3 -m scripts.send_test_email                    # SMTP check
docker compose up -d --build                          # full local stack + its own Postgres
```

Compose publishes Postgres on host port **5434** and the app on **8000**. The
maintainer's own `.env` points at port **5435** (a separate local Postgres) —
these are different databases, so know which one you are hitting.

---

## 3. Decisions

Recorded so they are not silently reversed.

- **`app/` package rather than root-level `models/ views/ controllers/`.**
  `Flask(__name__)` inside the package sets `root_path` to `app/`, so
  `app/templates/` and `app/static/` are auto-discovered with no
  `template_folder`/`static_folder` arguments. It is also the layout a Flask
  developer expects. Cost: the package name `app` once collided with the old
  `app.py`, which is why that file was deleted in the same change.
- **Single `app/config.py`, loaded at import.** `load_env(ENV_FILE)` runs once
  when the module is imported, *before* any constant below it is read. That
  ordering is the fix for the old `send_campaign.py` bug (§5).
- **`PGPASSWORD` is a function, not a constant.** `config.pg_password()` is
  read on demand because `send_test_email.py` needs `app.config` for SMTP
  settings but never touches Postgres, and must not be blocked by a missing DB
  password. Fail-fast is preserved by calling it once inside `create_app()`, so
  gunicorn still refuses to boot rather than erroring on the first request.
- **`PROJECT_ROOT = Path(__file__).resolve().parents[1]`.** All data and SQL
  paths are anchored to it, so the scripts behave identically under systemd,
  Docker, and a shell in any directory. `.resolve()` handles symlinked
  checkouts.
- **`to_tel_href` is a Jinja filter, not a controller step.** It formats a
  model field for display, so it belongs to the view layer. This let the
  controller stop writing a presentation key (`phone_href`) into model rows.
- **One DB connection per request, shared by both queries.** The tab counts and
  the visible page must come from the same snapshot; two connections would let
  the counts disagree with the page while `send_campaign.py` writes.
- **The `f"WHERE {where_sql}"` interpolation in `app/models/license.py` stays.**
  It is safe *only* because the value comes from the `STATUS_FILTERS`
  allowlist. `normalize_status()` lives in the same module for exactly this
  reason — keep them together, and never let a raw request value reach it.
- **No `pyproject.toml`.** `python -m` from the repo root covers both systemd
  (`WorkingDirectory=/opt/agent_licence`) and manual runs. Add one if/when a
  `tests/` directory appears and imports need resolving.
- **`base.html` now exists.** The rule was "add a base when a second page
  exists"; login, invite acceptance and the admin page are that second page.
- **Access control is app-wide and default-deny, not per-route.** A single
  `before_request` hook denies every endpoint not in `PUBLIC_ENDPOINTS`. The old
  per-route `@require_auth` was removed because forgetting it — or writing the two
  decorators in the wrong order — silently served real personal data. Adding a
  route now cannot leak it; only editing `PUBLIC_ENDPOINTS` can.
- **An invite IS a user row**, not a separate `invites` table. A pending invite is
  a `users` row with `password_hash IS NULL` and a live `invite_token_hash`.
  "Nobody can self-register" is then true by construction: no row, no access.
- **Invites are copy-paste links, never emails.** The admin page shows the link
  once; the raw token is never stored (only its sha256). This keeps the web app
  incapable of sending mail, so it can never reach the real agents in `licenses`.
- **Passwords use `werkzeug.security` (scrypt), which ships with Flask.** Real
  KDF, and `requirements.txt` stays at four lines. Do not add `bcrypt`,
  `passlib`, `flask-login` or `flask-wtf` — sessions and CSRF are ~200 lines of
  hand-rolled code here for the same reason the `.env` parser is.
- **Invite tokens are stored as a plain sha256, not a KDF.** Correct because a
  token is 256 bits of `secrets` randomness — not guessable from a dictionary —
  and lookups must be indexable. Passwords are the opposite case; don't unify them.
- **`SECRET_KEY` is a function (`config.secret_key()`), not a constant**, for the
  same reason as `pg_password()`: `send_test_email.py` imports `app.config` for
  SMTP only and must not need it. `create_app()` calls it so the web app still
  fails fast.
- **The web app SPAWNS the importer, it does not import it.** `app/jobs.py` runs
  `python3 -m scripts.run_import` as a detached subprocess (`start_new_session=True`).
  This is what lets the web app start an ETL without breaking the §2 rule that it
  must never import `scripts/` — a subprocess is not an import. It also solves two
  real problems: the work takes minutes (far longer than a request), and a detached
  process survives a gunicorn worker restart mid-download. Progress comes back
  through the `import_runs` table, not a return value. Do not "simplify" this into
  a thread.
- **`scripts/run_import.py` is the ONE import entry point.** The UI button, the
  systemd timer and `python3 -m scripts.parser` all end up there, so run history,
  locking and filter handling exist once. `parser.py` is now ETL primitives only
  and holds no filter state; adding a second path that writes `licenses` directly
  would mean imports that never appear in the history.
- **Concurrent imports are blocked with a Postgres ADVISORY LOCK, not a status
  column.** An advisory lock is released automatically when its connection dies,
  so a killed process cannot leave behind a flag that blocks every future import.
  The `status = 'running'` rows are for display, and are separately protected by a
  heartbeat (see the trap below).
- **The import schedule lives in the database, and systemd only POLLS.**
  `agent-licence-parser.timer` fires every 15 minutes and runs
  `run_import --if-due`, which reads `import_settings` and decides. systemd cannot
  read Postgres, so a UI-configurable time can only be honoured by asking often
  enough; 15 minutes is the resulting granularity. `--if-due` compares wall-clock
  time in the stored IANA zone, so 09:00 stays 09:00 across the DST switch — the
  same property the old `OnCalendar=... America/New_York` gave us.
- **Filter selections are stored as NAMES; the name → cities expansion lives in
  code** (`app/import_catalog.py`). The database holds `{Broward, Miami-Dade}`,
  not 71 city strings. A stored name that no longer resolves is reported in the run
  log rather than silently matching nothing. Adding a county is a code change on
  purpose: it needs its municipality list.
- **A CSRF failure with no session redirects to login; with a session it is 400.**
  The check itself stays first and unconditional (see the trap below) — only the
  response is split. An expired session hitting any form is a routine timeout and
  deserves "sign in again", not a bare 400 page; a mismatch while signed in is a
  real anomaly and gets no hint.
- **`user.force_set_password()` is not reachable from the web app.** It exists for
  `scripts/manage_users.py` as the break-glass path when every admin is locked
  out. Keep it out of any controller.
- **`scripts/send_campaign.py` keeps its own psql-based DB access.** Folding it
  into `app/models/license.py` would mix psql-subprocess and psycopg2 access in
  one module. Worth revisiting when the web app grows a real send endpoint.

---

## 4. Traps — things that break silently

Each of these has bitten or nearly bitten this project. None of them raise an
obvious error.

- **Decorator order on routes.** The route must be the OUTER decorator:
  ```python
  @bp.route("/admin/users")   # outer
  @admin_required             # inner
  def users(): ...
  ```
  Flip them and the blueprint registers the *unwrapped* function. This used to
  silently disable authentication entirely; since access control moved to the
  app-wide hook it is less dangerous, but flipping these on an admin route still
  lets **any signed-in member manage accounts**. Only `admin_required` is applied
  this way now.
- **`PUBLIC_ENDPOINTS` is the entire authentication boundary.** Adding a name to
  that frozenset in `app/views/auth.py` makes the page world-readable with no
  error and no warning. Three names belong there; if you find a fourth, be sure.
- **A new `before_request` hook could run before the auth hook.** Flask runs them
  in registration order, and `create_app()` registers the auth hook *before* any
  blueprint on purpose. If you add another `before_request` (or a
  `before_app_request` on a blueprint) that touches `g.user`, check the ordering —
  loading the user and enforcing the login are deliberately one function so they
  cannot be reordered relative to each other.
- **A crashed import leaves a `status = 'running'` row.** Nothing marks it
  finished, because the process that would have is gone. `active_run()` therefore
  ignores rows whose `heartbeat_at` is older than
  `app/models/imports.STALE_AFTER` (5 minutes), and `mark_stale_runs_failed()`
  closes them out when the next run starts. If you lengthen the gap between
  heartbeats in `run_import.py`, raise `STALE_AFTER` too — otherwise a slow but
  healthy import gets declared dead and a second one is allowed to start
  alongside it.
- **`sql/load_script.sql` needs the `psql` binary, so an import cannot run where
  psql is missing.** The container and the server have it; a Mac usually does not,
  which means "Run import now" works in compose but fails from a locally-run
  `python3 wsgi.py` with a `FileNotFoundError` recorded on the run. Set `PG_BIN`
  in `.env` or `brew install libpq` if you need it locally.
- **`filter_and_transform()` is a generator, so its totals come back through the
  `counts` dict, not a return value.** A generator's `return` goes into
  `StopIteration`, which the `for` loop that consumes it swallows. If you need
  scanned/matched counts, pass `counts={}` and read it after the iteration is
  finished — reading it early gives you a partial number.
- **Editing import filters or the schedule changes nothing already in the table.**
  The loader is insert-only-new, so narrowing the counties does not delete rows
  imported under the old selection. Say so when someone asks why the row count did
  not drop.
- **Changing `SECRET_KEY` logs every user out**, including you, with no error —
  the cookies simply stop verifying. Generate it once per environment and leave it.
- **`SESSION_COOKIE_SECURE=true` over plain HTTP looks like "login is broken".**
  The browser accepts the redirect but never stores or returns the cookie, so you
  land back on the login form with no message. Keep it `false` locally, `true` on
  the server.
- **`\copy` in `sql/load_script.sql`** is a *client-side* psql meta-command. Its
  path resolves against psql's own CWD, which `scripts/parser.py` pins with
  `cwd=STAGING_CSV.parent` on the subprocess. psql performs **no variable
  interpolation inside `\copy` arguments**, so `psql -v` + `:'var'` does not
  work — the filename is taken literally. Don't retry it.
- **`.env` must stay at the repo root.** `deploy/dump_db.sh` sources `./.env`,
  and both systemd units use `EnvironmentFile=/opt/agent_licence/.env`. Moving
  a Python file down a directory while keeping a `__file__`-relative `.env`
  path makes `load_env()` a silent no-op — this is why config is centralised.
- **systemd unit files are not in the rsynced tree.** They live in
  `/etc/systemd/system/`. `deploy/update.sh` only restarts the service; it does
  not reinstall units. Change an `ExecStart` and you must `cp` + `daemon-reload`
  on the server or the old command keeps running.
- **`rsync --delete` is required in `deploy/update.sh`** so files deleted
  locally also disappear from the server. It is safe because rsync never
  deletes receiver files matched by an `--exclude` (`.env`, `.venv/`, the dumps,
  the big CSVs are all protected). **Never add `--delete-excluded`** — that
  would wipe the server's `.env` and virtualenv.
- **`docker compose` initdb only runs on a fresh volume.** A wrong
  `./sql/create_table.sql` mount path makes Compose create a *directory* there
  and silently skip table creation. Test with `docker compose down -v` first.
- **`fetchall()` must happen inside the cursor/connection scope.** Returning a
  cursor, or closing the connection before the template iterates, yields an
  empty table with no error.
- **`/static/*` is unauthenticated.** Basic Auth covers the route, not Flask's
  static endpoint. Fine today (only CSS and a toast function). Never put
  anything sensitive under `app/static/`.

---

## 5. Changes

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
- **Import schedule granularity is 15 minutes**, set by the timer's poll interval,
  and only one daily slot is supported. "Every N hours" would need a second field
  and a change to `is_due()`.
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
