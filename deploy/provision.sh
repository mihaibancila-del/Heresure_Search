#!/usr/bin/env bash
# [EN] One-time bootstrap of a CLEAN droplet (Ubuntu 22.04) for this application.
# Run ON THE SERVER as root right after creating the droplet:
#
#   bash provision.sh '<password_for_the_agents_app_DB>'
#
# Make up the password for the agents_app role in Postgres yourself (e.g. openssl rand -base64 24)
# and don't lose it — it also goes into .env as PGPASSWORD.
#
# [RU] Одноразовый bootstrap ЧИСТОГО droplet'а (Ubuntu 22.04) под это приложение.
# Запускать НА СЕРВЕРЕ от root сразу после создания droplet'а:
#
#   bash provision.sh '<пароль_для_БД_agents_app>'
#
# Пароль для роли agents_app в Postgres придумай сам (например: openssl rand -base64 24)
# и не теряй — он же пойдёт в .env как PGPASSWORD.

set -euo pipefail

DB_PASSWORD="${1:?Usage: bash provision.sh <password_for_the_agents_app_role>}"

APP_USER="agentapp"
APP_DIR="/opt/agent_licence"
DB_NAME="Agents_Heresure"
DB_USER="agents_app"

echo "==> apt update and package install"
apt-get update -y
apt-get install -y python3-venv python3-pip postgresql postgresql-contrib nginx ufw git

echo "==> firewall (open only SSH and HTTP/HTTPS)"
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

echo "==> system user for the app (no shell, no sudo)"
id -u "$APP_USER" &>/dev/null || useradd --system --create-home --shell /usr/sbin/nologin "$APP_USER"

echo "==> app directory"
mkdir -p "$APP_DIR"
chown "$APP_USER":"$APP_USER" "$APP_DIR"

echo "==> role and database in Postgres"
sudo -u postgres psql -v ON_ERROR_STOP=1 -c "
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASSWORD}';
  ELSE
    ALTER ROLE ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';
  END IF;
END
\$\$;
"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" | grep -q 1 || \
  sudo -u postgres createdb -O "$DB_USER" "$DB_NAME"

echo
echo "======================================================================"
echo "Done. Next, manually (see deploy/README.md):"
echo "  1) upload the code to $APP_DIR (git clone https://github.com/Leillaa/Heresure_Search.git)"
echo "  2) su - $APP_USER -s /bin/bash -c \"cd $APP_DIR && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt\""
echo "  3) create $APP_DIR/.env (based on .env.example):"
echo "       PGHOST=localhost"
echo "       PGUSER=${DB_USER}"
echo "       PGDATABASE=${DB_NAME}"
echo "       PGPASSWORD=${DB_PASSWORD}"
echo "       SECRET_KEY=<python3 -c 'import secrets; print(secrets.token_urlsafe(48))'>"
echo "       SESSION_COOKIE_SECURE=true"
echo "     (SECRET_KEY is required — the app refuses to start without it)"
echo "  4) upload the database dump (scp) and restore it:"
echo "       PGPASSWORD=${DB_PASSWORD} deploy/restore_db.sh /root/agents_heresure_*.dump"
echo "  5) create the users table and the first admin (access is invite-only):"
echo "       psql -h localhost -U ${DB_USER} -d ${DB_NAME} -f sql/create_users_table.sql"
echo "       .venv/bin/python -m scripts.manage_users set-password you@example.com --role admin"
echo "  6) install the systemd unit (deploy/agent-licence.service) and nginx (deploy/nginx.conf)"
echo "======================================================================"
