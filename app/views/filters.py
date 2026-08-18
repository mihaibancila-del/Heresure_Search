"""
[EN]
Jinja filters — presentation-only formatting of model fields. Registered on the
app in create_app(), used from the templates.

[RU]
Jinja-фильтры — чисто презентационное форматирование полей модели.
Регистрируются на приложении в create_app(), используются из шаблонов.
"""


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
