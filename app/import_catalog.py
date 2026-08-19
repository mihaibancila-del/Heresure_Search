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

# [EN] License categories, exactly as the Florida DFS licensee-search form offers
# them, mapped to the `License TYCL Desc` values the CSV actually contains.
#
# This indirection is NOT optional. The website's dropdown is a coarse taxonomy —
# "Life & Annuity" — while the export column holds the granular licence class:
# "LIFE INCL VARIABLE ANNUITY", "NONRES LIFE & VARIABLE ANNUITY", and eight more.
# Filtering on the category label directly would match nothing at all, silently, and
# every import would report zero rows. Same shape as COUNTIES above: the database
# stores the label, the expansion to matchable values happens here.
#
# Values were taken from the registry itself (77 distinct code/description pairs);
# `python3 -m scripts.audit_license_types` re-checks the mapping against a freshly
# downloaded file and reports anything new or unmapped.
#
# Three categories exist on the DFS form but have no individual-licence class, so
# they map to nothing: agencies and adjusting firms are entities and live in a
# different export, and Debit Agent has no current TYCL. They are kept in the list
# so it matches the form you are used to, and the UI marks them unavailable rather
# than offering a checkbox that can never match.
#
# [RU] Категории лицензий — в точности как их предлагает форма поиска Florida DFS —
# сопоставленные со значениями `License TYCL Desc`, которые реально есть в CSV.
#
# Эта прослойка НЕ опциональна. Выпадающий список на сайте — грубая классификация
# ("Life & Annuity"), тогда как в колонке экспорта лежит конкретный класс лицензии:
# "LIFE INCL VARIABLE ANNUITY", "NONRES LIFE & VARIABLE ANNUITY" и ещё восемь.
# Фильтрация прямо по названию категории не дала бы ни одного совпадения — молча, и
# каждый импорт возвращал бы ноль строк. Форма та же, что у COUNTIES выше: в базе
# хранится название, разворот в сопоставимые значения происходит здесь.
#
# Значения взяты из самого реестра (77 различных пар код/описание);
# `python3 -m scripts.audit_license_types` перепроверяет соответствие по свежему
# файлу и сообщает о новых или несопоставленных значениях.
#
# Три категории есть на форме DFS, но не имеют класса индивидуальной лицензии,
# поэтому не сопоставлены ни с чем: агентства и фирмы аджастеров — это организации и
# лежат в другом экспорте, а у Debit Agent нет актуального TYCL. Они оставлены в
# списке, чтобы он совпадал с привычной формой, и интерфейс помечает их как
# недоступные, а не даёт чекбокс, который никогда ничего не найдёт.
LICENSE_CATEGORIES: dict[str, frozenset[str]] = {
    "Adjuster": frozenset({
        "ADJUSTER - ALL LINES",
        "ADJUSTER - MOTOR VEHICLE PD",
        "ADJUSTER - MOTOR VEHICLE PD & CASUALTY",
        "ADJUSTER - PROPERTY & CASUALTY",
        "ADJUSTER - WORKERS COMP",
        "NON-RES ADJUSTER - ALL LINES",
        "NON-RES ADJUSTER - HEALTH",
        "NON-RES ADJUSTER - MOTOR VEHICLE PD",
        "NON-RES ADJUSTER - PROPERTY & CASUALTY",
        "NON-RES ADJUSTER - WORKERS COMP",
        "NONRES DESIGNATED HOME STATE ALL LINES ADJUSTER",
        "NONRES PUBLIC ADJ - PROPERTY & CASUALTY",
        "NONRES PUBLIC ADJUSTER - ALL LINES",
        "PUBLIC ADJ.- FIRE & ALLIED LINES",
        "PUBLIC ADJUSTER - HEALTH",
        "PUBLIC ADJUSTER - PROPERTY",
        "PUBLIC ADJUSTER-ALL LINES",
    }),
    # [EN] Entities, not individuals — see the note above.
    # [RU] Организации, а не физлица — см. примечание выше.
    "Adjusting Firm": frozenset(),
    "Bail Bonds": frozenset({
        "LIMITED SURETY AGENT (BAIL)",
        "PROFESSIONAL BONDSMAN (BAIL)",
    }),
    "Company/MGA service staff": frozenset({
        "SERVICE REPRESENTATIVE",
    }),
    "Customer Representative": frozenset({
        "CUSTOMER REPRESENTATIVE",
        "LIMITED CUST REPRESENTATIVE",
    }),
    "Debit Agent": frozenset(),
    "Health": frozenset({
        "HEALTH",
        "NONRESIDENT HEALTH",
    }),
    "Insurance Agency": frozenset(),
    "Legal Expense": frozenset({
        "LEGAL EXPENSE",
        "NONRESIDENT LEGAL EXPENSE",
    }),
    # [EN] The tool's historical filter was four of these (the resident ones).
    # Selecting the whole category also brings in the NONRES classes — which the
    # county filter mostly excludes anyway, since a nonresident licensee rarely has
    # a Broward or Miami-Dade mailing address.
    # [RU] Исторический фильтр инструмента — четыре из этих значений (резидентские).
    # Выбор всей категории добавляет и классы NONRES, которые фильтр по округу всё
    # равно в основном отсекает: у нерезидента редко бывает почтовый адрес в Broward
    # или Miami-Dade.
    "Life & Annuity": frozenset({
        "LIFE",
        "LIFE & HEALTH",
        "LIFE INCL VAR ANNUITY & HEALTH",
        "LIFE INCL VARIABLE ANNUITY",
        "MILITARY REG (LIFE INSURANCE)",
        "NONRES LIFE & VARIABLE ANNUITY",
        "NONRES LIFE, HEALTH, & VAR ANN",
        "NONRESIDENT LIFE",
        "NONRESIDENT LIFE & HEALTH",
        "VARIABLE ANNUITY",
        "VIATICAL SETTLEMENT BROKER",
    }),
    "Limited Lines": frozenset({
        "CREDIT",
        "CROP HAIL & MULT PERIL CROP",
        "IN-TRANSIT & STORAGE PERS PROP",
        "INDUSTRIAL FIRE OR BURGLARY",
        "MOTOR VEH PD & MECH BREAKDOWN",
        "NON RESIDENT MOTOR VEHICLE RENTAL",
        "NON-RES PORTABLE ELECTRONICS OR EYEWEAR LEAD-AGENT",
        "NON-RES PRENEED FUNERAL AGREEMENT INSURANCE AGENT",
        "NON-RESIDENT TRAVEL INSURANCE",
        "NONRES INDUST FIRE OR BURGLARY",
        "NONRESIDENT CREDIT INSURANCE AGENT",
        "PORTABLE ELECTRONICS OR EYEWEAR LEAD - AGENT",
        "PRENEED FUNERAL AGREEMENT INSURANCE AGENT",
        "RESIDENT MOTOR VEHICLE RENTAL",
        "RESIDENT TRAVEL INSURANCE",
    }),
    "MGA": frozenset({
        "MANAGING GENERAL AGENT",
    }),
    "Mediator": frozenset({
        "MEDIATOR",
    }),
    "Navigator": frozenset({
        "NAVIGATOR",
    }),
    "Neutral Evaluator": frozenset({
        "NEUTRAL EVALUATOR",
    }),
    "Property & Casualty": frozenset({
        "GENERAL LINES (PROP & CAS)",
        "NONRES GEN LINES (PROP & CAS)",
        "NONRES PERSONAL LINES AGENT",
        "PERSONAL LINES AGENT",
        "TEMPORARY GENERAL LINES (PROP & CAS)",
    }),
    "Reinsurance": frozenset({
        "REINSURANCE INTERMED BROKER",
        "REINSURANCE INTERMED MANAGER",
        "REINSURANCE INTERMEDIARY BROKER",
    }),
    "Surplus Lines": frozenset({
        "NONRES SURPLUS LINES",
        "SURPLUS LINES",
    }),
    "Title": frozenset({
        "NON-RESIDENT TITLE AGENT",
        "TITLE",
    }),
    "Warranty": frozenset({
        "AUTOMOBILE WARRANTY",
        "HOME WARRANTY",
        "SERVICE WARRANTY",
    }),
}

# [EN] Category names, for the UI and for validating a stored selection.
# [RU] Названия категорий — для интерфейса и проверки сохранённого выбора.
LICENSE_TYPES: tuple[str, ...] = tuple(LICENSE_CATEGORIES.keys())

# [EN] Categories the individual registry cannot supply, so the UI can say so
# instead of offering a checkbox that silently matches nothing.
# [RU] Категории, которых нет в реестре физлиц, чтобы интерфейс мог об этом сказать,
# а не предлагал чекбокс, который молча ничего не найдёт.
UNAVAILABLE_LICENSE_TYPES: frozenset[str] = frozenset(
    name for name, values in LICENSE_CATEGORIES.items() if not values
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


def license_descs_for(category_names) -> frozenset[str]:
    """[EN] Expands category labels into the `License TYCL Desc` values to match on.
    Unknown labels are ignored here; use unknown_license_types() to report them.
    [RU] Разворачивает названия категорий в значения `License TYCL Desc`, по которым
    идёт сравнение. Неизвестные названия здесь игнорируются; сообщить о них —
    unknown_license_types()."""
    descs: set[str] = set()
    for name in category_names or ():
        descs |= LICENSE_CATEGORIES.get(name, frozenset())
    return frozenset(descs)


def unknown_license_types(types) -> list[str]:
    """[EN] Selected license categories that are not in the catalogue.
    [RU] Выбранные категории лицензий, отсутствующие в каталоге."""
    return sorted(t for t in (types or ()) if t not in LICENSE_CATEGORIES)
