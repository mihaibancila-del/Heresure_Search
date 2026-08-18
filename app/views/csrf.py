"""
[EN]
CSRF protection for the POST forms (login, logout, accept invite, admin
actions). Hand-rolled for the same reason as the .env parser: it keeps
requirements.txt at four lines (AGENTS.md §1), and the whole mechanism is small
enough to read in one sitting.

The scheme is the standard synchroniser token: a random value is stored in the
signed session cookie and echoed in a hidden form field. An attacker's site can
make a browser POST here, but cannot read the victim's session cookie, so it
cannot supply the matching field.

Enforcement is global — check_csrf() is called from the app-wide before_request
for every POST, so a new form cannot forget it. SameSite=Lax on the session
cookie (set in create_app) is a second, independent layer.

[RU]
Защита от CSRF для POST-форм (вход, выход, принятие приглашения, действия
админа). Написано вручную по той же причине, что и парсер .env: requirements.txt
остаётся на четырёх строках (AGENTS.md §1), а весь механизм достаточно мал,
чтобы прочитать его за один раз.

Схема — стандартный synchroniser token: случайное значение хранится в подписанной
cookie сессии и дублируется в скрытом поле формы. Сайт атакующего может заставить
браузер отправить сюда POST, но не может прочитать cookie сессии жертвы, поэтому
не подставит совпадающее поле.

Проверка глобальная — check_csrf() вызывается из общего before_request для каждого
POST, поэтому новая форма не может о ней забыть. SameSite=Lax на cookie сессии
(выставляется в create_app) — второй независимый слой.
"""

import secrets

from flask import request, session

from app.security import tokens_equal

_CSRF_KEY = "csrf"
FIELD_NAME = "csrf_token"


def csrf_token() -> str:
    """[EN] The token for this session, minted on first use. Registered as a Jinja
    global in create_app, so templates call {{ csrf_token() }} directly.

    Deliberately NOT rotated per request: with one token per session, a user with
    two tabs open can submit from either one. Rotating would invalidate the older
    tab's form and look like a random failure.

    [RU] Токен для этой сессии, создаётся при первом обращении. Регистрируется как
    глобал Jinja в create_app, поэтому шаблоны вызывают {{ csrf_token() }} напрямую.

    Намеренно НЕ меняется на каждый запрос: при одном токене на сессию пользователь
    с двумя открытыми вкладками может отправить форму из любой. Ротация сделала бы
    форму в старой вкладке недействительной, и это выглядело бы как случайный сбой."""
    token = session.get(_CSRF_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[_CSRF_KEY] = token
    return token


def session_has_token() -> bool:
    """[EN] Whether this session ever minted a CSRF token. Distinguishes the two
    reasons check_csrf() can fail:

      - No token in the session at all -> the session is new, expired or was
        cleared (a sign-out, a deactivated account, a restart with a new
        SECRET_KEY). The person is simply no longer signed in, and the useful
        response is "sign in again", not a bare 400.
      - A token exists but the submitted one does not match -> genuinely
        suspicious, and 400 is the right answer.

    Reading this does NOT move or weaken the check itself — the check stays first
    and unconditional; only the failure response differs.

    [RU] Создавала ли эта сессия когда-либо CSRF-токен. Различает две причины сбоя
    check_csrf():

      - Токена в сессии нет вовсе -> сессия новая, истекла или была очищена (выход,
        отключённый аккаунт, перезапуск с новым SECRET_KEY). Человек просто больше
        не в системе, и полезный ответ — "войдите снова", а не сухой 400.
      - Токен есть, но присланный не совпадает -> действительно подозрительно, и 400
        здесь уместен.

    Это чтение НЕ перемещает и не ослабляет саму проверку — она остаётся первой и
    безусловной; отличается только ответ при сбое."""
    return bool(session.get(_CSRF_KEY))


def check_csrf() -> bool:
    """[EN] True if this request may proceed. Only POST is checked — GET must stay
    side-effect free, which is why every state change in this app is a POST.

    A missing session token cannot pass: tokens_equal("", "") would be true, so
    the empty case is rejected explicitly before comparing.

    [RU] True, если запрос можно продолжать. Проверяется только POST — GET должен
    оставаться без побочных эффектов, поэтому каждое изменение состояния в этом
    приложении сделано через POST.

    Отсутствующий токен в сессии пройти не может: tokens_equal("", "") дало бы
    true, поэтому пустой случай отклоняется явно до сравнения."""
    if request.method != "POST":
        return True

    expected = session.get(_CSRF_KEY)
    supplied = request.form.get(FIELD_NAME, "")
    if not expected or not supplied:
        return False
    return tokens_equal(expected, supplied)
