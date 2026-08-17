from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from app.buybacks.euronext import BuybackStatus, parse_euronext_buyback_status
from app.newsweb.normalization import normalize_weekly_body

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}


def _iso_date(value: str) -> str:
    match = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", value.strip())
    if not match:
        raise ValueError(f"Ugyldig NewsWeb-buybackdato: {value}")
    day, month, year = match.groups()
    return datetime(int(year), _MONTHS[month.lower()], int(day)).date().isoformat()


def _integer(value: str) -> int:
    return int(value.replace(",", "").replace(" ", ""))


def _decimal(value: str) -> Decimal:
    return Decimal(value.replace(",", "").strip())


def _parse_first_program_week(clean: str) -> BuybackStatus | None:
    """Parse the documented first-week status variant that omits cumulative/treasury text.

    Otello's 26 June 2023 status is the first status of a newly initiated program. It
    reports the initiation date, exact first trading period, weekly shares/VWAP/value and
    program maximum, but no separate cumulative or treasury sentence. We only infer
    cumulative == weekly and treasury == weekly when the announced program date equals
    the first trading date. This keeps the fallback narrow and auditable.
    """
    ref = re.search(
        r"notice(?:s)? from (\d{1,2} [A-Za-z]+ \d{4}) announcing the initiation of the share buyback program",
        clean,
        re.I,
    )
    period = re.search(
        r"From (\d{1,2} [A-Za-z]+ \d{4}) through (\d{1,2} [A-Za-z]+ \d{4}),"
        r".*?has bought ([\d, ]+) shares .*?average price of NOK ([\d.,]+)"
        r" and a total value of NOK ([\d, ]+)",
        clean,
        re.I,
    )
    maximum = re.search(
        r"maximum number of shares that can be purchased under this buyback program is ([\d, ]+)",
        clean,
        re.I,
    )
    if not (ref and period and maximum):
        return None

    reference_date = _iso_date(ref.group(1))
    period_start = _iso_date(period.group(1))
    if reference_date != period_start:
        return None

    shares = _integer(period.group(3))
    avg_price = _decimal(period.group(4))
    amount = _decimal(period.group(5))
    if shares <= 0 or avg_price <= 0 or amount <= 0:
        return None

    return BuybackStatus(
        program_reference_date=reference_date,
        period_start=period_start,
        period_end=_iso_date(period.group(2)),
        period_shares=shares,
        period_avg_price_nok=avg_price,
        period_amount_nok=amount,
        cumulative_program_shares=shares,
        cumulative_program_avg_price_nok=avg_price,
        cumulative_program_amount_nok=amount,
        max_program_shares=_integer(maximum.group(1)),
        treasury_shares_after=shares,
    )


def parse_newsweb_weekly_status(text: str) -> BuybackStatus:
    """Parse current and documented historical NewsWeb weekly buyback wording."""
    clean = normalize_weekly_body(text)
    try:
        return parse_euronext_buyback_status(clean)
    except ValueError as standard_error:
        first_week = _parse_first_program_week(clean)
        if first_week is not None:
            return first_week
        raise standard_error
