"""
[EN]
Account management from the command line. Its reason to exist is the
chicken-and-egg problem: invites are issued from /admin/users, but that page
requires an admin session, and a fresh database has no users at all. This script
creates the first one. After that, day-to-day inviting happens in the web UI.

It is also the only recovery path if every admin account is locked out — which is
why it must be run on the machine with database access, not exposed anywhere.

Run from the repo root, as a module (AGENTS.md §1):

    python3 -m scripts.manage_users list
    python3 -m scripts.manage_users invite alice@example.com --role admin
    python3 -m scripts.manage_users set-password alice@example.com
    python3 -m scripts.manage_users deactivate bob@example.com
    python3 -m scripts.manage_users activate bob@example.com

`invite` prints a one-time link. `set-password` prompts for a password and skips
the invite step entirely — the quickest way to create the very first admin.

[RU]
Управление аккаунтами из командной строки. Причина существования — проблема
курицы и яйца: приглашения выдаются на /admin/users, но эта страница требует
сессии админа, а в чистой базе пользователей нет вообще. Этот скрипт создаёт
первого. Дальше повседневные приглашения делаются в веб-интерфейсе.

Это также единственный путь восстановления, если доступ потерян ко всем
админ-аккаунтам — поэтому запускать его нужно на машине с доступом к базе и
никуда не выставлять.

Запуск из корня репозитория, как модуль (AGENTS.md §1):

    python3 -m scripts.manage_users list
    python3 -m scripts.manage_users invite alice@example.com --role admin
    python3 -m scripts.manage_users set-password alice@example.com
    python3 -m scripts.manage_users deactivate bob@example.com
    python3 -m scripts.manage_users activate bob@example.com

`invite` печатает одноразовую ссылку. `set-password` спрашивает пароль и
полностью пропускает шаг приглашения — самый быстрый способ создать первого админа.
"""

import argparse
import getpass
import sys

from app import config
from app.models import db, user as user_model
from app.security import (
    hash_password,
    hash_token,
    invite_expiry,
    new_invite_token,
    normalize_email,
)

# [EN] Where the invite link points. The script has no request context, so it
# cannot use url_for(_external=True) — the base URL has to be told to it.
# [RU] Куда ведёт ссылка-приглашение. У скрипта нет контекста запроса, поэтому
# url_for(_external=True) недоступен — базовый URL нужно передать явно.
DEFAULT_BASE_URL = "http://127.0.0.1:5000"


def cmd_list(args) -> int:
    with db.connection() as conn:
        rows = user_model.list_all(conn)

    if not rows:
        print("No users yet. Create the first admin:")
        print("  python3 -m scripts.manage_users set-password you@example.com --role admin")
        return 0

    print(f"{'EMAIL':<40} {'ROLE':<8} {'STATE':<16} LAST SIGN-IN")
    for row in rows:
        if not row["is_active"]:
            state = "deactivated"
        elif row["is_pending"] and row["invite_expired"]:
            state = "invite expired"
        elif row["is_pending"]:
            state = "invite pending"
        else:
            state = "active"
        last = row["last_login_at"].strftime("%Y-%m-%d %H:%M") if row["last_login_at"] else "-"
        print(f"{row['email']:<40} {row['role']:<8} {state:<16} {last}")
    return 0


def cmd_invite(args) -> int:
    email = normalize_email(args.email)
    token = new_invite_token()

    with db.connection() as conn:
        row = user_model.create_invite(
            conn, email, args.role, hash_token(token),
            invite_expiry(config.INVITE_TTL_HOURS),
        )

    if not row:
        print(f"{email} already has a password set. Deactivate the account first, "
              f"or use set-password to overwrite it.", file=sys.stderr)
        return 1

    print(f"Invite created for {email} (role: {args.role}).")
    print(f"Expires in {config.INVITE_TTL_HOURS} hours. Send them this link:\n")
    print(f"  {args.base_url.rstrip('/')}/invite/{token}\n")
    # [EN] The raw token is not stored anywhere — only its sha256. If this output
    # is lost, issue a new invite rather than trying to recover it.
    # [RU] Сырой токен нигде не сохраняется — только его sha256. Если этот вывод
    # потерян, выдайте новое приглашение, а не пытайтесь его восстановить.
    print("This link is shown once and cannot be recovered later.")
    return 0


def cmd_set_password(args) -> int:
    """[EN] Creates the account if needed and sets a password directly, bypassing
    the invite flow. This is the bootstrap path for the first admin, and the
    break-glass path when everyone is locked out.
    [RU] Создаёт аккаунт при необходимости и задаёт пароль напрямую, минуя
    приглашение. Это путь начальной установки для первого админа и аварийный путь,
    когда доступ потерян у всех."""
    email = normalize_email(args.email)

    # [EN] getpass so the password never lands in shell history or the process list.
    # [RU] getpass, чтобы пароль не попал ни в историю shell, ни в список процессов.
    password = getpass.getpass("New password: ")
    if len(password) < config.PASSWORD_MIN_LENGTH:
        print(f"Password must be at least {config.PASSWORD_MIN_LENGTH} characters.",
              file=sys.stderr)
        return 1
    if password != getpass.getpass("Repeat password: "):
        print("The two passwords do not match.", file=sys.stderr)
        return 1

    with db.connection() as conn:
        existing = user_model.find_by_email(conn, email)

        if not existing:
            # [EN] Create the row as a pending invite first, then immediately accept
            # it — reusing accept_invite() keeps password writing in one place.
            # [RU] Сначала создаём строку как ожидающее приглашение, затем сразу
            # принимаем его — переиспользование accept_invite() держит запись
            # пароля в одном месте.
            user_model.create_invite(
                conn, email, args.role, hash_token(new_invite_token()),
                invite_expiry(config.INVITE_TTL_HOURS),
            )
            existing = user_model.find_by_email(conn, email)
            user_model.accept_invite(conn, existing["id"], hash_password(password))
            print(f"Created {email} as {args.role} with a password set.")
        else:
            user_model.force_set_password(conn, existing["id"], hash_password(password))
            print(f"Password updated for {email}.")
            # [EN] force_set_password deliberately leaves is_active alone, so say so
            # rather than letting the operator assume the account can now sign in.
            # [RU] force_set_password намеренно не меняет is_active, поэтому говорим
            # об этом, а не оставляем оператора думать, что вход уже возможен.
            if not existing["is_active"]:
                print(f"NOTE: {email} is deactivated and still cannot sign in. "
                      f"Run: python3 -m scripts.manage_users activate {email}")

    return 0


def cmd_deactivate(args) -> int:
    return _set_active(args.email, False)


def cmd_activate(args) -> int:
    return _set_active(args.email, True)


def _set_active(email: str, is_active: bool) -> int:
    email = normalize_email(email)
    with db.connection() as conn:
        row = user_model.find_by_email(conn, email)
        if not row:
            print(f"No such user: {email}", file=sys.stderr)
            return 1

        # [EN] Same guard as the admin page, and it must stay identical to it
        # (app/controllers/admin.py, deactivate): never remove the last way in.
        # It fires only when THIS target is itself a counted active admin —
        # admin + active + already accepted — because count_active_admins()
        # counts exactly those. A pending admin invite has no password, cannot
        # log in and is not counted, so deactivating it removes nobody's access.
        # [RU] Та же защита, что на админ-странице, и она должна оставаться
        # идентичной ей (app/controllers/admin.py, deactivate): не убирать
        # последний вход. Срабатывает только если ИМЕННО этот target —
        # учитываемый активный админ (admin + active + уже принявший
        # приглашение), потому что count_active_admins() считает именно таких.
        # Ожидающий админ-инвайт без пароля войти не может и не считается,
        # поэтому его отключение ни у кого не отбирает доступ.
        target_is_counted_admin = (
            row["role"] == "admin"
            and row["is_active"]
            and row["password_hash"] is not None
        )
        if not is_active and target_is_counted_admin and user_model.count_active_admins(conn) <= 1:
            print("Refusing to deactivate the last active admin.", file=sys.stderr)
            return 1

        user_model.set_active(conn, row["id"], is_active)

    print(f"{email} is now {'active' if is_active else 'deactivated'}.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage Agents_Heresure accounts (invite-only access).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="show all accounts").set_defaults(func=cmd_list)

    p_invite = sub.add_parser("invite", help="create a one-time invite link")
    p_invite.add_argument("email")
    p_invite.add_argument("--role", choices=("member", "admin"), default="member")
    p_invite.add_argument("--base-url", default=DEFAULT_BASE_URL,
                          help=f"public base URL for the link (default {DEFAULT_BASE_URL})")
    p_invite.set_defaults(func=cmd_invite)

    p_pw = sub.add_parser("set-password",
                          help="set a password directly (bootstrap the first admin)")
    p_pw.add_argument("email")
    p_pw.add_argument("--role", choices=("member", "admin"), default="admin")
    p_pw.set_defaults(func=cmd_set_password)

    p_off = sub.add_parser("deactivate", help="revoke access")
    p_off.add_argument("email")
    p_off.set_defaults(func=cmd_deactivate)

    p_on = sub.add_parser("activate", help="restore access")
    p_on.add_argument("email")
    p_on.set_defaults(func=cmd_activate)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
