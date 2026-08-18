"""
[EN]
Application factory. Flask(__name__) here means root_path is this package, so
app/templates/ and app/static/ are discovered with no extra configuration.

[RU]
Фабрика приложения. Flask(__name__) здесь означает, что root_path — это сам
пакет, поэтому app/templates/ и app/static/ находятся без дополнительной
настройки.
"""

from datetime import timedelta

from flask import Flask

from app import config
from app.controllers import admin, auth, imports, licenses
from app.views.auth import current_user
from app.views.csrf import csrf_token
from app.views.filters import to_duration, to_tel_href


def create_app() -> Flask:
    app = Flask(__name__)

    # [EN] Fail at boot, not on the first request — this is what app.py used to
    # get from reading PGPASSWORD at import time. SECRET_KEY is checked the same
    # way: without it every session cookie would be unsignable, so gunicorn
    # should refuse to start rather than serve a site nobody can log in to.
    # [RU] Падаем при старте, а не на первом запросе — раньше это давало чтение
    # PGPASSWORD во время импорта app.py. SECRET_KEY проверяется так же: без него
    # cookie сессии невозможно подписать, поэтому gunicorn должен не стартовать,
    # а не отдавать сайт, куда никто не может войти.
    config.pg_password()
    app.secret_key = config.secret_key()

    app.config.update(
        # [EN] No JavaScript access to the session cookie — an XSS bug should not
        # hand over a login.
        # [RU] Никакого доступа из JavaScript к cookie сессии — баг XSS не должен
        # отдавать вход.
        SESSION_COOKIE_HTTPONLY=True,
        # [EN] Lax blocks the cookie on cross-site POSTs, a second layer under the
        # CSRF token in app/views/csrf.py.
        # [RU] Lax не отправляет cookie на межсайтовых POST — второй слой под
        # CSRF-токеном из app/views/csrf.py.
        SESSION_COOKIE_SAMESITE="Lax",
        # [EN] HTTPS only. False locally (plain http), MUST be true on the server.
        # [RU] Только HTTPS. Локально false (обычный http), на сервере ОБЯЗАТЕЛЬНО true.
        SESSION_COOKIE_SECURE=config.SESSION_COOKIE_SECURE,
        PERMANENT_SESSION_LIFETIME=timedelta(days=config.SESSION_LIFETIME_DAYS),
    )

    app.jinja_env.filters["tel_href"] = to_tel_href
    app.jinja_env.filters["duration"] = to_duration
    # [EN] Templates read the signed-in user and the CSRF token directly, so no
    # controller has to thread them through every render_template call.
    # [RU] Шаблоны читают вошедшего пользователя и CSRF-токен напрямую, поэтому
    # ни один контроллер не тащит их через каждый вызов render_template.
    app.jinja_env.globals["current_user"] = current_user
    app.jinja_env.globals["csrf_token"] = csrf_token
    # [EN] So the form's minlength and the server-side check in
    # controllers/auth.py:_password_error cannot drift apart.
    # [RU] Чтобы minlength в форме и серверная проверка в
    # controllers/auth.py:_password_error не разошлись.
    app.jinja_env.globals["password_min_length"] = config.PASSWORD_MIN_LENGTH

    # [EN] THE access control line. One hook, registered before any blueprint, that
    # CSRF-checks every POST, loads the session user and denies anything not in
    # PUBLIC_ENDPOINTS. Every route added from here on is protected by default —
    # see the module docstring in app/views/auth.py for why it is not per-route.
    # [RU] ГЛАВНАЯ строка контроля доступа. Один хук, зарегистрированный раньше
    # любого blueprint: проверяет CSRF на каждом POST, загружает пользователя
    # сессии и запрещает всё, чего нет в PUBLIC_ENDPOINTS. Каждый добавленный далее
    # маршрут защищён по умолчанию — почему не по-маршрутно, см. docstring модуля
    # app/views/auth.py.
    app.before_request(auth.load_user_and_require_login)

    app.register_blueprint(auth.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(imports.bp)
    app.register_blueprint(licenses.bp)

    return app
