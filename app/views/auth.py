"""
[EN]
Session-based access control for the whole site. Access is invite-only — there
is no signup — because the database holds real names, emails, phone numbers and
addresses of Florida insurance agents.

This module is deliberately pure: session cookie reads/writes, the public
endpoint allowlist, and the admin decorator. It performs no SQL. Loading the
signed-in user is a model call and therefore lives in
app/controllers/auth.py:load_user_and_require_login, which is registered as the
single app-wide before_request.

DEFAULT DENY. Protection is not per-route any more. Every endpoint requires a
session unless its name is in PUBLIC_ENDPOINTS below. This replaces the old
per-route @require_auth decorator, where writing the two decorators in the wrong
order silently served real personal data with no auth at all (the first trap in
AGENTS.md §4). Forgetting to protect a new route is now impossible; the only way
to expose one is to add its endpoint name here on purpose.

[RU]
Контроль доступа на сессиях для всего сайта. Доступ только по приглашению —
регистрации нет — потому что в базе реальные ФИО, email, телефоны и адреса
страховых агентов Флориды.

Модуль намеренно чистый: чтение/запись cookie сессии, белый список публичных
эндпоинтов и декоратор для админа. SQL здесь не выполняется. Загрузка вошедшего
пользователя — это вызов модели, поэтому она живёт в
app/controllers/auth.py:load_user_and_require_login и регистрируется как
единственный before_request на всё приложение.

ЗАПРЕТ ПО УМОЛЧАНИЮ. Защита больше не привязана к маршруту. Каждый эндпоинт
требует сессию, если его имени нет в PUBLIC_ENDPOINTS ниже. Это заменяет старый
подекораторный @require_auth, где неверный порядок двух декораторов молча отдавал
реальные персональные данные вообще без авторизации (первая ловушка в AGENTS.md §4).
Забыть защитить новый маршрут теперь невозможно; открыть его можно только
намеренно добавив имя эндпоинта сюда.
"""

import functools

from flask import abort, g, redirect, request, session, url_for

# [EN] The only endpoints reachable without a session:
#   auth.login          — the login form itself, or nobody could ever sign in
#   auth.accept_invite  — the invite link; the user has no password yet by definition
#   static              — CSS/JS only. Never put anything sensitive under app/static/
#                         (AGENTS.md §4: static is not covered by any auth).
# Adding a name here makes that page world-readable. Do not add one without
# checking what it renders.
# [RU] Единственные эндпоинты, доступные без сессии:
#   auth.login          — сама форма входа, иначе никто не смог бы войти
#   auth.accept_invite  — ссылка-приглашение; у пользователя по определению ещё нет пароля
#   static              — только CSS/JS. Никогда не кладите ничего чувствительного
#                         в app/static/ (AGENTS.md §4: static не покрыт авторизацией).
# Добавление имени сюда делает страницу доступной всем. Не добавляйте, не
# проверив, что она отдаёт.
PUBLIC_ENDPOINTS = frozenset({"auth.login", "auth.accept_invite", "static"})

_USER_ID_KEY = "uid"


def is_public(endpoint: str | None) -> bool:
    """[EN] Unmatched routes (endpoint is None, i.e. a 404) count as protected:
    an anonymous visitor is sent to the login page instead of being told which
    URLs do and do not exist.
    [RU] Несопоставленные маршруты (endpoint is None, то есть 404) считаются
    защищёнными: анонимный посетитель отправляется на страницу входа, а не
    узнаёт, какие URL существуют, а какие нет."""
    return endpoint in PUBLIC_ENDPOINTS


def start_session(user_id: int) -> None:
    """[EN] session.clear() first to prevent session fixation — anything an
    attacker planted in the pre-login session (including a stale uid) is dropped
    before the new identity is written.

    permanent=True is what keeps the user logged in after the browser closes;
    the lifetime comes from config.SESSION_LIFETIME_DAYS.

    [RU] Сначала session.clear() против фиксации сессии — всё, что атакующий
    подложил в сессию до входа (включая устаревший uid), сбрасывается до записи
    новой личности.

    permanent=True — именно это оставляет пользователя в системе после закрытия
    браузера; срок берётся из config.SESSION_LIFETIME_DAYS."""
    session.clear()
    session[_USER_ID_KEY] = user_id
    session.permanent = True


def end_session() -> None:
    session.clear()


def session_user_id() -> int | None:
    """[EN] The raw id from the signed cookie. It is only a claim — the caller
    must still load the row and check is_active.
    [RU] Сырой id из подписанной cookie. Это лишь заявка — вызывающий обязан
    загрузить строку и проверить is_active."""
    user_id = session.get(_USER_ID_KEY)
    return user_id if isinstance(user_id, int) else None


def current_user() -> dict | None:
    """[EN] The user loaded for this request, or None. Registered as a Jinja
    global in create_app so templates can render the header without the
    controllers passing it into every render_template call.
    [RU] Пользователь, загруженный для этого запроса, или None. Регистрируется
    как глобал Jinja в create_app, чтобы шаблоны рисовали шапку без передачи его
    в каждый вызов render_template."""
    return g.get("user")


def login_redirect():
    """[EN] Sends an anonymous visitor to the login form, remembering where they
    were headed so the login can bounce them back.

    request.full_path is used only when there really is a query string — it
    appends a bare "?" otherwise, which would show up as ?next=/? in the URL bar.
    [RU] Отправляет анонимного посетителя на форму входа, запоминая, куда он шёл,
    чтобы после входа вернуть его обратно.

    request.full_path берётся только когда query-строка действительно есть — иначе
    он добавляет пустой "?", и в адресной строке появилось бы ?next=/?."""
    target = request.full_path if request.query_string else request.path
    return redirect(url_for("auth.login", next=target))


def safe_next_target(raw: str | None, fallback: str) -> str:
    """[EN] Open-redirect guard for the ?next= parameter. Only a site-relative
    path is allowed: it must start with a single "/" and must not start with "//"
    or "/\\", both of which browsers treat as protocol-relative URLs pointing at
    another host. Without this check a crafted login link could send a user to an
    attacker's page after a successful login.

    Two further rules, both rejecting outright rather than sanitising — a value
    that looks hostile is never worth repairing:

    * Control characters (anything below 0x20, plus 0x7f DEL) are rejected
      anywhere in the value. Browsers *strip* tab, CR and LF from a URL before
      resolving it, so "/\\t/evil.com" passes a naive prefix check and is then
      re-formed into "//evil.com" — a protocol-relative URL to the attacker's
      host. CR/LF are also the classic ingredient for response-header (CRLF)
      injection once the value reaches a Location header.
    * A backslash anywhere is rejected, not just as the second character. Several
      browsers normalise "\\" to "/", so "/\\evil.com" and its variants can turn
      into a protocol-relative URL too. Legitimate paths on this site never
      contain one.

    [RU] Защита от открытого перенаправления для параметра ?next=. Разрешён только
    относительный путь на этом же сайте: он должен начинаться с одного "/" и не
    должен начинаться с "//" или "/\\" — браузеры считают их URL с относительным
    протоколом, ведущими на другой хост. Без этой проверки поддельная ссылка на
    вход могла бы после успешного входа отправить пользователя на страницу атакующего.

    Ещё два правила; оба отклоняют значение целиком, а не «чистят» его — значение,
    выглядящее враждебным, чинить не нужно:

    * Управляющие символы (всё ниже 0x20, а также 0x7f DEL) запрещены в любом
      месте строки. Браузеры *вырезают* табуляцию, CR и LF из URL до его
      разрешения, поэтому "/\\t/evil.com" проходит наивную проверку префикса, а
      затем превращается в "//evil.com" — URL с относительным протоколом на хост
      атакующего. Кроме того, CR/LF — классический материал для инъекции в
      заголовки ответа (CRLF), когда значение попадает в заголовок Location.
    * Обратный слэш запрещён в любой позиции, а не только вторым символом. Ряд
      браузеров нормализует "\\" в "/", так что "/\\evil.com" и его варианты тоже
      могут стать URL с относительным протоколом. В настоящих путях этого сайта
      обратного слэша не бывает."""
    if not raw or not raw.startswith("/"):
        return fallback
    if raw.startswith("//") or "\\" in raw:
        return fallback
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in raw):
        return fallback
    return raw


def admin_required(view):
    """[EN] For pages that manage other accounts. Layered ON TOP of the app-wide
    login guard, which has already run and guaranteed g.user exists — so this
    only has to check the role.

    NOTE: like every route decorator in this project, the route must be the OUTER
    decorator:
        @bp.route("/admin/users")   # outer
        @admin_required             # inner
    Flipping them registers the unwrapped view. Unlike the old @require_auth,
    getting this wrong no longer exposes personal data — the app-wide guard still
    requires a session — but it would let any signed-in member manage accounts.

    [RU] Для страниц, управляющих другими аккаунтами. Накладывается ПОВЕРХ
    общего guard-а входа, который уже сработал и гарантировал наличие g.user —
    поэтому здесь достаточно проверить роль.

    ВАЖНО: как и у любого декоратора маршрута в этом проекте, маршрут должен быть
    ВНЕШНИМ декоратором:
        @bp.route("/admin/users")   # внешний
        @admin_required             # внутренний
    Если поменять местами, зарегистрируется необёрнутая функция. В отличие от
    старого @require_auth, ошибка здесь больше не открывает персональные данные —
    общий guard всё равно требует сессию — но позволит любому вошедшему участнику
    управлять аккаунтами."""
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or user["role"] != "admin":
            # [EN] 404, not 403: a member has no business knowing this page is here.
            # [RU] 404, а не 403: участнику незачем знать, что эта страница существует.
            abort(404)
        return view(*args, **kwargs)

    return wrapped
