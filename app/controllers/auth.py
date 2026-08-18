"""
[EN]
Login, logout and invite acceptance, plus the one app-wide before_request that
loads the signed-in user and enforces the login requirement.

Why the guard lives here and not in app/views/auth.py: confirming a session is
still valid means reading the users row on every request (so that deactivating an
account takes effect immediately), and per AGENTS.md §2 the view layer must not
query the database. Loading and enforcing are also deliberately ONE function
rather than two before_request hooks — two hooks would depend on registration
order, and if the guard ever ran before the loader, g.user would be empty and
every signed-in user would be bounced to the login page.

[RU]
Вход, выход и принятие приглашения, а также единственный общий before_request,
который загружает вошедшего пользователя и требует авторизацию.

Почему guard живёт здесь, а не в app/views/auth.py: проверка того, что сессия
всё ещё действительна, означает чтение строки users на каждом запросе (чтобы
отключение аккаунта действовало сразу), а по AGENTS.md §2 слой представления не
должен обращаться к базе. Загрузка и проверка намеренно сделаны ОДНОЙ функцией,
а не двумя хуками before_request — два хука зависели бы от порядка регистрации,
и если бы guard сработал раньше загрузчика, g.user был бы пуст и каждого
вошедшего пользователя выбрасывало бы на страницу входа.
"""

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from app import config
from app.models import db, user as user_model
from app.security import hash_password, hash_token, normalize_email, verify_password
from app.views import auth as auth_view
from app.views.csrf import check_csrf

bp = Blueprint("auth", __name__)

# [EN] Deliberately identical for "no such email", "wrong password" and
# "deactivated": a login form that distinguishes them tells an outsider which
# email addresses are on the team.
# [RU] Намеренно одинаково для "нет такого email", "неверный пароль" и
# "отключён": форма входа, различающая эти случаи, сообщает посторонним, какие
# email есть в команде.
_LOGIN_FAILED = "Wrong email or password."

# [EN] Endpoints that need NO per-request users row, so the guard can skip the
# connection + SELECT entirely. Only `static` qualifies, and only because it
# satisfies both conditions at once: it is in PUBLIC_ENDPOINTS (so g.user cannot
# change whether it is allowed), and it renders no template — Flask serves the
# file straight from app/static/, so nothing ever calls current_user(). Every
# page load pulls several CSS/JS files, and each one was opening a brand-new
# Postgres connection just to be thrown away.
#
# This set is NOT "the public endpoints". auth.login reads g.user to bounce an
# already-signed-in visitor, and auth.login/auth.accept_invite both render
# base.html, which calls current_user() to draw the nav bar — so they keep the
# load. Anything not listed here (including request.endpoint None, i.e. a 404)
# also keeps it: default deny is unchanged, this only removes work that could
# have had no effect on the outcome.
#
# [RU] Эндпоинты, которым НЕ нужна строка users на каждый запрос, поэтому guard
# может полностью пропустить подключение и SELECT. Подходит только `static`, и
# только потому, что выполняются оба условия сразу: он есть в PUBLIC_ENDPOINTS
# (значит g.user не влияет на то, разрешён ли он) и он не рендерит шаблон —
# Flask отдаёт файл прямо из app/static/, поэтому current_user() никто не
# вызывает. Каждая загрузка страницы тянет несколько файлов CSS/JS, и на каждый
# открывалось новое соединение с Postgres только чтобы его сразу выбросить.
#
# Это НЕ "публичные эндпоинты". auth.login читает g.user, чтобы перенаправить уже
# вошедшего посетителя, а auth.login и auth.accept_invite оба рендерят base.html,
# который вызывает current_user() для шапки — поэтому загрузка у них остаётся.
# Всё, чего здесь нет (включая request.endpoint None, то есть 404), тоже её
# сохраняет: запрет по умолчанию не меняется, убрана только работа, которая всё
# равно не могла повлиять на результат.
_SKIP_USER_LOAD_ENDPOINTS = frozenset({"static"})


def load_user_and_require_login():
    """[EN] Registered in create_app as the single app-wide before_request. Runs
    for EVERY request, in this order:

      1. CSRF check on POSTs (before any state changes) — unconditionally, for
         every endpoint, public ones included.
      2. Load the session's user, if any, into g.user — unless the endpoint is
         one of _SKIP_USER_LOAD_ENDPOINTS, where the row cannot affect anything.
      3. Deny the request unless the endpoint is public or a user is loaded.

    A signed cookie proves only that we issued the id; the row is re-read every
    request so that deactivating a user, or deleting them, takes effect on their
    very next click rather than whenever the cookie happens to expire. That still
    holds after the step-2 skip: the only skipped endpoint is `static`, which
    grants no access to data and is reachable anonymously anyway, so a
    deactivated user gains nothing from it — their next request to any real page
    re-reads the row and ends the session.

    [RU] Регистрируется в create_app как единственный общий before_request.
    Выполняется для КАЖДОГО запроса в таком порядке:

      1. Проверка CSRF на POST (до любых изменений состояния) — безусловно, для
         каждого эндпоинта, включая публичные.
      2. Загрузка пользователя из сессии, если он есть, в g.user — кроме
         эндпоинтов из _SKIP_USER_LOAD_ENDPOINTS, где строка ни на что не влияет.
      3. Отказ, если эндпоинт не публичный и пользователь не загружен.

    Подписанная cookie доказывает лишь то, что id выдали мы; строка перечитывается
    на каждом запросе, чтобы отключение или удаление пользователя срабатывало на
    следующем же его клике, а не когда истечёт cookie. Это остаётся верным и после
    пропуска на шаге 2: единственный пропускаемый эндпоинт — `static`, он не даёт
    доступа к данным и так открыт анонимно, поэтому отключённый пользователь
    ничего от него не получает — на следующем же запросе к реальной странице
    строка перечитывается и сессия закрывается."""
    g.user = None

    # [EN] CSRF stays FIRST and unconditional. It must cover POSTs to the public
    # endpoints too (auth.login, auth.accept_invite) — those are exactly the
    # forms an attacker would target, and they change state. Never move this
    # behind an endpoint check.
    # [RU] CSRF остаётся ПЕРВЫМ и безусловным. Он должен покрывать и POST к
    # публичным эндпоинтам (auth.login, auth.accept_invite) — именно эти формы
    # атакующий и будет использовать, и именно они меняют состояние. Никогда не
    # уводите эту проверку за условие по эндпоинту.
    if not check_csrf():
        # [EN] 400, and no hint about what to fix — a real form always has the field.
        # [RU] 400 и без подсказок — у настоящей формы поле всегда есть.
        return "Bad request (CSRF check failed).", 400

    # [EN] is_public() is re-checked here on purpose, so PUBLIC_ENDPOINTS remains
    # the single authentication boundary: if `static` were ever removed from it,
    # this shortcut stops applying and the request falls through to the normal
    # load-and-deny path instead of staying open on its own authority.
    # [RU] is_public() здесь перепроверяется намеренно, чтобы PUBLIC_ENDPOINTS
    # оставался единственной границей авторизации: если `static` когда-нибудь
    # уберут оттуда, этот шорткат перестанет действовать и запрос уйдёт в обычный
    # путь "загрузить и запретить", а не останется открытым сам по себе.
    if request.endpoint in _SKIP_USER_LOAD_ENDPOINTS and auth_view.is_public(request.endpoint):
        # [EN] Public AND template-free: no DB trip, g.user stays None, allowed.
        # [RU] Публичный И без шаблона: без обращения к базе, g.user остаётся
        # None, запрос разрешён.
        return None

    user_id = auth_view.session_user_id()
    if user_id is not None:
        with db.connection() as conn:
            row = user_model.find_by_id(conn, user_id)
        # [EN] is_active and an accepted invite (password set) are both required;
        # a revoked or never-completed account cannot ride an old cookie.
        # [RU] Требуются и is_active, и принятое приглашение (пароль задан);
        # отозванный или незавершённый аккаунт не проедет на старой cookie.
        if row and row["is_active"] and row["password_hash"]:
            g.user = row
        else:
            auth_view.end_session()

    if auth_view.is_public(request.endpoint) or g.user:
        return None

    return auth_view.login_redirect()


@bp.route("/login", methods=["GET", "POST"])
def login():
    """[EN] The login form. Public by way of PUBLIC_ENDPOINTS — without that
    nobody could ever reach it.
    [RU] Форма входа. Публичная через PUBLIC_ENDPOINTS — иначе до неё никто не
    смог бы добраться."""
    target = auth_view.safe_next_target(request.args.get("next"), url_for("licenses.index"))

    # [EN] Already signed in? Don't show the form again.
    # [RU] Уже вошли? Не показываем форму снова.
    if g.user:
        return redirect(target)

    if request.method == "POST":
        email = normalize_email(request.form.get("email", ""))
        password = request.form.get("password", "")

        with db.connection() as conn:
            row = user_model.find_by_email(conn, email)

            # [EN] verify_password() runs even when the row is missing — it spends
            # the same time on an unknown email, so response timing does not
            # reveal which addresses exist.
            # [RU] verify_password() вызывается даже когда строки нет — на
            # неизвестный email тратится столько же времени, поэтому время ответа
            # не выдаёт, какие адреса существуют.
            stored = row["password_hash"] if row else None
            password_ok = verify_password(stored, password)

            # [EN] password_ok is computed FIRST and unconditionally, then combined —
            # short-circuiting on `row` here would skip the dummy hash and reintroduce
            # the timing leak the dummy exists to close.
            # [RU] password_ok вычисляется СНАЧАЛА и безусловно, и только потом
            # объединяется — короткое замыкание по `row` пропустило бы фиктивный хеш
            # и вернуло утечку по времени, которую он и закрывает.
            ok = bool(row) and row["is_active"] and password_ok

            if not ok:
                flash(_LOGIN_FAILED, "error")
                return render_template("login.html", email=email, next=target), 401

            user_model.touch_last_login(conn, row["id"])

        auth_view.start_session(row["id"])
        return redirect(target)

    return render_template("login.html", email="", next=target)


@bp.route("/logout", methods=["POST"])
def logout():
    """[EN] POST only, and CSRF-checked like every other POST: a GET logout could
    be triggered by any <img> tag on another site.
    [RU] Только POST и с проверкой CSRF, как все остальные POST: выход по GET мог
    бы срабатывать от любого тега <img> на другом сайте."""
    auth_view.end_session()
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/invite/<token>", methods=["GET", "POST"])
def accept_invite(token: str):
    """[EN] The invite link: the invited person sets their own password here, so a
    password is never transmitted or known by the admin who invited them.

    Public by necessity — the holder has no session and no password yet. The token
    itself is the credential: 256 random bits, looked up by sha256 hash, single
    use, and time-limited (config.INVITE_TTL_HOURS).

    [RU] Ссылка-приглашение: приглашённый сам задаёт себе пароль здесь, поэтому
    пароль никогда не передаётся и не известен пригласившему админу.

    Публичная по необходимости — у владельца ссылки ещё нет ни сессии, ни пароля.
    Сам токен и есть credential: 256 случайных бит, поиск по хешу sha256,
    одноразовый и ограниченный по времени (config.INVITE_TTL_HOURS)."""
    token_hash = hash_token(token)

    with db.connection() as conn:
        row = user_model.find_by_invite_token_hash(conn, token_hash)

    # [EN] One message for expired, already-used, revoked and never-existed, so a
    # stranger poking at /invite/<guess> learns nothing.
    # [RU] Одно сообщение для истёкших, уже использованных, отозванных и никогда
    # не существовавших, чтобы посторонний, тыкающий в /invite/<догадка>, ничего
    # не узнал.
    if not row:
        return render_template("accept_invite.html", invalid=True, token=token), 404

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("password_confirm", "")
        error = _password_error(password, confirm)

        if error:
            flash(error, "error")
            return render_template("accept_invite.html", invalid=False,
                                   token=token, email=row["email"]), 400

        with db.connection() as conn:
            accepted = user_model.accept_invite(conn, row["id"], hash_password(password))

        # [EN] accept_invite() returns False if the token was already burned —
        # e.g. a double submit, or the link used twice in two tabs.
        # [RU] accept_invite() вернёт False, если токен уже сожжён — например,
        # двойная отправка или ссылка, открытая в двух вкладках.
        if not accepted:
            return render_template("accept_invite.html", invalid=True, token=token), 409

        # [EN] Log them straight in — they just proved they hold the invite and
        # chose the password, so a second trip through the login form adds nothing.
        # [RU] Сразу выполняем вход — человек только что подтвердил владение
        # приглашением и задал пароль, поэтому ещё один проход через форму входа
        # ничего не добавляет.
        auth_view.start_session(row["id"])
        flash("Welcome. Your password is set.", "success")
        return redirect(url_for("licenses.index"))

    return render_template("accept_invite.html", invalid=False, token=token, email=row["email"])


def _password_error(password: str, confirm: str) -> str | None:
    """[EN] Minimum viable password rules: a length floor and a confirmation
    field. Length is the check that actually matters — composition rules push
    people towards predictable substitutions.
    [RU] Минимально осмысленные правила пароля: нижняя граница длины и поле
    подтверждения. Реально значима именно длина — правила про состав символов
    подталкивают людей к предсказуемым заменам."""
    if len(password) < config.PASSWORD_MIN_LENGTH:
        return f"Password must be at least {config.PASSWORD_MIN_LENGTH} characters."
    if password != confirm:
        return "The two passwords do not match."
    return None
