"""
[EN]
Checks app/import_catalog.LICENSE_CATEGORIES against the registry itself.

The catalogue maps the DFS form's category labels onto the `License TYCL Desc`
values the CSV contains. That mapping is hand-written, and the registry changes:
Florida can add a licence class at any time. A value that exists in the file but
is in no category is invisible to the tool — nobody could ever import it, and
nothing would say so. This script is how that gets noticed.

It reports, in both directions:
  - descriptions in the file that no category covers  (blind spots)
  - descriptions in the catalogue that the file lacks (stale entries or typos)
  - how many rows each category would match, so a mapping mistake shows up as a
    count that looks wrong

Uses the already-downloaded CSV if present, so it costs nothing after an import.
Pass --download to fetch a fresh copy first.

Run from the repo root:
    python3 -m scripts.audit_license_types

[RU]
Проверяет app/import_catalog.LICENSE_CATEGORIES по самому реестру.

Каталог сопоставляет названия категорий с формы DFS со значениями
`License TYCL Desc`, которые есть в CSV. Это соответствие написано вручную, а
реестр меняется: Флорида может добавить класс лицензии в любой момент. Значение,
которое есть в файле, но не попало ни в одну категорию, невидимо для инструмента —
его никто не смог бы импортировать, и никто бы об этом не сообщил. Этот скрипт
нужен, чтобы это заметить.

Отчёт в обе стороны:
  - описания из файла, не покрытые ни одной категорией  (слепые зоны)
  - описания из каталога, которых нет в файле (устаревшие записи или опечатки)
  - сколько строк совпало бы по каждой категории, чтобы ошибка в соответствии
    проявилась как неправдоподобное число

Использует уже скачанный CSV, если он есть, поэтому после импорта ничего не стоит.
С флагом --download сначала скачивает свежую копию.

Запуск из корня репозитория:
    python3 -m scripts.audit_license_types
"""

import argparse
import collections
import csv
import sys

from app.import_catalog import (
    LICENSE_CATEGORIES,
    TARGET_STATE,
    UNAVAILABLE_LICENSE_TYPES,
)
from scripts import parser


def audit(csv_path, fl_only: bool) -> int:
    seen = collections.Counter()
    with csv_path.open(newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            if fl_only and parser.clean(row.get("Mailing State")).upper() != TARGET_STATE:
                continue
            seen[parser.clean(row.get("License TYCL Desc")).upper()] += 1
    seen.pop("", None)

    mapped = {d: name for name, descs in LICENSE_CATEGORIES.items() for d in descs}

    print(f"Distinct License TYCL Desc values in the file: {len(seen)}")
    print(f"Values mapped by the catalogue:                {len(mapped)}")
    print()

    print("Rows per category:")
    for name, descs in LICENSE_CATEGORIES.items():
        total = sum(seen.get(d, 0) for d in descs)
        note = ""
        if name in UNAVAILABLE_LICENSE_TYPES:
            note = "  (no individual-licence class — expected)"
        elif total == 0:
            note = "  <-- mapped but matched NOTHING"
        print(f"  {total:>9,}  {name}{note}")

    unmapped = sorted(d for d in seen if d not in mapped)
    print()
    if unmapped:
        print(f"BLIND SPOTS — in the file, in no category ({len(unmapped)}):")
        for d in unmapped:
            print(f"  {seen[d]:>9,}  {d}")
        print()
        print("  Add each to a category in app/import_catalog.py, or the tool can")
        print("  never import these licensees and will not say why.")
    else:
        print("No blind spots: every value in the file belongs to a category.")

    phantom = sorted(d for d in mapped if d not in seen)
    print()
    if phantom:
        print(f"STALE — in the catalogue, absent from the file ({len(phantom)}):")
        for d in phantom:
            print(f"  {d}   (listed under {mapped[d]})")
        print()
        print("  Harmless for matching, but usually a typo. Check the spelling.")
    else:
        print("No stale entries: every catalogue value appears in the file.")

    # [EN] Blind spots are the failure that silently loses data, so only they fail
    # the run; a stale entry cannot hide a licensee from the import.
    # [RU] Слепые зоны — та ошибка, которая молча теряет данные, поэтому только они
    # заваливают запуск; устаревшая запись не может спрятать лицензиата от импорта.
    return 1 if unmapped else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    ap.add_argument("--download", action="store_true",
                    help="fetch a fresh registry first (~330MB)")
    ap.add_argument("--all-states", action="store_true",
                    help="audit every row, not just Florida mailing addresses")
    args = ap.parse_args()

    path = parser.RAW_CSV
    if args.download or not path.exists():
        if not args.download:
            print(f"{path} not found — downloading a fresh copy.", file=sys.stderr)
        path = parser.download()

    return audit(path, fl_only=not args.all_states)


if __name__ == "__main__":
    raise SystemExit(main())
