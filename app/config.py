"""
[EN]
Single source of configuration for the whole project — the web app and the
scripts in scripts/ all read their settings from here.

Values come from the .env in the PROJECT ROOT (see .env.example). Real
environment variables always win over .env, so systemd EnvironmentFile= and
docker-compose environment: override the file without any extra wiring.

[RU]
Единый источник конфигурации для всего проекта — и веб-приложение, и скрипты
из scripts/ берут настройки отсюда.

Значения читаются из .env в КОРНЕ ПРОЕКТА (см. .env.example). Реальные
переменные окружения всегда важнее .env, поэтому systemd EnvironmentFile= и
docker-compose environment: переопределяют файл без дополнительной настройки.
"""

import os
import sys
from pathlib import Path

# [EN] app/config.py -> the repo root is one level up. resolve() so a symlinked
# checkout or a relative `python -m` invocation still lands on the real root.
# [RU] app/config.py -> корень репозитория на уровень выше. resolve(), чтобы
# симлинк-чекаут или относительный запуск `python -m` всё равно попадал в
# настоящий корень.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"


def load_env(path: Path) -> None:
    """Simple .env parser — no third-party dependencies (like the other
    scripts in this project). Does not overwrite variables already set in
    the environment (e.g. systemd Environment=/EnvironmentFile=).

    Простой парсер .env — без сторонних зависимостей (как в остальных
    скриптах проекта). Не перезаписывает переменные, уже выставленные
    в окружении (например, systemd Environment=/EnvironmentFile=)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Variable {name} is not set (check .env)")
    return value


# [EN] Loaded once, at import — every constant below is read AFTER this line,
# so .env is authoritative for all of them.
# [RU] Загружается один раз, при импорте — все константы ниже читаются ПОСЛЕ
# этой строки, поэтому .env действует на каждую из них.
load_env(ENV_FILE)

PG_BIN = os.environ.get("PG_BIN", "psql")
PG_HOST = os.environ.get("PGHOST", "localhost")
PG_PORT = os.environ.get("PGPORT", "5432")
PG_USER = os.environ.get("PGUSER", "postgres")
PG_DB = os.environ.get("PGDATABASE", "Agents_Heresure")


def pg_password() -> str:
    """[EN] Read on demand, not at import: send_test_email.py needs this module
    for SMTP settings but never touches Postgres, and must not be blocked by a
    missing PGPASSWORD. The web app calls this in create_app() so gunicorn
    still refuses to boot rather than failing on the first request.

    [RU] Читается по требованию, а не при импорте: send_test_email.py берёт
    отсюда SMTP-настройки, но с Postgres не работает, и отсутствие PGPASSWORD
    не должно его блокировать. Веб-приложение вызывает это в create_app(),
    поэтому gunicorn по-прежнему не стартует, а не падает на первом запросе."""
    return get_required("PGPASSWORD")


def secret_key() -> str:
    """[EN] Signs the session cookie. A function, not a constant, for the same
    reason as pg_password(): send_test_email.py imports this module for SMTP
    settings only and must not be blocked by a missing SECRET_KEY. create_app()
    calls it at boot, so the web app still fails fast.

    Losing or changing this value invalidates every existing session — everyone
    is logged out. It must therefore be stable and secret; generate one with
    `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`.

    [RU] Подписывает cookie сессии. Функция, а не константа, по той же причине,
    что и pg_password(): send_test_email.py импортирует этот модуль только за
    SMTP-настройками, и отсутствие SECRET_KEY не должно его блокировать.
    create_app() вызывает её при старте, поэтому веб-приложение по-прежнему
    падает сразу.

    Потеря или смена значения делает недействительными все текущие сессии —
    все разлогиниваются. Поэтому оно должно быть постоянным и секретным;
    сгенерировать: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`."""
    return get_required("SECRET_KEY")


def _int_env(name: str, default: int) -> int:
    """[EN] Tolerant int parser — a malformed value falls back to the default
    rather than taking the whole app down at import.
    [RU] Терпимый парсер int — некорректное значение откатывается к значению по
    умолчанию, а не роняет всё приложение при импорте."""
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# [EN] How long a login lasts. The session cookie is "permanent" in Flask's
# sense, so closing the browser does not log the user out — that is what
# "stays logged in across sessions" requires.
# [RU] Сколько живёт вход. Cookie сессии "permanent" в терминах Flask, поэтому
# закрытие браузера не разлогинивает — это и требуется от "остаётся в системе
# между сессиями".
SESSION_LIFETIME_DAYS = _int_env("SESSION_LIFETIME_DAYS", 14)

# [EN] Send the session cookie over HTTPS only. Must stay false for local http
# development (python3 wsgi.py on 127.0.0.1:5000, docker compose on
# localhost:8000), and MUST be true on the server (nginx terminates TLS there).
#
# Why the default is still false, plus a warning, rather than true: a wrong
# `true` over plain http breaks login *silently* — the browser never stores or
# returns the cookie, so you land back on the login form with no error (see
# AGENTS.md §4). Defaulting to true would therefore hand that footgun to every
# local run and to the compose stack, which sets no SESSION_COOKIE_SECURE at
# all. Instead, "not set anywhere" is treated as a distinct case from an
# explicit "false" and is called out loudly on stderr (gunicorn error log /
# journald), so a production deploy cannot forget it in silence. An explicit
# `SESSION_COOKIE_SECURE=false` is a conscious choice and stays quiet.
#
# [RU] Отправлять cookie сессии только по HTTPS. Должно оставаться false для
# локальной разработки по http (python3 wsgi.py на 127.0.0.1:5000, docker
# compose на localhost:8000) и ОБЯЗАТЕЛЬНО true на сервере (TLS терминирует nginx).
#
# Почему по умолчанию всё же false плюс предупреждение, а не true: ошибочное
# `true` поверх обычного http ломает вход *молча* — браузер не сохраняет и не
# отправляет cookie, и вы возвращаетесь на форму входа без ошибки (см.
# AGENTS.md §4). Значение true по умолчанию раздало бы эту мину каждому
# локальному запуску и compose-стеку, где SESSION_COOKIE_SECURE не задан
# вовсе. Поэтому "нигде не задано" отличается от явного "false" и громко
# выводится в stderr (error-лог gunicorn / journald), так что продакшен-деплой
# не сможет забыть об этом молча. Явное `SESSION_COOKIE_SECURE=false` — это
# осознанный выбор, и он ничего не печатает.
_SESSION_COOKIE_SECURE_RAW = os.environ.get("SESSION_COOKIE_SECURE")
_SESSION_COOKIE_SECURE_VALUE = (_SESSION_COOKIE_SECURE_RAW or "").strip().lower()

SESSION_COOKIE_SECURE = _SESSION_COOKIE_SECURE_VALUE in ("1", "true", "yes", "on")

# [EN] Warn when the value is missing entirely, or is a typo we do not
# recognise ("True!", "sure", "0n") — both leave the cookie non-Secure, and both
# would otherwise pass unnoticed. An explicit false/0/no/off is silent.
# [RU] Предупреждаем, когда значение отсутствует вовсе или содержит опечатку,
# которую мы не распознаём ("True!", "sure", "0n") — и то и другое оставляет
# cookie без Secure и иначе прошло бы незамеченным. Явное false/0/no/off молчит.
if not SESSION_COOKIE_SECURE and _SESSION_COOKIE_SECURE_VALUE not in (
    "0", "false", "no", "off",
):
    _reason_en = (
        "is not set"
        if _SESSION_COOKIE_SECURE_RAW is None
        else f"has an unrecognised value {_SESSION_COOKIE_SECURE_RAW!r}"
    )
    _reason_ru = (
        "не задан"
        if _SESSION_COOKIE_SECURE_RAW is None
        else f"содержит нераспознанное значение {_SESSION_COOKIE_SECURE_RAW!r}"
    )
    # [EN] Printed once, at import. stderr rather than `warnings` so no warning
    # filter can hide it, and no logging config has to exist yet. It reaches the
    # gunicorn error log under systemd and `docker compose logs app` in compose.
    # [RU] Печатается один раз, при импорте. stderr, а не `warnings`, чтобы
    # никакой фильтр предупреждений не смог это скрыть и чтобы не требовалась
    # уже настроенная система логирования. Попадает в error-лог gunicorn под
    # systemd и в `docker compose logs app` в compose.
    print(
        f"WARNING: SESSION_COOKIE_SECURE {_reason_en} — the session cookie will "
        "be sent over plain HTTP and can be stolen in transit. Set "
        "SESSION_COOKIE_SECURE=true in .env on any HTTPS deployment; set it "
        "explicitly to false to silence this on a local http setup.\n"
        f"ВНИМАНИЕ: SESSION_COOKIE_SECURE {_reason_ru} — cookie сессии будет "
        "передаваться по обычному HTTP и может быть перехвачена. На любом "
        "HTTPS-развёртывании задайте SESSION_COOKIE_SECURE=true в .env; для "
        "локального http задайте явное false, чтобы убрать это сообщение.",
        file=sys.stderr,
    )

# [EN] Invite links expire — an old link found in a chat log should not still
# grant access.
# [RU] Ссылки-приглашения истекают — старая ссылка, найденная в переписке, не
# должна по-прежнему давать доступ.
INVITE_TTL_HOURS = _int_env("INVITE_TTL_HOURS", 72)

# [EN] Minimum password length enforced when an invite is accepted.
# [RU] Минимальная длина пароля при принятии приглашения.
PASSWORD_MIN_LENGTH = _int_env("PASSWORD_MIN_LENGTH", 10)

PAGE_SIZE = 50
