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
    """Recurring non-trading dates for the B3 listed-equities market.

    The rules match B3's published 2026 market calendar. Provider-date validation remains
    a second line of defence for any exceptional closure B3 may announce separately.
    """
    easter = _easter_sunday(year)
    return {
        date(year, 1, 1),
        easter - timedelta(days=48),  # Carnival Monday
        easter - timedelta(days=47),  # Carnival Tuesday
        easter - timedelta(days=2),   # Good Friday
        date(year, 4, 21),            # Tiradentes
        date(year, 5, 1),             # Labour Day
        easter + timedelta(days=60),  # Corpus Christi
        date(year, 9, 7),             # Independence Day
        date(year, 10, 12),           # Our Lady of Aparecida
        date(year, 11, 2),            # All Souls' Day
        date(year, 11, 20),           # Black Awareness Day
        date(year, 12, 24),           # Christmas Eve - no equity session
        date(year, 12, 25),           # Christmas
        date(year, 12, 31),           # New Year's Eve - no equity session
    }


def is_b3_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in b3_market_holidays(day.year)


def previous_b3_trading_day(day: date) -> date:
    candidate = day - timedelta(days=1)
    while not is_b3_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate


def is_ash_wednesday(day: date) -> bool:
    return day == _easter_sunday(day.year) - timedelta(days=46)
