"""
[EN]
Data access for the `users` table — every SQL statement about accounts and
invites lives here, mirroring app/models/license.py. Controllers call these
functions; they never write SQL themselves.

An invite is not a separate entity: a pending invite IS a users row with
password_hash IS NULL and a live invite_token_hash. Accepting an invite sets the
password and clears the token, which is what makes it one-time.

[RU]
Доступ к данным таблицы `users` — все SQL-запросы про аккаунты и приглашения
живут здесь, по аналогии с app/models/license.py. Контроллеры вызывают эти
функции и никогда не пишут SQL сами.

Приглашение — не отдельная сущность: ожидающее приглашение ЭТО строка users, у
которой password_hash IS NULL и живой invite_token_hash. Принятие приглашения
проставляет пароль и очищает токен — именно поэтому оно одноразовое.
"""

import psycopg2.extras

# [EN] Columns the app reads about a user. Kept in one place so every query
# returns the same shape; password_hash is listed explicitly only where needed.
# [RU] Колонки, которые приложение читает о пользователе. Держим в одном месте,
# чтобы все запросы возвращали одинаковую форму; password_hash перечисляется
# явно только там, где он нужен.
_FIELDS = """
    id, email, role, is_active, password_hash,
    invite_expires_at, invited_at, accepted_at, last_login_at
"""


def _dict_cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


def find_by_id(conn, user_id: int) -> dict | None:
    """[EN] Used on every request to reload the signed-in user, so deactivating
    an account takes effect immediately instead of waiting for the cookie to expire.
    [RU] Используется на каждом запросе для перезагрузки вошедшего пользователя,
    поэтому отключение аккаунта действует сразу, а не после истечения cookie."""
    with _dict_cursor(conn) as cur:
        cur.execute(f"SELECT {_FIELDS} FROM users WHERE id = %s;", (user_id,))
        return cur.fetchone()


def find_by_email(conn, email: str) -> dict | None:
    """[EN] Case-insensitive lookup, matching users_email_lower_idx.
    [RU] Поиск без учёта регистра, как в users_email_lower_idx."""
    with _dict_cursor(conn) as cur:
        cur.execute(f"SELECT {_FIELDS} FROM users WHERE lower(email) = lower(%s);", (email,))
        return cur.fetchone()


def find_by_invite_token_hash(conn, token_hash: str) -> dict | None:
    """[EN] Finds a live, unexpired, unaccepted invite. Expiry is compared in the
    database (now()) rather than in Python, so the app server's clock and
    timezone cannot widen the window.
    [RU] Находит живое, неистёкшее и непринятое приглашение. Срок сравнивается в
    базе (now()), а не в Python, поэтому часы и часовой пояс сервера приложения
    не могут расширить окно."""
    with _dict_cursor(conn) as cur:
        cur.execute(
            f"""
            SELECT {_FIELDS} FROM users
            WHERE invite_token_hash = %s
              AND is_active
              AND password_hash IS NULL
              AND invite_expires_at > now();
            """,
            (token_hash,),
        )
        return cur.fetchone()


def list_all(conn) -> list[dict]:
    """[EN] Every account, for the admin page. Pending invites first, so an admin
    sees outstanding ones without scrolling.
    [RU] Все аккаунты для админ-страницы. Сначала ожидающие приглашения, чтобы
    админ видел незакрытые без прокрутки."""
    with _dict_cursor(conn) as cur:
        cur.execute(
            f"""
            SELECT {_FIELDS},
                   (password_hash IS NULL) AS is_pending,
                   (invite_token_hash IS NOT NULL
                    AND invite_expires_at <= now()) AS invite_expired
            FROM users
            ORDER BY (password_hash IS NULL) DESC, lower(email);
            """
        )
        return cur.fetchall()


def create_invite(conn, email: str, role: str, token_hash: str, expires_at) -> dict:
    """[EN] Creates a pending account, or re-issues the invite if one is already
    pending for that email. The ON CONFLICT branch only ever touches rows whose
    password_hash IS NULL, so re-inviting can never reset an active user's
    password or silently take over a live account — that path returns no row and
    the caller reports "already registered".

    [RU] Создаёт ожидающий аккаунт или перевыпускает приглашение, если для этого
    email оно уже ожидает. Ветка ON CONFLICT затрагивает только строки с
    password_hash IS NULL, поэтому повторное приглашение никогда не сбросит
    пароль активного пользователя и не перехватит живой аккаунт — в этом случае
    строка не возвращается, и вызывающий сообщает "уже зарегистрирован"."""
    with _dict_cursor(conn) as cur:
        cur.execute(
            """
            INSERT INTO users (email, role, invite_token_hash, invite_expires_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (lower(email)) DO UPDATE
                SET invite_token_hash = EXCLUDED.invite_token_hash,
                    invite_expires_at = EXCLUDED.invite_expires_at,
                    role              = EXCLUDED.role,
                    is_active         = TRUE,
                    invited_at        = now()
                WHERE users.password_hash IS NULL
            RETURNING id, email, role;
            """,
            (email, role, token_hash, expires_at),
        )
        row = cur.fetchone()
        conn.commit()
        return row


def accept_invite(conn, user_id: int, password_hash: str) -> bool:
    """[EN] Sets the password and burns the token in one statement. The
    `invite_token_hash IS NOT NULL` guard makes this atomic against a double
    submit: the second request updates zero rows and is rejected, so one invite
    link can only ever create one password.

    [RU] Проставляет пароль и сжигает токен одним запросом. Условие
    `invite_token_hash IS NOT NULL` делает операцию атомарной против двойной
    отправки: второй запрос обновит ноль строк и будет отклонён, поэтому одна
    ссылка-приглашение может задать пароль только один раз."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET password_hash     = %s,
                accepted_at       = now(),
                invite_token_hash = NULL,
                invite_expires_at = NULL
            WHERE id = %s
              AND invite_token_hash IS NOT NULL
              AND is_active;
            """,
            (password_hash, user_id),
        )
        updated = cur.rowcount
        conn.commit()
        return updated == 1


def force_set_password(conn, user_id: int, password_hash: str) -> None:
    """[EN] Overwrites a password without an invite token. Deliberately NOT reachable
    from the web app — only scripts/manage_users.py calls it, as the break-glass path
    for when every admin is locked out. Any pending invite is burned at the same time,
    and is_active is left untouched so a deactivated account is not silently revived.

    [RU] Перезаписывает пароль без токена приглашения. Намеренно НЕ доступно из
    веб-приложения — вызывается только из scripts/manage_users.py как аварийный путь,
    когда доступ потерян у всех админов. Ожидающее приглашение сжигается тут же, а
    is_active не трогается, чтобы отключённый аккаунт не ожил незаметно."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET password_hash     = %s,
                accepted_at       = COALESCE(accepted_at, now()),
                invite_token_hash = NULL,
                invite_expires_at = NULL
            WHERE id = %s;
            """,
            (password_hash, user_id),
        )
        conn.commit()


def touch_last_login(conn, user_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE users SET last_login_at = now() WHERE id = %s;", (user_id,))
        conn.commit()


def set_active(conn, user_id: int, is_active: bool) -> None:
    """[EN] Deactivating also revokes any pending invite for that row, so a
    disabled account cannot be resurrected with an old link.
    [RU] Отключение также отзывает ожидающее приглашение для этой строки, чтобы
    отключённый аккаунт нельзя было восстановить по старой ссылке."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE users
            SET is_active         = %s,
                invite_token_hash = CASE WHEN %s THEN invite_token_hash ELSE NULL END
            WHERE id = %s;
            """,
            (is_active, is_active, user_id),
        )
        conn.commit()


def revoke_invite(conn, user_id: int) -> int:
    """[EN] Deletes a pending invite outright. Because an invite IS the user row,
    a never-accepted invite has no password and no history to keep, so revoking it
    removes it from the list entirely and frees the email to be invited again.

    The `password_hash IS NULL` guard is load-bearing: it makes this DELETE
    incapable of touching an account that has ever been accepted. Returns the
    number of rows removed (0 if the id was already accepted or gone).

    [RU] Полностью удаляет ожидающее приглашение. Поскольку приглашение ЭТО и есть
    строка пользователя, у непринятого приглашения нет ни пароля, ни истории,
    которые стоило бы хранить, поэтому отзыв убирает его из списка целиком и
    освобождает email для повторного приглашения.

    Условие `password_hash IS NULL` — несущее: оно делает этот DELETE неспособным
    затронуть аккаунт, который когда-либо был принят. Возвращает число удалённых
    строк (0, если id уже принят или отсутствует)."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM users WHERE id = %s AND password_hash IS NULL;",
            (user_id,),
        )
        removed = cur.rowcount
        conn.commit()
        return removed


def count_active_admins(conn) -> int:
    """[EN] Guards against removing the last way in: the admin page refuses to
    deactivate or demote the final active admin.
    [RU] Защита от потери последнего входа: админ-страница отказывается отключать
    или понижать последнего активного админа."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM users
            WHERE role = 'admin' AND is_active AND password_hash IS NOT NULL;
            """
        )
        return cur.fetchone()[0]
