"""
[EN]
WSGI entry point for the mini page listing the agents from the Agents_Heresure
database. Paginated (50 per page), with a "Send Email" button on each row — the
button currently does nothing (a stub for future sending).

The application itself is assembled in app/create_app(); see app/README-less
layout: app/models (data), app/controllers (routes), app/templates +
app/static (presentation).

Access is invite-only: every page requires a login session except the login form
and an invite link. A fresh database has no accounts, so create the first one with
    python3 -m scripts.manage_users set-password you@example.com --role admin

Settings (DB, SECRET_KEY, session) are read from the .env in this same folder —
see .env.example. The app refuses to start without PGPASSWORD or SECRET_KEY.

Local run (Flask dev server):
    python3 wsgi.py
Open in a browser:
    http://127.0.0.1:5000

Production run (server, behind nginx) — see deploy/README.md:
    gunicorn -w 2 -b 127.0.0.1:8000 wsgi:app

[RU]
WSGI-точка входа для мини-страницы со списком агентов из базы Agents_Heresure.
Постранично (50 на страницу), с кнопкой "Отправить письмо" у каждой строки —
пока кнопка ничего не делает (заглушка под будущую отправку).

Само приложение собирается в app/create_app(); структура: app/models (данные),
app/controllers (маршруты), app/templates + app/static (представление).

Доступ только по приглашению: каждая страница требует сессию входа, кроме формы
входа и ссылки-приглашения. В чистой базе аккаунтов нет, первый создаётся так:
    python3 -m scripts.manage_users set-password you@example.com --role admin

Настройки (БД, SECRET_KEY, сессия) берутся из .env в этой же папке — см.
.env.example. Приложение не стартует без PGPASSWORD или SECRET_KEY.

Локальный запуск (dev-сервер Flask):
    python3 wsgi.py
Открыть в браузере:
    http://127.0.0.1:5000

Прод-запуск (сервер, за nginx) — см. deploy/README.md:
    gunicorn -w 2 -b 127.0.0.1:8000 wsgi:app
"""

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    # [EN] Bind to localhost only by default — the database holds real personal
    # data. On the server the app runs via gunicorn (see deploy/README.md);
    # this block is for local development only.
    # [RU] bind по умолчанию только на localhost — в базе реальные персональные
    # данные. На сервере приложение запускается через gunicorn (см.
    # deploy/README.md), этот блок — только для локальной разработки.
    host = os.environ.get("APP_HOST", "127.0.0.1")
    port = int(os.environ.get("APP_PORT", "5000"))
    app.run(host=host, port=port, debug=False)
