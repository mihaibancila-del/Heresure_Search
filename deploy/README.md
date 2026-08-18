# Deploying to DigitalOcean

Step-by-step guide: a new droplet, migrating the entire current local database,
and team access via login/password over HTTPS.

## 0. What's already in the repository

- `wsgi.py` + `app/` — the Flask app, served as `wsgi:app`. Config (DB, auth)
  is read from `.env` by `app/config.py`; there's no longer a default database
  password.
- `scripts/` — `run_import.py` (the import entry point), `parser.py` (its ETL
  primitives), `send_campaign.py`, `send_test_email.py`, `manage_users.py`.
  Run as modules from `/opt/agent_licence`, e.g. `python3 -m scripts.run_import`.
- `sql/` — `create_table.sql`, `create_users_table.sql`,
  `create_imports_tables.sql`, `load_script.sql`, `dedupe_licenses.sql`.
- `requirements.txt` — dependencies for the server.
- `deploy/provision.sh` — one-time setup of a clean droplet (Postgres, nginx,
  firewall, system user, Postgres role and database).
- `deploy/dump_db.sh` — locally: dumps the current database.
- `deploy/restore_db.sh` — on the server: restores the dump into the database.
- `deploy/agent-licence.service` — systemd unit (gunicorn).
- `deploy/nginx.conf` — reverse proxy + a TLS stub.

## 1. Create a droplet

In the DigitalOcean panel (or `doctl compute droplet create`, if you install
`doctl` and authenticate with a token):

- Image: **Ubuntu 22.04 (LTS) x64**
- Plan: Basic, 1 GB RAM / 1 vCPU is enough for this app
- Region: closest to you/your team
- Authentication: **SSH key** (not password)
- Add the droplet to the same VPC/project as your other servers, if that matters

After creation, note the **droplet's IP** — you'll need it later.

## 2. First login and bootstrap

```bash
ssh root@<DROPLET_IP>
```

On the server:

```bash
git clone https://github.com/Leillaa/Heresure_Search.git /root/repo-tmp
cp -r /root/repo-tmp/deploy /root/deploy
cd /root/deploy

# make up a password for the app's DB role, e.g.:
openssl rand -base64 24
# save it — you'll need it in step 4

bash provision.sh '<PASSWORD_FROM_THE_PREVIOUS_LINE>'
```

The script installs Postgres/nginx/python, enables the firewall (only
SSH + 80/443 open), creates the system user `agentapp`, the role
`agents_app`, and an empty database `Agents_Heresure`.

## 3. Upload the application code

The easiest way is the same git (the repo is private/public, but remember: its
history already exposed the old password `1560`, see the warning below):

```bash
sudo -u agentapp git clone https://github.com/Leillaa/Heresure_Search.git /opt/agent_licence
cd /opt/agent_licence
sudo -u agentapp python3 -m venv .venv
sudo -u agentapp .venv/bin/pip install -r requirements.txt
```

Create `.env` at `/opt/agent_licence/.env` (owner — `agentapp`,
permissions `600`), based on `.env.example`:

```bash
sudo -u agentapp cp .env.example .env
sudo -u agentapp nano .env
```

Fill in:
- `PGUSER=agents_app`, `PGDATABASE=Agents_Heresure`, `PGPASSWORD=<password from step 2>`
- `SMTP_*` — if you'll run the campaign from the server too
- `SECRET_KEY` — **required**, the app will not start without it. Generate one
  on the server and never change it afterwards (changing it logs everyone out):
  ```bash
  python3 -c "import secrets; print(secrets.token_urlsafe(48))"
  ```
- `SESSION_COOKIE_SECURE=true` — the server is behind nginx with TLS. Leaving it
  false would let the session cookie travel over plain HTTP.

Then create the `users` table and the first admin account (the site is
invite-only and a restored dump may not contain a `users` table yet):

```bash
sudo -u agentapp psql -h localhost -U agents_app -d Agents_Heresure \
  -f /opt/agent_licence/sql/create_users_table.sql
sudo -u agentapp psql -h localhost -U agents_app -d Agents_Heresure \
  -f /opt/agent_licence/sql/create_imports_tables.sql
cd /opt/agent_licence && sudo -u agentapp .venv/bin/python -m scripts.manage_users \
  set-password you@example.com --role admin
```

Everyone else is invited from `/admin/users` in the web UI once you can log in.

```bash
sudo chmod 600 /opt/agent_licence/.env
```

## 4. Migrate the database (all current records)

**Locally**, on your own Mac:

```bash
cd ~/Desktop/agent_licence
./deploy/dump_db.sh
# creates a file like agents_heresure_20260817_153000.dump
scp agents_heresure_*.dump root@<DROPLET_IP>:/root/
```

**On the server**:

```bash
cd /opt/agent_licence
PGPASSWORD='<password of the agents_app role>' \
  deploy/restore_db.sh /root/agents_heresure_20260817_153000.dump
```

The script restores the schema and all rows and at the end prints `SELECT COUNT(*)` —
compare it with what you see locally at `http://127.0.0.1:5000`.

## 5. Run the application as a service

```bash
sudo cp /opt/agent_licence/deploy/agent-licence.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now agent-licence
sudo systemctl status agent-licence   # should be active (running)
```

## 6. nginx + HTTPS

There's no domain — we use the free wildcard DNS `sslip.io`, which resolves to
the droplet's IP on its own without buying any domain: `<IP>.sslip.io`
(e.g. `167.99.12.34.sslip.io`).

```bash
sudo cp /opt/agent_licence/deploy/nginx.conf /etc/nginx/sites-available/agent-licence
sudo sed -i "s/YOUR_HOST/<DROPLET_IP_WITH_DOTS>.sslip.io/" /etc/nginx/sites-available/agent-licence
sudo ln -s /etc/nginx/sites-available/agent-licence /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx

sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d <DROPLET_IP_WITH_DOTS>.sslip.io
```

Certbot will add the TLS block itself and set up the http-to-https redirect.

Done: `https://<IP>.sslip.io` is your site's address. It opens from any device,
but every page requires a login — access is invite-only, so sign in with the admin
account created in step 3 and invite the rest of the team from `/admin/users`. No
domain was bought — `sslip.io` resolves `<IP>.sslip.io` to the droplet's IP for
free, which is enough for certbot too (a real TLS certificate).

If you later want your own domain (e.g. `agents.yourcompany.com`) — just point
an A record at the droplet's IP and reissue the certificate:
`certbot --nginx -d agents.yourcompany.com`.

## 7. Verification and future updates

First, once — locally remember the server's address (the file is in `.gitignore`,
it doesn't go into git):

```bash
cp deploy/server.env.example deploy/server.env
# fill in SERVER_IP and SITE_URL of this droplet
```

- Site logs: `journalctl -u agent-licence -f`
- Update the code after changes — locally, in one command: `./deploy/update.sh`
  (rsync to the server + `systemctl restart agent-licence`, doesn't touch `.env` on the server)

### ⚠️ One-time step when moving to the MVC layout

The project was flat (`app.py`, `parser.py`, … in the root) and is now split
into `wsgi.py` + `app/` + `scripts/` + `sql/`. **Both systemd unit files
changed their `ExecStart`**, and unit files live in `/etc/systemd/system/`, not
in the rsynced tree — `update.sh` only restarts the service, it does not
reinstall units. So on the first deploy after the reorg, run in this order:

```bash
./deploy/update.sh                       # locally: rsync (now with --delete, so the old flat files go away)
```

then on the server:

```bash
sudo cp /opt/agent_licence/deploy/agent-licence.service /etc/systemd/system/
sudo cp /opt/agent_licence/deploy/agent-licence-parser.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart agent-licence
systemctl is-active agent-licence
sudo systemctl start agent-licence-parser   # one poll by hand; runs the import only if the schedule says it is due
journalctl -u agent-licence-parser -n 30
```

If you deploy the code but leave the old unit in place, gunicorn is still told
to load `app:app`; `app` is now a package with no module-level `app`, so the
worker dies on boot, `Restart=on-failure` loops, and nginx returns 502.

## 8. Scheduled loading of new agents (`scripts.run_import` on a schedule)

The timer **no longer owns the time of day**. It polls every 15 minutes and runs
`scripts.run_import --if-due`, which reads the schedule from the database
(`import_settings`) and does nothing unless the configured slot has arrived. The
schedule itself — on/off, time, timezone — is set in the app at
`/imports/settings`, along with which counties and license types to import.

When it does run: downloads the fresh Florida DFS registry → filters by the
selected counties and license types → adds to `licenses` only new agents (by the
Full Name + Business Email pair) with `checked = false`. It never touches existing
rows or manually-set `checked`/`Personal Email`. Every run, manual or scheduled,
is recorded and visible on `/imports`.

Install or update the units:

```bash
cp /opt/agent_licence/deploy/agent-licence-parser.service /opt/agent_licence/deploy/agent-licence-parser.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now agent-licence-parser.timer
systemctl restart agent-licence-parser.timer
```

> **⚠️ Upgrading an existing server:** the unit files are NOT part of the rsynced
> tree — `deploy/update.sh` only restarts the app service. Until you run the copy
> above plus `daemon-reload`, the server keeps running the OLD unit, which fires
> `-m scripts.parser` at a fixed 09:00 and ignores the schedule in the UI. You must
> also apply `sql/create_imports_tables.sql` once (see §3) or every import fails
> with a missing-table error.

Handy commands:
- When the next poll is: `systemctl list-timers agent-licence-parser.timer`
- Logs of the last poll/run: `journalctl -u agent-licence-parser.service -n 50`
  (a poll that decides "not due" logs one line and exits 0 — that is normal)
- Force a run now, ignoring the schedule:
  `sudo -u agentapp /opt/agent_licence/.venv/bin/python3 -m scripts.run_import`
  run from `/opt/agent_licence`. Or just press **Run import now** on `/imports`.
- Why nothing ran: check the schedule is enabled on `/imports/settings`, then the
  journal above — `--if-due` prints the reason it skipped (disabled, not yet due,
  or already ran for that slot).

## ⚠️ About the leaked password `1560`

It was hardcoded as a default in the app and the scripts (then `app.py`/
`parser.py`/`send_campaign.py`, now `app/config.py`) and
has already been committed to git, pushed to
`github.com/Leillaa/Heresure_Search`. I removed the hardcode and the server now
uses a new random password — but the fact that `1560` is in the repository's
history hasn't gone anywhere. If this is the only place this password was used
(e.g. a local Postgres only on your Mac) — you can just stop using it
everywhere. If you want to purge it from git history — say so, I'll help
(`git filter-repo` + force-push; this is an irreversible operation on history,
done only on explicit request).
