from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from io import StringIO


@dataclass(frozen=True)
class EuronextDailyClose:
    trading_date: str
    close: Decimal


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _detect_dialect(text: str) -> csv.Dialect:
    sample = "\n".join(text.splitlines()[:10])
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        return csv.excel


def _parse_decimal(value: str) -> Decimal:
    cleaned = value.strip().replace("\u00a0", "").replace(" ", "")
    if not cleaned:
        raise ValueError("Tom prisverdi")
    if "," in cleaned and "." in cleaned:
        # Whichever separator occurs last is treated as the decimal separator.
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    price = Decimal(cleaned)
    if not price.is_finite() or price <= 0:
        raise ValueError(f"Ugyldig Euronext-sluttkurs: {value}")
    return price


def _parse_date(value: str, date_order: str) -> str:
    value = value.strip()
    formats = {
        "DMY": ("%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%Y-%m-%d"),
        "MDY": ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%Y-%m-%d"),
        "YMD": ("%Y-%m-%d", "%Y/%m/%d"),
    }
    if date_order not in formats:
        raise ValueError("date_order må være DMY, MDY eller YMD")
    for fmt in formats[date_order]:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f"Kunne ikke tolke Euronext-dato: {value}")


def parse_euronext_historical_csv(text: str, *, date_order: str = "DMY") -> list[EuronextDailyClose]:
    """Parse a CSV exported from Euronext Live historical data.

    Euronext allows the user to choose delimiter/decimal/date formatting. The parser
    therefore detects the delimiter and accepts several English/Norwegian close/date
    headings. It deliberately requires an explicit date order to avoid ambiguous dates.
    """
    dialect = _detect_dialect(text)
    reader = csv.DictReader(StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ValueError("Euronext CSV mangler kolonneoverskrifter")

    normalized = {_normalize_header(name): name for name in reader.fieldnames}
    date_aliases = ("date", "dato", "trading date", "dato handel")
    close_aliases = (
        "closing price",
        "close",
        "last",
        "last price",
        "price",
        "sluttkurs",
        "siste",
        "siste kurs",
    )

    date_col = next((normalized[a] for a in date_aliases if a in normalized), None)
    close_col = next((normalized[a] for a in close_aliases if a in normalized), None)
    if date_col is None or close_col is None:
        raise ValueError(
            f"Fant ikke dato/sluttkurs i Euronext CSV. Kolonner: {reader.fieldnames}"
        )

    result: list[EuronextDailyClose] = []
    for row in reader:
        raw_date = (row.get(date_col) or "").strip()
        raw_close = (row.get(close_col) or "").strip()
        if not raw_date or not raw_close:
            continue
        result.append(
            EuronextDailyClose(
                trading_date=_parse_date(raw_date, date_order),
                close=_parse_decimal(raw_close),
            )
        )
    return sorted(result, key=lambda item: item.trading_date)
