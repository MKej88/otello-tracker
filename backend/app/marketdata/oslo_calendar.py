from __future__ import annotations

from datetime import date, timedelta


def _easter_sunday(year: int) -> date:
    """Return Gregorian Easter Sunday using the Meeus/Jones/Butcher algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def oslo_bors_closed_days(year: int) -> set[date]:
    """Known recurring full-day closures for Euronext Oslo cash equities.

    The rules match Euronext's published 2026 Oslo calendar. The Wednesday before
    Easter is a half trading day and therefore remains a trading day for the daily
    Safe Harbour capacity model.
    """
    easter = _easter_sunday(year)
    return {
        date(year, 1, 1),
        easter - timedelta(days=3),  # Maundy Thursday
        easter - timedelta(days=2),  # Good Friday
        easter + timedelta(days=1),  # Easter Monday
        date(year, 5, 1),
        date(year, 5, 17),
        easter + timedelta(days=39),  # Ascension Day
        easter + timedelta(days=50),  # Whit Monday
        date(year, 12, 24),
        date(year, 12, 25),
        date(year, 12, 26),
        date(year, 12, 31),
    }


def is_oslo_bors_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in oslo_bors_closed_days(day.year)


def oslo_bors_trading_days(start: date, end: date) -> list[date]:
    if end < start:
        return []
    return [
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
        if is_oslo_bors_trading_day(start + timedelta(days=offset))
    ]
