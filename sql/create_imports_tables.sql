-- [EN] Import configuration and run history.
--
-- `import_settings` is a SINGLETON row (CHECK id = 1): there is one set of
-- filters and one schedule for the whole tool, so a table with one row is
-- simpler than a key/value store and keeps the types real (TEXT[], TIME, BOOLEAN)
-- instead of everything being a string.
--
-- The seeded values reproduce exactly what scripts/parser.py used to hardcode, so
-- applying this file changes no behaviour until someone edits the settings in the UI.
--
-- Apply to an existing database (compose initdb only runs on a fresh volume):
--     psql -h localhost -p 5434 -U postgres -d Agents_Heresure -f sql/create_imports_tables.sql
--
-- [RU] Настройки импорта и история запусков.
--
-- `import_settings` — строка-СИНГЛТОН (CHECK id = 1): на весь инструмент один
-- набор фильтров и одно расписание, поэтому таблица с одной строкой проще, чем
-- хранилище ключ/значение, и сохраняет настоящие типы (TEXT[], TIME, BOOLEAN)
-- вместо того, чтобы всё было строкой.
--
-- Засеянные значения в точности повторяют то, что раньше было захардкожено в
-- scripts/parser.py, поэтому применение файла ничего не меняет в поведении, пока
-- кто-нибудь не отредактирует настройки в интерфейсе.
--
-- Применить к существующей базе (initdb в compose срабатывает только на пустом томе):
--     psql -h localhost -p 5434 -U postgres -d Agents_Heresure -f sql/create_imports_tables.sql

CREATE TABLE IF NOT EXISTS import_settings (
    id                SMALLINT    PRIMARY KEY DEFAULT 1,
    -- [EN] County NAMES, not city lists. The name -> cities mapping lives in
    -- app/import_catalog.py, so a typo here cannot silently match nothing.
    -- [RU] НАЗВАНИЯ округов, а не списки городов. Соответствие название -> города
    -- живёт в app/import_catalog.py, поэтому опечатка здесь не приведёт молча к
    -- нулю совпадений.
    counties          TEXT[]      NOT NULL DEFAULT '{}',
    license_types     TEXT[]      NOT NULL DEFAULT '{}',
    schedule_enabled  BOOLEAN     NOT NULL DEFAULT FALSE,
    -- [EN] Local wall-clock time in schedule_timezone, NOT UTC — "run at 09:00 in
    -- New York" must survive the DST switch, which a stored UTC offset would not.
    -- [RU] Локальное время в schedule_timezone, а НЕ UTC — "запуск в 09:00 по
    -- Нью-Йорку" должен переживать переход на летнее время, чего сохранённое
    -- смещение UTC не обеспечивает.
    schedule_time     TIME        NOT NULL DEFAULT '09:00',
    schedule_timezone TEXT        NOT NULL DEFAULT 'America/New_York',
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by        TEXT,
    CONSTRAINT import_settings_singleton CHECK (id = 1)
);

-- [EN] Seed the one row with the previously hardcoded filters. ON CONFLICT so
-- re-running this file never clobbers settings someone has since edited.
-- [RU] Засеваем единственную строку ранее захардкоженными фильтрами. ON CONFLICT,
-- чтобы повторный запуск файла никогда не перетирал уже изменённые настройки.
INSERT INTO import_settings (id, counties, license_types, schedule_enabled)
VALUES (
    1,
    ARRAY['Broward', 'Miami-Dade'],
    ARRAY['LIFE', 'LIFE & HEALTH', 'LIFE INCL VAR ANNUITY & HEALTH',
          'LIFE INCL VARIABLE ANNUITY'],
    FALSE
)
ON CONFLICT (id) DO NOTHING;

-- [EN] When a scheduler last asked "is an import due?". Written by
-- `run_import --if-due` on every poll, whatever it decides. A schedule is only
-- honoured if SOMETHING polls (systemd on the server, the `scheduler` service in
-- compose), and nothing in the app can make that happen by itself — so the app
-- records evidence that a poller exists and warns when it does not. Without this
-- an enabled schedule that nobody polls looks identical to a working one.
--
-- Added after the fact, so ALTER for databases created before it existed.
--
-- [RU] Когда планировщик в последний раз спрашивал "пора ли импортировать?".
-- Пишется `run_import --if-due` при каждом опросе, независимо от решения.
-- Расписание соблюдается, только если КТО-ТО опрашивает (systemd на сервере,
-- сервис `scheduler` в compose), и приложение само это обеспечить не может —
-- поэтому оно фиксирует свидетельство наличия опросчика и предупреждает, когда
-- его нет. Без этого включённое расписание, которое никто не опрашивает,
-- выглядит точно так же, как работающее.
--
-- Добавлено позже, поэтому ALTER для баз, созданных до его появления.
ALTER TABLE import_settings ADD COLUMN IF NOT EXISTS last_poll_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS import_runs (
    id            BIGSERIAL   PRIMARY KEY,
    status        TEXT        NOT NULL DEFAULT 'running',
    -- [EN] 'manual' (someone pressed the button) or 'scheduled' (the timer).
    -- [RU] 'manual' (кто-то нажал кнопку) или 'scheduled' (таймер).
    trigger       TEXT        NOT NULL,
    started_by    TEXT,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at   TIMESTAMPTZ,
    -- [EN] Bumped by the runner as it works. A 'running' row whose heartbeat has
    -- gone quiet is a crashed run, not an active one — that distinction is what
    -- stops one killed process from blocking every future import.
    -- [RU] Обновляется исполнителем по ходу работы. Строка 'running' с замолчавшим
    -- heartbeat — это упавший запуск, а не активный; именно это различие не даёт
    -- одному убитому процессу заблокировать все будущие импорты.
    heartbeat_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    rows_scanned  BIGINT,
    rows_matched  BIGINT,
    rows_inserted BIGINT,
    -- [EN] Snapshot of the filters actually used, so history stays truthful after
    -- someone changes the settings.
    -- [RU] Снимок фактически использованных фильтров, чтобы история оставалась
    -- правдивой после изменения настроек.
    counties      TEXT[],
    license_types TEXT[],
    log           TEXT        NOT NULL DEFAULT '',
    error         TEXT,
    CONSTRAINT import_runs_status_check CHECK (status IN ('running', 'success', 'failed'))
);

-- [EN] The history page reads newest-first; the runner asks "is one active?".
-- [RU] Страница истории читает от новых к старым; исполнитель спрашивает "есть
-- ли активный?".
CREATE INDEX IF NOT EXISTS import_runs_started_at_idx ON import_runs (started_at DESC);
CREATE INDEX IF NOT EXISTS import_runs_running_idx
    ON import_runs (heartbeat_at DESC) WHERE status = 'running';
