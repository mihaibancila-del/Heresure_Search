"""
[EN]
Password and token primitives. Pure functions — no Flask, no SQL, no request
state — so both the web app and scripts/manage_users.py use exactly the same
hashing rules.

Hashing comes from werkzeug.security, which ships with Flask. That is
deliberate: it adds no entry to requirements.txt (see AGENTS.md §1) while still
using a real password KDF (scrypt by default) rather than a bare digest.

[RU]
Примитивы для паролей и токенов. Чистые функции — без Flask, без SQL, без
состояния запроса — поэтому и веб-приложение, и scripts/manage_users.py
используют одни и те же правила хеширования.

Хеширование берётся из werkzeug.security, который поставляется вместе с Flask.
Это сделано намеренно: не добавляется ни одной строки в requirements.txt
(см. AGENTS.md §1), но при этом используется настоящий KDF для паролей
(по умолчанию scrypt), а не простой дайджест.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash, generate_password_hash

# [EN] A hash of a password that cannot be entered, used to spend the same CPU
# time on a login attempt for an unknown email as for a known one. Without this
# the response time tells an attacker which emails exist.
# [RU] Хеш пароля, который невозможно ввести; нужен, чтобы на попытку входа с
# неизвестным email тратилось столько же процессорного времени, сколько на
# известный. Без этого время ответа выдаёт атакующему, какие email существуют.
_DUMMY_HASH = generate_password_hash("password-that-is-never-valid")


def hash_password(password: str) -> str:
    """[EN] scrypt hash, salt included in the returned string.
    [RU] scrypt-хеш, соль включена в возвращаемую строку."""
    return generate_password_hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """[EN] Checks a password against a stored hash. A None hash (invite not yet
    accepted, or a deactivated user) still performs a dummy comparison so the
    timing matches a real check — see _DUMMY_HASH.

    [RU] Проверяет пароль по сохранённому хешу. Если хеш None (приглашение ещё
    не принято или пользователь отключён), всё равно выполняется фиктивное
    сравнение, чтобы время совпадало с настоящей проверкой — см. _DUMMY_HASH."""
    if not password_hash:
        check_password_hash(_DUMMY_HASH, password)
        return False
    return check_password_hash(password_hash, password)


def new_invite_token() -> str:
    """[EN] The raw one-time token that goes into the invite URL. 32 bytes of
    urlsafe randomness — this is the only secret protecting the invite, and it
    is shown to the admin exactly once.
    [RU] Сырой одноразовый токен для URL приглашения. 32 байта urlsafe-случайности —
    это единственный секрет, защищающий приглашение, и админу он показывается
    ровно один раз."""
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """[EN] sha256 hex of an invite token, for storage and lookup. A plain digest
    is right here (unlike passwords): the token is 256 bits of true randomness,
    so it cannot be brute-forced or guessed from a dictionary, and lookups need
    to be fast and deterministic.
    [RU] sha256-хеш токена приглашения в hex, для хранения и поиска. Простой
    дайджест здесь уместен (в отличие от паролей): токен — 256 бит настоящей
    случайности, его нельзя подобрать по словарю, а поиск должен быть быстрым и
    детерминированным."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_equal(left: str, right: str) -> bool:
    """[EN] Constant-time comparison for token hashes.
    [RU] Сравнение хешей токенов за постоянное время."""
    return hmac.compare_digest(left, right)


def invite_expiry(hours: int) -> datetime:
    """[EN] Timezone-aware expiry timestamp; the column is TIMESTAMPTZ, so a
    naive datetime here would be interpreted in the server's local zone.
    [RU] Метка истечения с часовым поясом; колонка TIMESTAMPTZ, поэтому naive
    datetime здесь был бы истолкован в локальной зоне сервера."""
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def normalize_email(email: str) -> str:
    """[EN] Lowercased and trimmed — matches the users_email_lower_idx unique
    index, so "Alice@x.com" and "alice@x.com" cannot become two accounts.
    [RU] В нижнем регистре и без пробелов по краям — соответствует уникальному
    индексу users_email_lower_idx, поэтому "Alice@x.com" и "alice@x.com" не
    станут двумя аккаунтами."""
    return email.strip().lower()
