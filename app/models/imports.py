"""
[EN]
Data access for `import_settings` and `import_runs` — every SQL statement about
import configuration and run history, mirroring app/models/license.py.

Read by both the web app and scripts/run_import.py. The runner is the only writer
of run progress; the web app only reads it, plus creates the initial row.

[RU]
Доступ к данным `import_settings` и `import_runs` — все SQL-запросы про настройки
импорта и историю запусков, по аналогии с app/models/license.py.

Читается и веб-приложением, и scripts/run_import.py. Прогресс запуска пишет только
исполнитель; веб-приложение только читает его и создаёт начальную строку.
"""

import psycopg2.extras

# [EN] A 'running' row whose heartbeat is older than this is treated as crashed,
# not active — otherwise one killed process would block imports forever. Must be
# comfortably longer than the gap between heartbeats in scripts/run_import.py.
# [RU] Строка 'running' с heartbeat старше этого считается упавшей, а не активной —
# иначе один убитый процесс заблокировал бы импорты навсегда. Должно быть заметно
# больше интервала между heartbeat в scripts/run_import.py.
STALE_AFTER = "5 minutes"


def _dict_cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


# --------------------------------------------------------------------------
# [EN] Settings (the singleton row) / [RU] Настройки (строка-синглтон)
# --------------------------------------------------------------------------

def get_settings(conn) -> dict:
    """[EN] The one settings row. Created by sql/create_imports_tables.sql; if it
    is somehow missing this inserts the defaults rather than returning None, so no
    caller has to handle a half-initialised database.
    [RU] Единственная строка настроек. Создаётся sql/create_imports_tables.sql;
    если её почему-то нет, вставляются значения по умолчанию, а не возвращается
    None, чтобы вызывающим не приходилось обрабатывать полуинициализированную базу."""
    with _dict_cursor(conn) as cur:
        cur.execute("SELECT * FROM import_settings WHERE id = 1;")
        row = cur.fetchone()
        if row:
            return row

        cur.execute(
            """
            INSERT INTO import_settings (id) VALUES (1)
            ON CONFLICT (id) DO NOTHING
            RETURNING *;
            """
        )
        row = cur.fetchone()
        conn.commit()
        if row:
            return row
        cur.execute("SELECT * FROM import_settings WHERE id = 1;")
        return cur.fetchone()


def save_filters(conn, counties: list[str], license_types: list[str], updated_by: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE import_settings
            SET counties = %s, license_types = %s,
                updated_at = now(), updated_by = %s
            WHERE id = 1;
            """,
            (counties, license_types, updated_by),
        )
        conn.commit()


def save_schedule(conn, enabled: bool, at_time: str, timezone: str, updated_by: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE import_settings
            SET schedule_enabled = %s, schedule_time = %s, schedule_timezone = %s,
                updated_at = now(), updated_by = %s
            WHERE id = 1;
            """,
            (enabled, at_time, timezone, updated_by),
        )
        conn.commit()


# --------------------------------------------------------------------------
# [EN] Runs / [RU] Запуски
# --------------------------------------------------------------------------

def active_run(conn) -> dict | None:
    """[EN] The currently-running import, or None. Excludes stale rows (see
    STALE_AFTER) so a crashed run does not look active forever.
    [RU] Текущий выполняющийся импорт или None. Исключает устаревшие строки
    (см. STALE_AFTER), чтобы упавший запуск не выглядел активным вечно."""
    with _dict_cursor(conn) as cur:
        cur.execute(
            f"""
            SELECT * FROM import_runs
            WHERE status = 'running'
              AND heartbeat_at > now() - INTERVAL '{STALE_AFTER}'
            ORDER BY started_at DESC
            LIMIT 1;
            """
        )
        return cur.fetchone()


def create_run(conn, trigger: str, started_by: str | None,
               counties: list[str], license_types: list[str]) -> int:
    """[EN] Records the run BEFORE the work starts, so the history page shows it
    immediately and the id can be handed to the runner subprocess.
    [RU] Записывает запуск ДО начала работы, чтобы страница истории показала его
    сразу, а id можно было передать процессу-исполнителю."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO import_runs (trigger, started_by, counties, license_types)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
            """,
            (trigger, started_by, counties, license_types),
        )
        run_id = cur.fetchone()[0]
        conn.commit()
        return run_id


def append_log(conn, run_id: int, message: str) -> None:
    """[EN] Appends one progress line and bumps the heartbeat in the same
    statement — every sign of life the runner gives goes through here, so the two
    can never drift apart.
    [RU] Добавляет одну строку прогресса и обновляет heartbeat одним запросом —
    любой признак жизни исполнителя идёт через эту функцию, поэтому они не могут
    разойтись."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE import_runs
            SET log = log || %s, heartbeat_at = now()
            WHERE id = %s;
            """,
            (message.rstrip("\n") + "\n", run_id),
        )
        conn.commit()


def heartbeat(conn, run_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE import_runs SET heartbeat_at = now() WHERE id = %s;", (run_id,))
        conn.commit()


def finish_run(conn, run_id: int, status: str, rows_scanned: int | None = None,
               rows_matched: int | None = None, rows_inserted: int | None = None,
               error: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE import_runs
            SET status = %s, finished_at = now(), heartbeat_at = now(),
                rows_scanned = %s, rows_matched = %s, rows_inserted = %s, error = %s
            WHERE id = %s;
            """,
            (status, rows_scanned, rows_matched, rows_inserted, error, run_id),
        )
        conn.commit()


def recent_runs(conn, limit: int = 50) -> list[dict]:
    """[EN] Newest first, with two derived columns the page needs: duration, and
    whether a 'running' row has actually gone stale. Computing `is_stale` in SQL
    keeps it consistent with active_run(), which uses the same interval.
    [RU] От новых к старым, с двумя вычисленными колонками для страницы:
    длительность и признак того, что строка 'running' на самом деле зависла.
    Вычисление `is_stale` в SQL держит его согласованным с active_run(), где
    используется тот же интервал."""
    with _dict_cursor(conn) as cur:
        cur.execute(
            f"""
            SELECT *,
                   COALESCE(finished_at, now()) - started_at AS duration,
                   (status = 'running'
                    AND heartbeat_at <= now() - INTERVAL '{STALE_AFTER}') AS is_stale
            FROM import_runs
            ORDER BY started_at DESC
            LIMIT %s;
            """,
            (limit,),
        )
        return cur.fetchall()


def get_run(conn, run_id: int) -> dict | None:
    with _dict_cursor(conn) as cur:
        cur.execute("SELECT * FROM import_runs WHERE id = %s;", (run_id,))
        return cur.fetchone()


def last_scheduled_start(conn) -> dict | None:
    """[EN] The most recent scheduled run of any outcome. `--if-due` uses this to
    avoid starting a second run for the same slot: what matters is that an attempt
    was made, not whether it succeeded, otherwise a failing import would retry
    every time the timer fires.
    [RU] Последний запуск по расписанию с любым исходом. `--if-due` использует это,
    чтобы не запустить второй раз для того же слота: важен сам факт попытки, а не
    её успех, иначе падающий импорт повторялся бы при каждом срабатывании таймера."""
    with _dict_cursor(conn) as cur:
        cur.execute(
            """
            SELECT * FROM import_runs
            WHERE trigger = 'scheduled'
            ORDER BY started_at DESC
            LIMIT 1;
            """
        )
        return cur.fetchone()


def mark_stale_runs_failed(conn) -> int:
    """[EN] Closes out 'running' rows whose process died without reporting. Called
    when a new run starts, so history does not accumulate rows stuck at 'running'.
    [RU] Закрывает строки 'running', чей процесс умер, не отчитавшись. Вызывается
    при старте нового запуска, чтобы в истории не копились строки, застрявшие в
    состоянии 'running'."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE import_runs
            SET status = 'failed', finished_at = COALESCE(finished_at, heartbeat_at),
                error = COALESCE(error, 'Interrupted — the import process stopped '
                                        'without reporting (server restart or kill).')
            WHERE status = 'running'
              AND heartbeat_at <= now() - INTERVAL '{STALE_AFTER}';
            """
        )
        closed = cur.rowcount
        conn.commit()
        return closed
