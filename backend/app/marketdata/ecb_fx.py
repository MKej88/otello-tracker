from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal, getcontext
from io import StringIO
from urllib.parse import urlencode
from urllib.request import Request, urlopen

getcontext().prec = 28

ECB_EXR_URL = "https://data-api.ecb.europa.eu/service/data/EXR/D.BRL+NOK+USD.EUR.SP00.A"


@dataclass(frozen=True)
class CrossRate:
    trading_date: str
    base_currency: str
    quote_currency: str
    rate: Decimal


def build_ecb_url(start_date: str, end_date: str | None = None) -> str:
    query = {"startPeriod": start_date, "format": "csvdata", "detail": "dataonly"}
    if end_date:
        query["endPeriod"] = end_date
    return f"{ECB_EXR_URL}?{urlencode(query)}"


def parse_ecb_csv(text: str) -> dict[str, dict[str, Decimal]]:
    """Return {date: {currency: units_per_eur}} from ECB EXR CSV."""
    rows: dict[str, dict[str, Decimal]] = {}
    reader = csv.DictReader(StringIO(text))
    required = {"CURRENCY", "TIME_PERIOD", "OBS_VALUE"}
    if not required.issubset(set(reader.fieldnames or [])):
        raise ValueError(f"Uventet ECB CSV-felter: {reader.fieldnames}")

    for row in reader:
        currency = row["CURRENCY"].strip().upper()
        if currency not in {"BRL", "NOK", "USD"}:
            continue
        value = row["OBS_VALUE"].strip()
        if not value:
            continue
        rows.setdefault(row["TIME_PERIOD"], {})[currency] = Decimal(value)
    return rows


def derive_nok_cross_rates(ecb_rows: dict[str, dict[str, Decimal]]) -> list[CrossRate]:
    """Derive BRL/NOK and USD/NOK from ECB's EUR reference rates.

    ECB quotes units of each currency per EUR, so currency/NOK equals
    NOK-per-EUR divided by currency-per-EUR.
    """
    result: list[CrossRate] = []
    for trading_date, values in sorted(ecb_rows.items()):
        nok = values.get("NOK")
        if nok is None:
            continue
        for base in ("BRL", "USD"):
            denominator = values.get(base)
            if denominator is None or denominator == 0:
                continue
            result.append(
                CrossRate(
                    trading_date=trading_date,
                    base_currency=base,
                    quote_currency="NOK",
                    rate=nok / denominator,
                )
            )
    return result


def fetch_ecb_csv(start_date: str, end_date: str | None = None, timeout: int = 30) -> tuple[str, str]:
    url = build_ecb_url(start_date, end_date)
    request = Request(
        url,
        headers={
            "Accept": "text/csv",
            "User-Agent": "otello-tracker/0.4 (+private research)",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return url, response.read().decode("utf-8-sig")
