"""
[EN]
Runs one import and records it in `import_runs`. This is the single entry point
for every kind of import:

  - the "Run import now" button   -> the web app spawns this as a subprocess
  - the systemd timer             -> `--trigger scheduled --if-due`
  - by hand                       -> `python3 -m scripts.run_import`
  - `python3 -m scripts.parser`   -> delegates here

Why the web app spawns a subprocess instead of importing this module: a full
import downloads ~330MB and takes minutes, far longer than a request may last,
and AGENTS.md §2 forbids the web app importing scripts/. A detached subprocess
satisfies both — it outlives the request and even a gunicorn worker restart, and
reports progress through the database rather than a return value.

Two runs must never overlap (they would fight over staging_licenses.csv and
double the work). That is enforced with a Postgres ADVISORY LOCK rather than a
status column, because an advisory lock is released automatically when the
connection dies — so a killed process cannot leave a lock behind that blocks
every future import.

Usage:
    python3 -m scripts.run_import                          # run now, trigger=manual
    python3 -m scripts.run_import --trigger scheduled --if-due
    python3 -m scripts.run_import --run-id 42              # adopt a row the UI created

[RU]
Выполняет один импорт и записывает его в `import_runs`. Это единственная точка
входа для всех видов импорта:

  - кнопка "Запустить импорт"   -> веб-приложение запускает это как подпроцесс
  - таймер systemd              -> `--trigger scheduled --if-due`
  - вручную                     -> `python3 -m scripts.run_import`
  - `python3 -m scripts.parser` -> делегирует сюда

Почему веб-приложение запускает подпроцесс, а не импортирует модуль: полный импорт
скачивает ~330MB и занимает минуты — намного дольше, чем может длиться запрос, а
AGENTS.md §2 запрещает веб-приложению импортировать scripts/. Отсоединённый
подпроцесс решает и то, и другое — он живёт дольше запроса и даже перезапуска
воркера gunicorn, а о прогрессе сообщает через базу, а не возвращаемым значением.

Два запуска не должны пересекаться (они бы конкурировали за staging_licenses.csv и
удвоили работу). Это обеспечивается ADVISORY LOCK в Postgres, а не колонкой
статуса, потому что advisory lock освобождается автоматически при обрыве
соединения — поэтому убитый процесс не может оставить блокировку, которая
заблокирует все будущие импорты.
"""

import argparse
import sys
import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.import_catalog import cities_for, unknown_counties, unknown_license_types
from app.models import db, imports as imports_model
from scripts import parser

# [EN] Any 64-bit constant works; it just has to be the same in every process
# that takes the lock. Kept literal (not hashtext of a string) so it is obvious
# and stable across Postgres versions.
# [RU] Подойдёт любая 64-битная константа; важно лишь, чтобы она была одинаковой
# во всех процессах, берущих блокировку. Оставлена литералом (а не hashtext от
# строки), чтобы была очевидной и стабильной между версиями Postgres.
ADVISORY_LOCK_KEY = 8_140_233_119_450_001


def _try_lock(conn) -> bool:
    """[EN] Session-scoped advisory lock. Released when this connection closes,
    including on a crash — that is the whole point of using it over a flag column.
    [RU] Advisory lock на уровне сессии. Освобождается при закрытии соединения, в
    том числе при падении — в этом и весь смысл по сравнению с колонкой-флагом."""
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s);", (ADVISORY_LOCK_KEY,))
        return bool(cur.fetchone()[0])


def _resolve_filters(settings) -> tuple[frozenset[str], frozenset[str], list[str]]:
    """[EN] Turns saved county/type NAMES into the sets the parser matches on, and
    collects any that no longer resolve so they can be logged instead of silently
    narrowing the import.
    [RU] Превращает сохранённые НАЗВАНИЯ округов/типов в множества, по которым
    фильтрует парсер, и собирает те, что больше не разрешаются, чтобы их можно было
    записать в лог, а не молча сузить импорт."""
    counties = list(settings["counties"] or [])
    types = list(settings["license_types"] or [])

    warnings = []
    for name in unknown_counties(counties):
        warnings.append(f"Ignoring unknown county {name!r} — no city list for it "
                        f"in app/import_catalog.py.")
    for name in unknown_license_types(types):
        warnings.append(f"License type {name!r} is not in the catalogue; it will "
                        f"match only if the registry contains it verbatim.")

    return cities_for(counties), frozenset(types), warnings


def is_due(settings, last_run) -> tuple[bool, str]:
    """[EN] Decides whether the schedule says to run now. Returns (due, reason) so
    the caller can log why nothing happened.

    The rule: run when the local wall-clock time in the configured timezone has
    passed today's scheduled time, and no scheduled run has been started since
    that moment. Comparing against the scheduled MOMENT (not "was there a run
    today") means a timer that was down over the slot still catches up on its next
    poll, and a slot is never run twice.

    Wall-clock in a named timezone, not UTC, so a 09:00 schedule stays 09:00 local
    across the DST switch.

    [RU] Решает, велит ли расписание запускаться сейчас. Возвращает (due, reason),
    чтобы вызывающий мог записать, почему ничего не произошло.

    Правило: запускать, когда локальное время в настроенном часовом поясе прошло
    сегодняшнее запланированное время, и с этого момента ни один запуск по
    расписанию ещё не начинался. Сравнение с запланированным МОМЕНТОМ (а не "был ли
    запуск сегодня") означает, что таймер, лежавший во время слота, всё равно
    догонит на следующем опросе, и слот никогда не выполнится дважды."""
    if not settings["schedule_enabled"]:
        return False, "Schedule is disabled."

    tz_name = settings["timezone"] or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        return False, f"Unknown timezone {tz_name!r} in settings — refusing to guess."

    now_local = datetime.now(tz)
    at = settings["schedule_time"]
    slot = now_local.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)

    if now_local < slot:
        return False, (f"Next run at {slot:%Y-%m-%d %H:%M} {tz_name} "
                       f"(now {now_local:%H:%M}).")

    # [EN] Past today's slot. Has a scheduled run already started for it?
    # [RU] Сегодняшний слот уже прошёл. Начинался ли для него запуск по расписанию?
    if last_run and last_run["started_at"].astimezone(tz) >= slot:
        nxt = slot + timedelta(days=1)
        return False, (f"Already ran for the {slot:%H:%M} slot; "
                       f"next at {nxt:%Y-%m-%d %H:%M} {tz_name}.")

    return True, f"Due for the {slot:%Y-%m-%d %H:%M} {tz_name} slot."


def run_once(trigger: str, started_by: str | None = None,
             run_id: int | None = None) -> int:
    """[EN] Performs the import. Returns a process exit code: 0 success, 1 failure,
    2 skipped because another import holds the lock.

    Every outcome is written to import_runs — a failure that is not recorded is a
    failure nobody sees on the history page, which is the whole point of that page.

    [RU] Выполняет импорт. Возвращает код выхода процесса: 0 — успех, 1 — ошибка,
    2 — пропущено, потому что другой импорт держит блокировку.

    Любой исход пишется в import_runs — незаписанная ошибка это ошибка, которой
    никто не увидит на странице истории, а ведь ради этого страница и существует."""
    with db.connection() as conn:
        settings = imports_model.get_settings(conn)
        cities, types, warnings = _resolve_filters(settings)

        # [EN] Close out rows left 'running' by a process that died, so the history
        # does not show phantom active imports.
        # [RU] Закрываем строки, оставшиеся в 'running' от умершего процесса, чтобы
        # история не показывала фантомные активные импорты.
        imports_model.mark_stale_runs_failed(conn)

        if not _try_lock(conn):
            print("Another import is already running — nothing to do.", file=sys.stderr)
            if run_id is not None:
                imports_model.finish_run(
                    conn, run_id, "failed",
                    error="Another import was already running, so this one was skipped.",
                )
            return 2

        if run_id is None:
            run_id = imports_model.create_run(
                conn, trigger, started_by,
                list(settings["counties"] or []), list(settings["license_types"] or []),
            )

        def log(message: str) -> None:
            print(message, flush=True)
            imports_model.append_log(conn, run_id, message)

        try:
            for warning in warnings:
                log(f"WARNING: {warning}")

            if not cities or not types:
                raise ValueError(
                    "Nothing to import: the filters select no counties or no license "
                    "types. Choose at least one of each on the import settings page."
                )

            log(f"Starting import (trigger: {trigger}).")
            log(f"Counties: {', '.join(settings['counties'] or []) or 'none'}")
            log(f"License types: {', '.join(settings['license_types'] or []) or 'none'}")

            csv_path = parser.download(progress=log)

            counts: dict = {}
            rows = parser.filter_and_transform(csv_path, cities, types,
                                               progress=log, counts=counts)
            staged = parser.write_staging_csv(rows)
            log(f"Prepared {staged:,} rows for loading.")

            before, after = parser.load_into_postgres()
            inserted = after - before
            log(f"Loaded. New rows added: {inserted:,} "
                f"(licenses: {before:,} -> {after:,}).")

            imports_model.finish_run(
                conn, run_id, "success",
                rows_scanned=counts.get("scanned"),
                rows_matched=counts.get("matched"),
                rows_inserted=inserted,
            )
            return 0

        except Exception as exc:
            # [EN] Full traceback into the log for diagnosis, one-line summary into
            # `error` for the history table.
            # [RU] Полный traceback в лог для разбора, однострочная сводка в `error`
            # для таблицы истории.
            detail = traceback.format_exc()
            print(detail, file=sys.stderr)
            try:
                imports_model.append_log(conn, run_id, detail)
            finally:
                imports_model.finish_run(
                    conn, run_id, "failed",
                    error=f"{type(exc).__name__}: {exc}"[:1000],
                )
            return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Run one license import.")
    ap.add_argument("--trigger", choices=("manual", "scheduled"), default="manual")
    ap.add_argument("--started-by", default=None,
                    help="email of the user who pressed the button, for the history")
    ap.add_argument("--run-id", type=int, default=None,
                    help="adopt an existing import_runs row (the web app creates it)")
    ap.add_argument("--if-due", action="store_true",
                    help="obey the schedule in import_settings and exit 0 if not due")
    args = ap.parse_args()

    if args.if_due:
        with db.connection() as conn:
            # [EN] Record the poll BEFORE deciding, and regardless of the decision:
            # this is what proves to the app that a scheduler is alive. A poll that
            # says "not due" is still evidence, and is the common case.
            # [RU] Фиксируем опрос ДО решения и независимо от него: именно это
            # доказывает приложению, что планировщик жив. Опрос с вердиктом "не
            # пора" — тоже свидетельство, и это обычный случай.
            imports_model.record_poll(conn)
            settings = imports_model.get_settings(conn)
            last = imports_model.last_scheduled_start(conn)
        due, reason = is_due(settings, last)
        print(reason)
        if not due:
            return 0

    return run_once(args.trigger, args.started_by, args.run_id)


if __name__ == "__main__":
    raise SystemExit(main())
