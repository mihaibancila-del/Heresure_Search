"""
[EN]
Downloads the Florida DFS license registry, filters agents by these
conditions:
  - Mailing State == FL
  - Mailing City is in one of the selected counties
  - License TYCL Desc is one of the selected license types
and writes the needed fields straight into Postgres (database
Agents_Heresure, table licenses).

The counties and license types are NOT hardcoded here any more: they are read
from import_settings and passed in as arguments (see scripts/run_import.py, which
is what the UI button and the systemd timer both call). Running this module
directly still works and uses whatever is currently saved in the settings.

Field transformation rules when writing to the DB:
  - Full Name        = First Name + Middle Name + Last Name (space-separated, no commas/periods)
  - License Type       = License TYCL Desc
  - Mailing Address    = Mailing Address + Mailing Address2 + Mailing City + Mailing State + Mailing Zip
                          (space-separated, empty parts skipped)
  - Business Email     = Email Address
  - Personal Email     = empty (left blank)
  - checked             = always False

Only NEW agents are inserted into licenses (compared by the Full Name +
Business Email pair) — existing rows are not touched, so manually-set
checked / Personal Email values are not overwritten.

[RU]
Скачивает реестр лицензий Florida DFS, фильтрует агентов по условиям:
  - Mailing State == FL
  - Mailing City входит в один из выбранных округов
  - License TYCL Desc входит в один из выбранных типов лицензий
и сразу записывает нужные поля в Postgres (база Agents_Heresure, таблица licenses).

Округа и типы лицензий здесь больше НЕ захардкожены: они читаются из
import_settings и передаются аргументами (см. scripts/run_import.py — именно его
вызывают и кнопка в интерфейсе, и таймер systemd). Прямой запуск модуля
по-прежнему работает и использует то, что сейчас сохранено в настройках.

Правила преобразования полей при записи в БД:
  - Full Name        = First Name + Middle Name + Last Name (через пробел, без запятых/точек)
  - License Type       = License TYCL Desc
  - Mailing Address    = Mailing Address + Mailing Address2 + Mailing City + Mailing State + Mailing Zip
                          (через пробел, пустые части пропускаются)
  - Business Email     = Email Address
  - Personal Email     = пусто (не заполняем)
  - checked             = всегда False

В licenses попадают только НОВЫЕ агенты (сравнение по паре Full Name +
Business Email) — уже существующие записи не трогаются, чтобы не затереть
вручную выставленные checked / Personal Email.
"""

import csv
import os
import re
import subprocess
from pathlib import Path

import requests

from app.config import PG_BIN, PG_DB, PG_HOST, PG_PORT, PG_USER, PROJECT_ROOT, pg_password
from app.import_catalog import TARGET_STATE

URL = "https://www.myfloridacfo.com/downloads/AAS/LicenseeSearch/AllValidLicensesIndividual.csv"

# [EN] Anchored to the project root, not the current directory — the script has
# to work the same under systemd (WorkingDirectory=/opt/agent_licence) and from
# a shell in any folder.
# [RU] Привязано к корню проекта, а не к текущему каталогу — скрипт должен
# работать одинаково и под systemd (WorkingDirectory=/opt/agent_licence), и из
# шелла в любой папке.
RAW_CSV = PROJECT_ROOT / "AllValidLicensesIndividual.csv"
STAGING_CSV = PROJECT_ROOT / "staging_licenses.csv"
LOAD_SQL = PROJECT_ROOT / "sql" / "load_script.sql"

headers = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    )
}

# [EN] The city and license-type filters used to be hardcoded here. They now come
# from import_settings in the database, expanded through app/import_catalog.py, so
# they can be changed in the UI (VOC-14) — see scripts/run_import.py, which reads
# the settings and passes them in. The functions below take them as arguments and
# hold no filter state of their own.
# [RU] Фильтры по городам и типам лицензий раньше были захардкожены здесь. Теперь
# они берутся из import_settings в базе и разворачиваются через
# app/import_catalog.py, поэтому их можно менять в интерфейсе (VOC-14) — см.
# scripts/run_import.py, который читает настройки и передаёт их сюда. Функции ниже
# принимают их аргументами и не хранят состояния фильтров.

STAGING_FIELDNAMES = [
    "License Number",
    "Full Name",
    "NPN Number",
    "License Type",
    "Business Email",
    "Business Phone",
    "Mailing Address",
    "Personal Email",
    "checked",
]


def download(dest: Path = RAW_CSV, progress=None) -> Path:
    """[EN] Streams the ~330MB registry to disk. `progress` is an optional
    callable(str) used to report milestones somewhere other than stdout — the web
    UI passes one that writes into import_runs.log. It is called once per 25MB,
    not per chunk, so a long download does not write hundreds of database rows.
    [RU] Стримит реестр (~330MB) на диск. `progress` — необязательный
    callable(str) для отчёта о вехах не в stdout: веб-интерфейс передаёт функцию,
    пишущую в import_runs.log. Вызывается раз на 25MB, а не на каждый чанк, чтобы
    долгая загрузка не наплодила сотни записей в базе."""
    print("Downloading Florida DFS individual License...")

    with requests.get(
        URL,
        headers=headers,
        stream=True,
        timeout=(30, 300),
    ) as response:
        response.raise_for_status()

        total = int(response.headers.get("Content-Length", 0))
        downloaded = 0
        next_report = 25 * 1024 * 1024

        with open(dest, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue

                f.write(chunk)
                downloaded += len(chunk)

                if total:
                    percent = downloaded / total * 100
                    print(
                        f"\r{percent:6.2f}% "
                        f"({downloaded / 1024 / 1024:.1f} / "
                        f"{total / 1024 / 1024:.1f} MB)",
                        end="",
                    )

                if progress and downloaded >= next_report:
                    next_report += 25 * 1024 * 1024
                    mb = downloaded / 1024 / 1024
                    if total:
                        progress(f"Downloading… {mb:.0f} MB of "
                                 f"{total / 1024 / 1024:.0f} MB")
                    else:
                        progress(f"Downloading… {mb:.0f} MB")

    print(f"\nDone: {dest.resolve()}")
    if progress:
        progress(f"Download finished ({downloaded / 1024 / 1024:.0f} MB).")
    return dest


def clean(value) -> str:
    """Strips Excel escaping of the form ="12345" -> 12345.
    Убирает Excel-экранирование вида ="12345" -> 12345."""
    value = (value or "").strip()
    if value.startswith('="') and value.endswith('"'):
        value = value[2:-1]
    return value


def clean_name_part(value: str) -> str:
    """Removes commas/periods from a name part, collapses whitespace.
    Убирает запятые/точки из части имени, схлопывает пробелы."""
    value = re.sub(r"[,.]", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def build_full_name(row: dict) -> str:
    parts = [
        clean_name_part(clean(row.get("First Name"))),
        clean_name_part(clean(row.get("Middle Name"))),
        clean_name_part(clean(row.get("Last Name"))),
    ]
    return " ".join(p for p in parts if p)


def build_mailing_address(row: dict) -> str:
    parts = [
        clean(row.get("Mailing Address")),
        clean(row.get("Mailing Address2")),
        clean(row.get("Mailing City")),
        clean(row.get("Mailing State")),
        clean(row.get("Mailing Zip")),
    ]
    return " ".join(p for p in parts if p)


def filter_and_transform(csv_path: Path, cities, license_types, progress=None,
                         counts: dict | None = None):
    """[EN] Streams the source CSV and yields rows already prepared for DB insert.

    `cities` and `license_types` are the expanded filters (see
    app/import_catalog.cities_for). Both are compared uppercased, so they must
    already be uppercase — the caller gets them from the catalogue, which is.

    `counts`, if given, is a dict this fills in with "scanned" and "matched" as it
    goes. A generator cannot return values to a caller that iterates it, and the
    caller needs those totals for the run history — so they are written into a
    dict the caller owns rather than returned.

    [RU] Стримит исходный CSV и yield-ит уже готовые для записи в БД строки.

    `cities` и `license_types` — уже развёрнутые фильтры (см.
    app/import_catalog.cities_for). Оба сравниваются в верхнем регистре, поэтому
    должны быть в верхнем регистре заранее — вызывающий берёт их из каталога, где
    это уже так.

    `counts`, если передан, — dict, который функция заполняет ключами "scanned" и
    "matched" по ходу работы. Генератор не может вернуть значения тому, кто его
    итерирует, а вызывающему эти итоги нужны для истории запусков — поэтому они
    пишутся в dict, принадлежащий вызывающему, а не возвращаются."""
    total = 0
    matched = 0

    with csv_path.open(newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)

        for row in reader:
            total += 1

            state = clean(row.get("Mailing State")).upper()
            city = clean(row.get("Mailing City")).upper()
            desc = clean(row.get("License TYCL Desc")).upper()

            if state != TARGET_STATE:
                continue
            if city not in cities:
                continue
            if desc not in license_types:
                continue

            matched += 1
            yield {
                "License Number": clean(row.get("License Number")),
                "Full Name": build_full_name(row),
                "NPN Number": clean(row.get("NPN Number")),
                "License Type": desc,
                "Business Email": clean(row.get("Email Address")),
                "Business Phone": clean(row.get("Business Phone")),
                "Mailing Address": build_mailing_address(row),
                "Personal Email": "",
                "checked": "false",
            }

            if total % 200_000 == 0:
                print(f"...processed {total} rows, matched {matched}")
                if progress:
                    progress(f"Filtering… scanned {total:,} rows, matched {matched:,}")
                if counts is not None:
                    counts["scanned"] = total
                    counts["matched"] = matched

    print(f"Filtering done. Total rows: {total}. Matched conditions: {matched}.")
    if counts is not None:
        counts["scanned"] = total
        counts["matched"] = matched
    if progress:
        progress(f"Filtering done. Scanned {total:,} rows, matched {matched:,}.")


def write_staging_csv(rows, dest: Path = STAGING_CSV) -> int:
    count = 0
    with dest.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=STAGING_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def load_into_postgres() -> tuple[int, int]:
    """[EN] Runs sql/load_script.sql via psql and returns (before, after) row counts
    of `licenses`, so the caller can report how many NEW rows the run added. Note
    this needs the psql binary on PATH (or PG_BIN set) — see AGENTS.md.
    [RU] Выполняет sql/load_script.sql через psql и возвращает (before, after) —
    число строк в `licenses` до и после, чтобы вызывающий мог сообщить, сколько НОВЫХ
    строк добавил запуск. Требует psql в PATH (или заданного PG_BIN) — см. AGENTS.md."""
    env = os.environ.copy()
    env["PGPASSWORD"] = pg_password()

    before = subprocess.run(
        [PG_BIN, "-h", PG_HOST, "-p", PG_PORT, "-U", PG_USER, "-d", PG_DB,
         "-t", "-c", "SELECT COUNT(*) FROM licenses;"],
        env=env, capture_output=True, text=True, check=True,
    ).stdout.strip()

    subprocess.run(
        [PG_BIN, "-h", PG_HOST, "-p", PG_PORT, "-U", PG_USER, "-d", PG_DB,
         "-f", str(LOAD_SQL)],
        env=env, check=True,
        # [EN] The \copy in sql/load_script.sql is a CLIENT-side psql
        # meta-command: its path is resolved against psql's own CWD, and psql
        # performs NO variable interpolation inside \copy arguments — so the
        # only way to make it CWD-independent is to pin psql's CWD here.
        # [RU] \copy в sql/load_script.sql — КЛИЕНТСКАЯ meta-команда psql: путь
        # считается от собственного CWD psql, и psql НЕ подставляет переменные
        # внутрь аргументов \copy — поэтому единственный способ избавиться от
        # зависимости от CWD это зафиксировать CWD самого psql здесь.
        cwd=STAGING_CSV.parent,
    )

    after = subprocess.run(
        [PG_BIN, "-h", PG_HOST, "-p", PG_PORT, "-U", PG_USER, "-d", PG_DB,
         "-t", "-c", "SELECT COUNT(*) FROM licenses;"],
        env=env, capture_output=True, text=True, check=True,
    ).stdout.strip()

    print(f"Rows before: {before}, after: {after} "
          f"(new rows added: {int(after) - int(before)}).")
    return int(before), int(after)


def main() -> None:
    """[EN] Standalone run, using whatever filters are currently saved in
    import_settings. Delegates to scripts.run_import so a hand-run import is
    recorded in the history exactly like one started from the UI — there is one
    code path, not two that could drift apart.
    [RU] Автономный запуск с фильтрами, сохранёнными сейчас в import_settings.
    Делегирует в scripts.run_import, чтобы запуск руками попадал в историю точно
    так же, как запущенный из интерфейса — один путь исполнения, а не два, которые
    могут разойтись."""
    from scripts.run_import import run_once

    raise SystemExit(run_once(trigger="manual", started_by="scripts.parser"))


if __name__ == "__main__":
    main()
