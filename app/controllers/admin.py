"""
[EN]
The admin page for accounts: invite someone, revoke a pending invite, and
deactivate or reactivate an account.

Invites are delivered by hand, not by SMTP. Creating one returns a link that is
shown to the admin ONCE and then never again — the raw token is not stored, only
its sha256. The admin passes the link to the new user over Slack or email
themselves. This is a deliberate choice: the web app never gains the ability to
send mail, so it cannot possibly reach the real agents in the licenses table
(AGENTS.md §1, "Never send a live email").

[RU]
Админ-страница для аккаунтов: пригласить человека, отозвать ожидающее
приглашение, отключить или снова включить аккаунт.

Приглашения передаются вручную, не по SMTP. При создании возвращается ссылка,
которая показывается админу ОДИН раз и больше никогда — сырой токен не хранится,
только его sha256. Админ сам передаёт ссылку новому пользователю через Slack или
почту. Это осознанный выбор: веб-приложение не получает возможности отправлять
письма, поэтому не может случайно достать до реальных агентов из таблицы licenses
(AGENTS.md §1, "Никогда не отправляйте живых писем").
"""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app import config
from app.models import db, imports as imports_model, user as user_model
from app.security import (
    hash_token,
    invite_expiry,
    new_invite_token,
    normalize_email,
)
from app.views.auth import admin_required, current_user

bp = Blueprint("admin", __name__, url_prefix="/admin")

_ROLES = ("member", "admin")


# [EN] Route OUTER, admin_required inner — see the note in app/views/auth.py.
# [RU] Маршрут ВНЕШНИЙ, admin_required внутренний — см. примечание в app/views/auth.py.
@bp.route("/users")
@admin_required
def users():
    with db.connection() as conn:
        rows = user_model.list_all(conn)
        # [EN] The "last sign-in" column is a timestamp, so this page needs the app
        # timezone too — otherwise it would be the one page still printing UTC.
        # [RU] Колонка "последний вход" — метка времени, поэтому этой странице тоже
        # нужен часовой пояс приложения, иначе она осталась бы единственной, где
        # печатается UTC.
        tz = imports_model.get_settings(conn)["timezone"]
    # [EN] invite_link is passed through one redirect via flash(), so it survives
    # the POST-redirect-GET without being stored anywhere.
    # [RU] invite_link передаётся через один redirect с помощью flash(), поэтому
    # переживает POST-redirect-GET и при этом нигде не сохраняется.
    return render_template("admin_users.html", users=rows, roles=_ROLES, tz=tz)


@bp.route("/users/invite", methods=["POST"])
@admin_required
def invite():
    email = normalize_email(request.form.get("email", ""))
    role = request.form.get("role", "member")

    if "@" not in email or len(email) < 3:
        flash("Enter a valid email address.", "error")
        return redirect(url_for("admin.users"))

    # [EN] Allowlist, not a free string — role goes into a CHECK-constrained column.
    # [RU] Белый список, а не произвольная строка — role попадает в колонку с CHECK.
    if role not in _ROLES:
        role = "member"

    token = new_invite_token()
    with db.connection() as conn:
        row = user_model.create_invite(
            conn, email, role, hash_token(token), invite_expiry(config.INVITE_TTL_HOURS)
        )

    # [EN] No row means the email already belongs to an account that has set a
    # password. Re-inviting must not silently reset a live account's credentials.
    # [RU] Отсутствие строки означает, что email уже принадлежит аккаунту с
    # заданным паролем. Повторное приглашение не должно молча сбрасывать доступ
    # живому аккаунту.
    if not row:
        flash(f"{email} already has an account. Deactivate it first to re-invite.", "error")
        return redirect(url_for("admin.users"))

    # [EN] _external=True so the link works when pasted into a chat window.
    # [RU] _external=True, чтобы ссылка работала при вставке в чат.
    link = url_for("auth.accept_invite", token=token, _external=True)

    # [EN] Two flashes: the sentence, and the link on its own under a category the
    # layout renders as a copy field. Passing them separately keeps the raw URL out
    # of a prose string, and the redirect (POST-redirect-GET) means a refresh does
    # not mint a second invite.
    # [RU] Два flash: текст и отдельно ссылка под категорией, которую каркас рисует
    # как поле для копирования. Раздельная передача не смешивает URL с текстом, а
    # redirect (POST-redirect-GET) означает, что обновление страницы не создаст
    # второе приглашение.
    #
    # [EN] Known and accepted: flash() puts the raw token in the session cookie,
    # which Flask signs but does NOT encrypt, so it is base64 plaintext for exactly
    # one redirect cycle (the next response rewrites the cookie without it). This is
    # not worth a server-side one-shot store, because every party who can read that
    # cookie already holds something strictly better:
    #   - XSS on this page reads the token straight out of the DOM — base.html
    #     renders it in an <input> on purpose, so HttpOnly buys nothing here;
    #   - anyone reading the browser profile or sniffing plain http (the
    #     SESSION_COOKIE_SECURE=false case) also has the admin's own login cookie,
    #     i.e. the power to mint fresh invites at will;
    #   - nginx logs the request line, not Cookie headers — but it DOES log
    #     /invite/<token> when the invitee clicks, and the admin pastes the same
    #     link into Slack. Those two channels are longer-lived than this one and
    #     are already accepted by the copy-paste design.
    # The token is single-use, expires after INVITE_TTL_HOURS, and is revocable
    # from this same page. Do not "fix" this by dropping the redirect — that is
    # what stops a refresh from minting a second invite. A worker-local dict would
    # be worse than useless: gunicorn runs several workers, so the follow-up GET
    # would miss the store about half the time.
    #
    # [RU] Известно и принято: flash() кладёт сырой токен в cookie сессии, которую
    # Flask подписывает, но НЕ шифрует, — то есть это открытый base64 ровно на один
    # цикл редиректа (следующий ответ перезаписывает cookie без него). Отдельное
    # серверное одноразовое хранилище того не стоит, потому что любой, кто может
    # прочитать эту cookie, уже располагает чем-то заведомо более ценным:
    #   - XSS на этой странице читает токен прямо из DOM — base.html намеренно
    #     рисует его в <input>, поэтому HttpOnly здесь ничего не даёт;
    #   - тот, кто читает профиль браузера или слушает обычный http (случай
    #     SESSION_COOKIE_SECURE=false), имеет и cookie входа самого админа, то есть
    #     возможность выпускать новые приглашения сколько угодно;
    #   - nginx пишет в лог строку запроса, а не заголовки Cookie, — но он ПИШЕТ
    #     /invite/<token>, когда приглашённый переходит по ссылке, и ту же ссылку
    #     админ вставляет в Slack. Эти два канала живут дольше и уже приняты самой
    #     схемой с копированием ссылки вручную.
    # Токен одноразовый, истекает через INVITE_TTL_HOURS и отзывается с этой же
    # страницы. Не «чините» это удалением редиректа — именно он не даёт обновлению
    # страницы создать второе приглашение. Словарь в памяти воркера был бы только
    # хуже: gunicorn запускает несколько воркеров, и следующий GET примерно в
    # половине случаев не найдёт запись.
    flash(
        f"Invite created for {email} ({role}). It expires in "
        f"{config.INVITE_TTL_HOURS} hours.",
        "success",
    )
    flash(link, "invite_link")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/revoke", methods=["POST"])
@admin_required
def revoke(user_id: int):
    with db.connection() as conn:
        removed = user_model.revoke_invite(conn, user_id)
    # [EN] removed is 0 if the id was already accepted (a real account) or gone —
    # revoke_invite refuses to delete anything with a password, so this stays safe.
    # [RU] removed = 0, если id уже принят (реальный аккаунт) или отсутствует —
    # revoke_invite не удаляет ничего с паролем, поэтому это остаётся безопасным.
    if removed:
        flash("Invite revoked and removed. The link no longer works.", "success")
    else:
        flash("Nothing to revoke — that account has already been accepted.", "error")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/deactivate", methods=["POST"])
@admin_required
def deactivate(user_id: int):
    me = current_user()

    # [EN] Locking yourself out is the one mistake with no in-app recovery —
    # you would need scripts/manage_users.py on the server to undo it.
    # [RU] Заблокировать себя — единственная ошибка, которую нельзя исправить в
    # приложении: понадобится scripts/manage_users.py на сервере.
    if me["id"] == user_id:
        flash("You cannot deactivate your own account.", "error")
        return redirect(url_for("admin.users"))

    with db.connection() as conn:
        target = user_model.find_by_id(conn, user_id)
        if not target:
            flash("No such user.", "error")
            return redirect(url_for("admin.users"))

        # [EN] Refuse to remove the last active admin — otherwise nobody can invite
        # anyone again and the account system is unreachable. The guard must only
        # fire when THIS target is itself a counted active admin (admin + active +
        # already accepted): a pending admin invite has no password, cannot log in,
        # and is not counted, so deactivating it never removes the last real admin.
        # Checking only role here was the bug — it blocked deactivating a pending
        # co-admin while the count (accepted admins) was legitimately 1.
        # [RU] Отказываемся убирать последнего активного админа — иначе никто не
        # сможет больше никого пригласить, и система аккаунтов станет недоступной.
        # Проверка должна срабатывать только если ИМЕННО этот target — учитываемый
        # активный админ (admin + active + уже принявший приглашение): ожидающий
        # админ-инвайт без пароля войти не может и не считается, поэтому его
        # отключение не убирает последнего настоящего админа. Проверка только по
        # role и была багом — она блокировала отключение ожидающего со-админа, пока
        # счётчик (принятых админов) был законно равен 1.
        target_is_counted_admin = (
            target["role"] == "admin"
            and target["is_active"]
            and target["password_hash"] is not None
        )
        if target_is_counted_admin and user_model.count_active_admins(conn) <= 1:
            flash("This is the last active admin. Promote someone else first.", "error")
            return redirect(url_for("admin.users"))

        user_model.set_active(conn, user_id, False)

    flash("Account deactivated. Any active session ends on their next request.", "success")
    return redirect(url_for("admin.users"))


@bp.route("/users/<int:user_id>/activate", methods=["POST"])
@admin_required
def activate(user_id: int):
    with db.connection() as conn:
        user_model.set_active(conn, user_id, True)
    flash("Account reactivated.", "success")
    return redirect(url_for("admin.users"))
