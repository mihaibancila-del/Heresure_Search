# Agent Licence — Florida DFS License Tracker

Internal tool that tracks Florida DFS-licensed insurance agents (life /
life & health) in Broward and Miami-Dade counties: pulls the public
license registry on a schedule you control from the UI, stores it in Postgres,
and exposes a web viewer + an outreach-email sender for the team.

This document is a technical overview for engineers picking up or
maintaining the project. For the step-by-step ops runbook (provisioning
a server, migrating the database, updating a live deployment), see
[`deploy/README.md`](deploy/README.md).

## What it does

1. **Data pull** — `scripts/run_import.py` downloads Florida DFS's public
   license CSV, filters it to the counties and license types selected in the
   UI, and inserts only the *new* ones into Postgres with `checked = false`.
   Existing rows (and anything staff manually set, like `checked` or
   `Personal Email`) are never touched. Runs on demand or on a schedule, and
   every run is recorded on `/imports`.
2. **Web viewer** — the Flask app in `app/` shows the `licenses` table,
   paginated, with a filter for `All / Checked / Not checked` and a
   per-row "Send Email" action (currently a UI stub).
3. **Outreach** — `scripts/send_campaign.py` sends one email at a time (single
   recipient per message, rate-limited) to agents where
   `checked = false` and a business email is on file, then flips
   `checked = true` right after each successful send so re-running the
   script never double-sends.

## Architecture (production)

```
                     ┌─────────────────────────────────────────┐
                     │   DigitalOcean droplet (Ubuntu 22.04)    │
                     │                                           │
  Internet ──HTTPS──▶│  nginx :443 ──▶ gunicorn :8000 ─▶ wsgi:app │
                     │      (Let's Encrypt via certbot)          │
                     │                          │                │
                     │                          ▼                │
                     │                   Postgres (local)        │
                     │                     licenses table         │
                     │                          ▲                │
                     │                          │                │
                     │   systemd timer (polls every minute)      │
                     │    └─▶ scripts.run_import --if-due          │
                     │        (schedule + filters read from the DB)│
                     └─────────────────────────────────────────┘
```

- **App process**: `gunicorn` running `wsgi:app`, managed by systemd unit
  `agent-licence.service` — restarts automatically on crash or reboot.
- **Reverse proxy**: nginx terminates TLS and forwards to gunicorn on
  `127.0.0.1:8000` (app itself is never exposed directly).
- **TLS**: a real Let's Encrypt certificate, auto-renewing. No domain was
  purchased — the site is reachable via a free `sslip.io` hostname that
  resolves to the droplet's IP (see `deploy/server.env`, not in git).
- **Scheduled data refresh**: systemd timer `agent-licence-parser.timer` polls
  every minute and runs the import when the schedule set in the app says it is due
  (enable/time on `/imports/settings`, in the app timezone, DST-aware). It's
  independent of anyone's laptop being on.
- **Firewall**: `ufw` — only SSH (22) and HTTP/HTTPS (80/443) are open.
- **Access**: session login, **invite only**. There is no signup page — an
  admin creates each account on `/admin/users` and passes on a one-time
  link. Every URL except the login and invite pages requires a session.

## Data flow

```
Florida DFS public CSV (~330MB, ~1.2M rows)
        │  scripts/run_import.py: download + filter
        │  (State=FL always; counties + license types from import_settings)
        ▼
staging_licenses.csv
        │  sql/load_script.sql: dedupe within batch, INSERT ... WHERE NOT EXISTS
        │  (match key: Full Name + Business Email — insert-only, never overwrite)
        ▼
licenses table (Postgres)
        │
        ├──▶ app/                     (web viewer + /imports history & settings)
        └──▶ scripts/send_campaign.py (reads checked=false rows, emails them, flips checked=true)
```

## Repository layout

| Path | Purpose |
|---|---|
| `wsgi.py` | WSGI entry point — `gunicorn wsgi:app`; also the local dev server |
| `app/` | The Flask application, laid out MVC-style (see below) |
| `app/config.py` | Single source of configuration for the app *and* the scripts: loads `.env`, exposes the Postgres/auth settings |
| `app/security.py` | Password hashing and invite-token primitives (no Flask, no SQL) |
| `app/import_catalog.py` | Counties → city sets, and DFS licence categories → `License TYCL Desc` values; shared by the app and the scripts |
| `app/jobs.py` | Spawns the import runner as a detached subprocess |
| `app/models/` | Data layer — `db.py` (connections), `license.py`, `user.py` (accounts/invites), `imports.py` (settings + run history) |
| `app/controllers/` | Request layer — `licenses.py` (`/`), `auth.py` (login/invite + the app-wide guard), `admin.py` (`/admin/users`), `imports.py` (`/imports`) |
| `app/views/` | Presentation helpers — `auth.py` (`PUBLIC_ENDPOINTS`, session helpers, `admin_required`), `csrf.py`, `filters.py` (Jinja filters) |
| `app/templates/` | Jinja templates — `base.html` plus the table, login, invite, users and imports pages |
| `app/static/` | `css/main.css` (shared) + `css/imports.css` (page-specific), `js/main.js` |
| `scripts/run_import.py` | **The** import entry point: run tracking, advisory locking, `--if-due` scheduling |
| `scripts/parser.py` | ETL primitives used by the runner: download → filter (filters passed in) → load |
| `scripts/manage_users.py` | CLI accounts: bootstrap the first admin, invite, deactivate |
| `scripts/audit_license_types.py` | Checks the licence-category mapping against the live registry; fails on any unmapped licence class |
| `scripts/send_campaign.py` | Rate-limited, one-recipient-per-email outreach sender; marks `checked = true` after each send |
| `scripts/send_test_email.py` | Sends one test email to yourself to verify SMTP creds work |
| `sql/load_script.sql` | Insert-only-new logic used by `scripts/parser.py` (staging table → `licenses`) |
| `sql/create_table.sql` | `licenses` table schema |
| `sql/create_users_table.sql` | `users` table schema (accounts + pending invites) |
| `sql/create_imports_tables.sql` | `import_settings` (filters + schedule) and `import_runs` (history) |
| `sql/dedupe_licenses.sql` | One-off maintenance: collapse existing duplicate rows (same Full Name + Business Email) |
| `requirements.txt` | Python dependencies |
| `.env.example` | Template for local `.env` (DB creds, SMTP creds, `SECRET_KEY`, session settings) — copy, fill in, never commit |
| `deploy/` | Everything needed to stand up or update the production server — see `deploy/README.md` |

Not part of the running app (kept on disk for history, gitignored,
superseded by `scripts/parser.py` which does download+filter+load in one
scheduled step): `filter_life_licenses.py`, `load_to_db.py` — an older
two-step manual version of the same pipeline.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # fill in PGPASSWORD (and SMTP_* if testing email)

python3 wsgi.py         # http://127.0.0.1:5000
```

The scripts are run as modules, always from the repository root, so that
`import app.config` resolves:

```bash
python3 -m scripts.run_import                          # download + filter + load
python3 -m scripts.send_campaign --dry-run --limit 3   # show recipients, send nothing
python3 -m scripts.send_test_email                     # verify SMTP creds
```

Requires a local Postgres with all three schemas applied
(`sql/create_table.sql`, `sql/create_users_table.sql`,
`sql/create_imports_tables.sql`), an admin account (see **Accounts and login**),
and `PGPASSWORD` + `SECRET_KEY` set — see `.env.example`. Then load data with
`python3 -m scripts.run_import`, or press **Run import now** on `/imports`.

Or skip all of that and use the container stack, which creates the schemas on a
fresh volume by itself:

```bash
docker compose up -d --build     # app on :8000, Postgres on 5434, scheduler
docker compose exec app python3 -m scripts.manage_users \
    set-password you@example.com --role admin
```

The stack has three services: `app`, `db`, and `scheduler`. The scheduler is what
makes a saved schedule actually fire — it runs the same
`run_import --if-due` command the systemd timer runs on the server, in a loop.
It polls every `IMPORT_POLL_SECONDS` (default **30s** locally; production polls
every minute via systemd), so a schedule you set is picked up promptly:

```bash
IMPORT_POLL_SECONDS=15 docker compose up -d scheduler   # even snappier
docker compose logs -f scheduler                        # watch it decide
```

## Imports

The `licenses` table is filled from the Florida DFS registry. Everything about
that is driven from the app, and every run is recorded.

- **`/imports`** — run history: status, what triggered it, who started it,
  duration, rows scanned / matched / newly inserted, the filters used, and the
  error if it failed. Readable by any signed-in user. Admins also get a
  **Run import now** button; the page auto-refreshes while a run is in progress
  and shows the last few log lines.
- **`/imports/settings`** (admin) — the **timezone**, which **counties** and
  **licence categories** to import, and the **daily schedule** (on/off, time).

Licence categories are the ones the DFS licensee-search form offers (Life &
Annuity, Health, Adjuster, Property & Casualty, …). Each expands to the underlying
`License TYCL Desc` values in the export — the count is shown next to each
checkbox. Three categories (Insurance Agency, Adjusting Firm, Debit Agent) are
organisations rather than individuals, so they are listed but disabled.

The timezone is app-wide and does two jobs: the schedule fires by it, and **every
time shown anywhere in the app is rendered in it**. A scheduled import starts on
the first check after its time — checks run every minute — so a 09:45 schedule
begins by about 09:46, not exactly at 09:45.

The app cannot start itself on a timer, so a schedule only fires if something
polls it: the `scheduler` compose service locally, or the
`agent-licence-parser.timer` systemd unit on the server. Both run the same
command. If nothing has polled recently, `/imports` shows a warning rather than
letting an enabled schedule silently do nothing.

The import is insert-only-new: it never overwrites or deletes existing rows, so
manually-set `checked` / `Personal Email` values are safe, and narrowing the
filters does not remove rows already imported.

From the command line (identical code path, also recorded in the history):

```bash
python3 -m scripts.run_import                               # run now
python3 -m scripts.run_import --trigger scheduled --if-due  # obey the schedule
```

Two runs can never overlap — the runner holds a Postgres advisory lock, and a
second attempt exits immediately. A run whose process is killed is closed out as
`interrupted` within 5 minutes rather than blocking future imports.

Requires the `psql` binary (the loader uses `\copy`); set `PG_BIN` in `.env` if it
is not on `PATH`.

## Configuration

All configuration is environment-based via `.env` (see `.env.example`
for the full list): Postgres connection (`PGHOST`/`PGPORT`/`PGUSER`/
`PGDATABASE`/`PGPASSWORD`), SMTP creds for outreach, and `SECRET_KEY`
for the login session cookie. Import filters and the schedule are **not** in
`.env` — they live in the database and are edited at `/imports/settings`. No secret has a hardcoded default in code —
the app refuses to start without `PGPASSWORD` **or** `SECRET_KEY` set.

## Accounts and login

Access is invite-only; there is no signup page. A row in the `users` table
is the only way in.

Create the first admin (a fresh database has no users, so this cannot be
done in the UI):

```bash
python3 -m scripts.manage_users set-password you@example.com --role admin
```

After that, invite people from **/admin/users** in the web UI. Creating an
invite shows a one-time link — no email is sent, you pass it on yourself.
The invited person sets their own password from that link, so you never
handle their password. Links expire after `INVITE_TTL_HOURS` (default 72)
and work once.

The same script covers the cases the UI cannot:

```bash
python3 -m scripts.manage_users list
python3 -m scripts.manage_users invite bob@example.com --base-url https://your-host
python3 -m scripts.manage_users deactivate bob@example.com
```

Password reset by email is not built yet — to recover an account today,
deactivate it and issue a fresh invite.

## Security notes

- **PII**: the `licenses` table contains real names, emails, phone
  numbers, and mailing addresses of licensed individuals. Treat exports,
  dumps, and server access accordingly.
- **Secrets** live only in `.env` (gitignored) and, in production, in
  `/opt/agent_licence/.env` on the server (mode `600`). They are never
  committed.
- **Server identity** (droplet IP, live site URL) lives in
  `deploy/server.env` (gitignored) — copy `deploy/server.env.example`
  and fill it in locally; get the real values from whoever currently
  operates the server, not from git.
- **Known history issue**: an early commit had a Postgres password
  hardcoded as a fallback default in three scripts. It has since been
  removed from the code and rotated on the server, but it still exists
  in the git history of this repository. If that password was ever
  reused anywhere else, rotate it there too.
- **Authentication** is invite-only session login, applied by default to
  every endpoint: a single `before_request` hook denies anything not in
  `PUBLIC_ENDPOINTS` (login, invite acceptance, static assets), so a new
  route cannot accidentally ship unprotected. Passwords are scrypt-hashed;
  invite tokens are stored only as sha256. Set `SESSION_COOKIE_SECURE=true`
  in production.
- `app/static/` is served **without** authentication. Never put anything
  sensitive there.

## Operations

See [`deploy/README.md`](deploy/README.md) for: provisioning a new
server, migrating the database, the systemd units, nginx/TLS setup, the
daily parser timer, and the one-command update flow (`deploy/update.sh`).

## License

All rights reserved — see [`LICENSE`](LICENSE). Copyright © 2026 Leila
Chernova (leila.studio). Viewing the source for personal, educational
purposes is permitted; any other use (running, deploying, copying,
modifying, redistributing) requires prior written permission from the
owner.
