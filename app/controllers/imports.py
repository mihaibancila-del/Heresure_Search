"""
[EN]
The imports area:

  GET  /imports                 run history + current status (any signed-in user)
  POST /imports/run             start an import now            (admin)
  GET  /imports/settings        filters + schedule             (admin)
  POST /imports/settings/filters                               (admin)
  POST /imports/settings/schedule                              (admin)

History is readable by everyone so any user can see whether the data is fresh;
everything that starts an import or changes what gets imported is admin-only,
because a run downloads ~330MB and mutates shared data.

[RU]
Раздел импортов:

  GET  /imports                 история запусков + текущий статус (любой вошедший)
  POST /imports/run             запустить импорт сейчас           (админ)
  GET  /imports/settings        фильтры + расписание              (админ)
  POST /imports/settings/filters                                  (админ)
  POST /imports/settings/schedule                                 (админ)

История доступна всем, чтобы любой пользователь видел, свежие ли данные; всё, что
запускает импорт или меняет его состав, — только для админов, потому что запуск
скачивает ~330MB и меняет общие данные.
"""

from zoneinfo import available_timezones

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app import jobs
from app.import_catalog import COUNTIES, LICENSE_TYPES
from app.models import db, imports as imports_model
from app.views.auth import admin_required, current_user

bp = Blueprint("imports", __name__, url_prefix="/imports")

# [EN] Offered in the schedule dropdown. A short list beats 600 IANA zones for a
# team working one market; any other zone can still be stored by the CLI, and
# whatever is saved is shown even if it is not in this list.
# [RU] Предлагается в выпадающем списке расписания. Короткий список лучше 600 зон
# IANA для команды, работающей с одним рынком; любую другую зону всё ещё можно
# записать через CLI, и сохранённое значение показывается, даже если его нет здесь.
COMMON_TIMEZONES = (
    "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles",
    "UTC", "Europe/London", "Europe/Bucharest", "Europe/Chisinau", "Europe/Moscow",
)


@bp.route("")
def index():
    """[EN] Status + history. The template polls this page while a run is active.
    [RU] Статус + история. Шаблон перезагружает страницу, пока запуск активен."""
    with db.connection() as conn:
        settings = imports_model.get_settings(conn)
        active = imports_model.active_run(conn)
        runs = imports_model.recent_runs(conn, limit=50)

    return render_template(
        "imports.html", settings=settings, active=active, runs=runs,
        counties=list(COUNTIES.keys()),
    )


# [EN] Route OUTER, admin_required inner — see app/views/auth.py.
# [RU] Маршрут ВНЕШНИЙ, admin_required внутренний — см. app/views/auth.py.
@bp.route("/run", methods=["POST"])
@admin_required
def run():
    me = current_user()

    with db.connection() as conn:
        # [EN] Clear crashed rows first, or a killed run would make this look busy
        # forever and no import could ever be started again.
        # [RU] Сначала закрываем упавшие строки, иначе убитый запуск навсегда
        # выглядел бы занятостью и новый импорт нельзя было бы запустить.
        imports_model.mark_stale_runs_failed(conn)

        active = imports_model.active_run(conn)
        if active:
            flash(f"Import #{active['id']} is already running — started "
                  f"{active['started_at']:%H:%M}.", "error")
            return redirect(url_for("imports.index"))

        settings = imports_model.get_settings(conn)
        if not settings["counties"] or not settings["license_types"]:
            flash("Choose at least one county and one license type before importing.",
                  "error")
            return redirect(url_for("imports.settings"))

        run_id = imports_model.create_run(
            conn, "manual", me["email"],
            list(settings["counties"]), list(settings["license_types"]),
        )

    # [EN] Spawned AFTER the row is committed, so the child cannot look for a run
    # that is not visible to its own connection yet.
    # [RU] Запускается ПОСЛЕ фиксации строки, чтобы дочерний процесс не искал
    # запуск, ещё не видимый его собственному соединению.
    jobs.start_import(run_id, "manual", me["email"])

    flash(f"Import #{run_id} started. This page refreshes while it runs.", "success")
    return redirect(url_for("imports.index"))


@bp.route("/settings")
@admin_required
def settings():
    with db.connection() as conn:
        current = imports_model.get_settings(conn)

    # [EN] Show the saved timezone even when it is not one of COMMON_TIMEZONES, so
    # opening this page can never silently rewrite a value set via the CLI.
    # [RU] Показываем сохранённую зону, даже если её нет в COMMON_TIMEZONES, чтобы
    # открытие страницы не могло молча перезаписать значение, заданное через CLI.
    zones = list(COMMON_TIMEZONES)
    if current["schedule_timezone"] not in zones:
        zones.insert(0, current["schedule_timezone"])

    return render_template(
        "import_settings.html", settings=current,
        all_counties=COUNTIES, county_names=list(COUNTIES.keys()),
        license_types=LICENSE_TYPES, timezones=zones,
    )


@bp.route("/settings/filters", methods=["POST"])
@admin_required
def save_filters():
    # [EN] Intersect with the catalogue rather than trusting the form: these values
    # decide what a later import matches, and a hand-crafted POST should not be
    # able to store a county name that resolves to no cities.
    # [RU] Пересекаем с каталогом, а не доверяем форме: эти значения определяют, что
    # будет соответствовать при импорте, и поддельный POST не должен уметь сохранить
    # название округа, которое не разворачивается ни в один город.
    counties = [c for c in request.form.getlist("counties") if c in COUNTIES]
    types = [t for t in request.form.getlist("license_types") if t in LICENSE_TYPES]

    if not counties or not types:
        flash("Select at least one county and one license type.", "error")
        return redirect(url_for("imports.settings"))

    with db.connection() as conn:
        imports_model.save_filters(conn, counties, types, current_user()["email"])

    flash(f"Filters saved: {len(counties)} count{'y' if len(counties) == 1 else 'ies'}, "
          f"{len(types)} license type{'' if len(types) == 1 else 's'}. "
          f"They apply to the next import.", "success")
    return redirect(url_for("imports.settings"))


@bp.route("/settings/schedule", methods=["POST"])
@admin_required
def save_schedule():
    enabled = request.form.get("schedule_enabled") == "on"
    at_time = (request.form.get("schedule_time") or "").strip()
    timezone = (request.form.get("schedule_timezone") or "").strip()

    # [EN] <input type="time"> gives HH:MM, but a raw POST can give anything, and
    # this string goes into a TIME column.
    # [RU] <input type="time"> даёт HH:MM, но произвольный POST может дать что
    # угодно, а строка попадает в колонку TIME.
    if not _valid_time(at_time):
        flash("Enter a valid time as HH:MM.", "error")
        return redirect(url_for("imports.settings"))

    # [EN] Validated against the system tz database, not COMMON_TIMEZONES, so a
    # zone previously set via the CLI can still be re-saved from this form.
    # [RU] Проверяется по системной базе часовых поясов, а не по COMMON_TIMEZONES,
    # чтобы зону, ранее заданную через CLI, можно было сохранить и из этой формы.
    if timezone not in available_timezones():
        flash("Unknown timezone.", "error")
        return redirect(url_for("imports.settings"))

    with db.connection() as conn:
        imports_model.save_schedule(conn, enabled, at_time, timezone,
                                    current_user()["email"])

    if enabled:
        flash(f"Schedule saved: daily at {at_time} {timezone}.", "success")
    else:
        flash("Schedule disabled. Imports now only run when started by hand.",
              "success")
    return redirect(url_for("imports.settings"))


def _valid_time(value: str) -> bool:
    """[EN] HH:MM, 24-hour. Accepts the HH:MM:SS some browsers submit.
    [RU] HH:MM, 24-часовой формат. Принимает HH:MM:SS, который отправляют некоторые
    браузеры."""
    parts = value.split(":")
    if len(parts) not in (2, 3):
        return False
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59
