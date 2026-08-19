"""
[EN]
Jinja filters — presentation-only formatting of model fields. Registered on the
app in create_app(), used from the templates.

[RU]
Jinja-фильтры — чисто презентационное форматирование полей модели.
Регистрируются на приложении в create_app(), используются из шаблонов.
"""

from datetime import timezone as _dt_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

UTC = _dt_timezone.utc


def in_timezone(value, tz_name: str) -> str:
    """[EN] Renders a timestamp in the app's configured timezone.

    Every timestamp in this app is a Postgres `timestamptz`, which psycopg2 hands
    back as an aware datetime in the SESSION's zone — and the session is Etc/UTC.
    Printing it directly is what put "06:46" in the history next to a schedule
    reading "09:45": the same instant, shown in two different zones on one page.
    Everything user-facing goes through here so that cannot happen again.

    A naive value is assumed to be UTC rather than guessed at, and an unknown zone
    falls back to UTC rather than raising — a bad setting should make the page look
    wrong, not break it.

    [RU] Отображает метку времени в настроенном часовом поясе приложения.

    Каждая метка в приложении — это `timestamptz` в Postgres, который psycopg2
    возвращает как aware datetime в зоне СЕССИИ, а сессия — Etc/UTC. Прямой вывод
    и дал "06:46" в истории рядом с расписанием "09:45": один момент, показанный в
    двух зонах на одной странице. Всё, что видит пользователь, идёт через эту
    функцию, чтобы это не повторилось.

    Naive-значение считается UTC, а не угадывается; неизвестная зона откатывается к
    UTC, а не выбрасывает исключение — неверная настройка должна портить вид
    страницы, а не ломать её."""
    if value is None:
        return "—"

    try:
        tz = ZoneInfo(tz_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")

    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)

    return value.astimezone(tz).strftime("%Y-%m-%d %H:%M")


def to_duration(delta) -> str:
    """[EN] Formats a timedelta as a compact human duration for the import history
    ("1h 04m", "3m 12s", "8s"). Postgres returns the `duration` column as a
    timedelta; None means the run never finished and had no heartbeat to measure to.

    [RU] Форматирует timedelta в компактную человеческую длительность для истории
    импортов ("1h 04m", "3m 12s", "8s"). Postgres отдаёт колонку `duration` как
    timedelta; None означает, что запуск не завершился и мерить не от чего."""
    if delta is None:
        return "—"

    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "—"
    if seconds < 60:
        return f"{seconds}s"

    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds:02d}s"

    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def to_tel_href(phone: str) -> str:
    """Builds a tel: link from a phone number so that tapping it on mobile
    offers to place a call.

    Готовит tel: ссылку из телефона, чтобы на мобильном по тапу
    предлагалось позвонить."""
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not digits:
        return ""
    if len(digits) == 10:
        digits = "1" + digits  # prepend the US country code / добавляем код страны США
    return f"tel:+{digits}"
