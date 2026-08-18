"""
[EN]
The catalogue of things an import can be filtered by: counties (each with the
city spellings that identify it) and license types.

This lives in app/ rather than in scripts/parser.py because BOTH sides need it:
the web app renders a checkbox per entry, and the ETL expands the selected
counties into the city set it matches on. scripts/ may import app/, never the
other way round (AGENTS.md §2), so app/ is the only place both can reach.

Pure data — no Flask, no SQL, no request state. The database stores only which
NAMES are selected; the expansion to cities happens here. A misspelled county in
the database therefore cannot silently match zero rows: it will not resolve at
all, and the caller reports it.

Adding a county: add an entry to COUNTIES with its municipalities (plus the
common abbreviations the registry actually contains, e.g. "FT LAUDERDALE"). It
then appears in the UI automatically, with no migration.

[RU]
Каталог того, по чему можно фильтровать импорт: округа (каждый со написаниями
городов, которые его определяют) и типы лицензий.

Живёт в app/, а не в scripts/parser.py, потому что нужен ОБЕИМ сторонам:
веб-приложение рисует по чекбоксу на запись, а ETL разворачивает выбранные округа
в множество городов, по которому фильтрует. scripts/ может импортировать app/, но
никогда наоборот (AGENTS.md §2), поэтому app/ — единственное место, доступное обоим.

Чистые данные — без Flask, без SQL, без состояния запроса. В базе хранятся только
выбранные НАЗВАНИЯ; разворот в города происходит здесь. Поэтому округ с опечаткой
в базе не может молча дать ноль совпадений: он вообще не разрешится, и вызывающий
об этом сообщит.

Добавление округа: добавьте запись в COUNTIES с его муниципалитетами (плюс
распространённые сокращения, которые реально встречаются в реестре, например
"FT LAUDERDALE"). После этого он появляется в интерфейсе автоматически, без миграции.
"""

# [EN] Official municipalities + the spellings the FL DFS registry actually uses.
# City names are compared uppercased, so these must stay uppercase.
# [RU] Официальные муниципалитеты + написания, реально используемые в реестре FL DFS.
# Названия городов сравниваются в верхнем регистре, поэтому здесь тоже верхний.
COUNTIES: dict[str, frozenset[str]] = {
    "Broward": frozenset({
        "COCONUT CREEK", "COOPER CITY", "CORAL SPRINGS", "DANIA BEACH", "DAVIE",
        "DEERFIELD BEACH", "FORT LAUDERDALE", "FT LAUDERDALE", "FT. LAUDERDALE",
        "HALLANDALE BEACH", "HALLANDALE", "HILLSBORO BEACH", "HOLLYWOOD",
        "LAUDERDALE BY THE SEA", "LAUDERDALE-BY-THE-SEA", "LAUDERDALE LAKES",
        "LAUDERHILL", "LAZY LAKE", "LIGHTHOUSE POINT", "MARGATE", "MIRAMAR",
        "NORTH LAUDERDALE", "OAKLAND PARK", "PARKLAND", "PEMBROKE PARK",
        "PEMBROKE PINES", "PLANTATION", "POMPANO BEACH", "SEA RANCH LAKES",
        "SOUTHWEST RANCHES", "SUNRISE", "TAMARAC", "WEST PARK", "WESTON",
        "WILTON MANORS",
    }),
    "Miami-Dade": frozenset({
        "AVENTURA", "BAL HARBOUR", "BAY HARBOR ISLANDS", "BISCAYNE PARK",
        "CORAL GABLES", "CUTLER BAY", "DORAL", "EL PORTAL", "FLORIDA CITY",
        "GOLDEN BEACH", "HIALEAH", "HIALEAH GARDENS", "HOMESTEAD",
        "INDIAN CREEK", "ISLANDIA", "KEY BISCAYNE", "MEDLEY", "MIAMI",
        "MIAMI BEACH", "MIAMI GARDENS", "MIAMI LAKES", "MIAMI SHORES",
        "MIAMI SPRINGS", "NORTH BAY VILLAGE", "NORTH MIAMI",
        "NORTH MIAMI BEACH", "OPA LOCKA", "OPA-LOCKA", "PALMETTO BAY",
        "PINECREST", "SOUTH MIAMI", "SUNNY ISLES BEACH", "SURFSIDE",
        "SWEETWATER", "VIRGINIA GARDENS", "WEST MIAMI",
    }),
    "Palm Beach": frozenset({
        "ATLANTIS", "BELLE GLADE", "BOCA RATON", "BOYNTON BEACH", "BRINY BREEZES",
        "CANAL POINT", "CLOUD LAKE", "DELRAY BEACH", "GLEN RIDGE", "GREENACRES",
        "GULF STREAM", "HAVERHILL", "HIGHLAND BEACH", "HYPOLUXO", "JUNO BEACH",
        "JUPITER", "JUPITER INLET COLONY", "LAKE CLARKE SHORES", "LAKE PARK",
        "LAKE WORTH", "LAKE WORTH BEACH", "LANTANA", "LOXAHATCHEE",
        "LOXAHATCHEE GROVES", "MANALAPAN", "MANGONIA PARK", "NORTH PALM BEACH",
        "OCEAN RIDGE", "PAHOKEE", "PALM BEACH", "PALM BEACH GARDENS",
        "PALM BEACH SHORES", "PALM SPRINGS", "RIVIERA BEACH", "ROYAL PALM BEACH",
        "SOUTH BAY", "SOUTH PALM BEACH", "TEQUESTA", "WELLINGTON",
        "WEST PALM BEACH",
    }),
}

# [EN] License TYCL Desc values. The first four are what the tool has always
# imported; the health-only ones are offered because they exist in the registry
# and are the obvious next widening. Selecting a value that the registry never
# contains simply matches nothing — harmless, but that is why this is a fixed
# list rather than a free-text field.
# [RU] Значения License TYCL Desc. Первые четыре — то, что инструмент импортировал
# всегда; варианты только по health предложены потому, что они есть в реестре и
# являются очевидным следующим расширением. Выбор значения, которого в реестре нет,
# просто не даст совпадений — безвредно, но именно поэтому это фиксированный
# список, а не поле свободного ввода.
LICENSE_TYPES: tuple[str, ...] = (
    "LIFE",
    "LIFE & HEALTH",
    "LIFE INCL VAR ANNUITY & HEALTH",
    "LIFE INCL VARIABLE ANNUITY",
    "HEALTH",
    "HEALTH & LIFE",
)

# [EN] Every import is scoped to Florida: the source file is the Florida DFS
# registry, so Mailing State is always compared against this. Not configurable —
# there is no other state in the data.
# [RU] Любой импорт ограничен Флоридой: исходный файл — реестр Florida DFS,
# поэтому Mailing State всегда сравнивается с этим значением. Не настраивается —
# другого штата в данных нет.
TARGET_STATE = "FL"


def cities_for(county_names) -> frozenset[str]:
    """[EN] Expands county names into the set of city spellings to match on.
    Unknown names are ignored here; use unknown_counties() to report them rather
    than silently importing a narrower set than the user asked for.
    [RU] Разворачивает названия округов в множество написаний городов для сравнения.
    Неизвестные названия здесь игнорируются; используйте unknown_counties(), чтобы
    сообщить о них, а не молча импортировать более узкий набор, чем просил пользователь."""
    cities: set[str] = set()
    for name in county_names or ():
        cities |= COUNTIES.get(name, frozenset())
    return frozenset(cities)


def unknown_counties(county_names) -> list[str]:
    """[EN] County names with no entry in COUNTIES — a stored value that no longer
    resolves, e.g. after a rename. Callers surface these instead of ignoring them.
    [RU] Названия округов, которых нет в COUNTIES — сохранённое значение, которое
    больше не разрешается, например после переименования. Вызывающие показывают их,
    а не игнорируют."""
    return sorted(n for n in (county_names or ()) if n not in COUNTIES)


def unknown_license_types(types) -> list[str]:
    """[EN] Selected license types that are not in the catalogue.
    [RU] Выбранные типы лицензий, отсутствующие в каталоге."""
    known = set(LICENSE_TYPES)
    return sorted(t for t in (types or ()) if t not in known)
