from __future__ import annotations

from datetime import date, timedelta


def _easter_sunday(year: int) -> date:
    """Gregorian Easter Sunday (Meeus/Jones/Butcher)."""
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


def b3_market_holidays(year: int) -> set[date]:
    """Recurring non-trading dates matching the reference B3 calendar."""
    easter = _easter_sunday(year)
    return {
        date(year, 1, 1),
        easter - timedelta(days=48),
        easter - timedelta(days=47),
        easter - timedelta(days=2),
        date(year, 4, 21),
        date(year, 5, 1),
        easter + timedelta(days=60),
        date(year, 9, 7),
        date(year, 10, 12),
        date(year, 11, 2),
        date(year, 11, 20),
        date(year, 12, 24),
        date(year, 12, 25),
        date(year, 12, 31),
    }


def is_b3_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in b3_market_holidays(day.year)


def is_ash_wednesday(day: date) -> bool:
    return day == _easter_sunday(day.year) - timedelta(days=46)
